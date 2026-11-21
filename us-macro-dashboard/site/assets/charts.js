/* 美国宏观数据看板 - 共享图表渲染逻辑（支持暗/明双主题） */
(function(){
  // 从 CSS 变量读取主题色，图表颜色随主题自动切换
  function readTheme(){
    var cs = getComputedStyle(document.documentElement);
    var v = function(name){ return cs.getPropertyValue(name).trim(); };
    return {
      bg:'transparent', card:v('--card'), line:v('--line2'),
      text:v('--text'), text2:v('--text2'), text3:v('--text3'),
      splitline:v('--splitline'),
      red:v('--red'), green:v('--green'), blue:v('--blue'), orange:v('--orange'),
      purple:v('--purple'), cyan:v('--cyan')
    };
  }
  var THEME = readTheme();

  // 主题切换：黑金(dark) <-> 明快(light)，按时间自动选默认，手动选择后持久化覆盖
  var STORAGE_KEY = 'us-macro-theme';
  // 根据当前小时判断默认主题：6:00~18:00 明快，其余黑金
  function timeDefaultTheme(){
    var h = new Date().getHours();
    return (h >= 6 && h < 18) ? 'light' : 'dark';
  }
  function applyTheme(theme, persist){
    document.documentElement.setAttribute('data-theme', theme);
    THEME = readTheme();
    if(persist){ try{ localStorage.setItem(STORAGE_KEY, theme); }catch(e){} }
    // 更新切换按钮图标
    var btn = document.querySelector('.theme-toggle');
    if(btn) btn.textContent = (theme === 'light') ? '☀️' : '🌙';
  }
  function initTheme(){
    var saved = null;
    try{ saved = localStorage.getItem(STORAGE_KEY); }catch(e){}
    // 有手动选择则沿用；否则按时间自动选默认
    applyTheme(saved ? saved : timeDefaultTheme(), false);
  }

  // 重渲染所有已初始化的图表实例
  var chartInstances = [];

  // 把日期戳（如 2018-03-01）显示为"统计月份/季度"，避免误读为"发布日期"
  // isQuarterly：是否为季频指标（只有季频才把 -10-01 等显示为 Q4，否则 10 月就是 10 月）
  function formatPeriod(axisValue, isQuarterly){
    if(!axisValue) return axisValue;
    var s = String(axisValue);
    var m = s.match(/^(\d{4})-(\d{2})-\d{2}$/);
    if(!m) return s;
    var y = m[1], mo = m[2];
    if(isQuarterly){
      if(s.endsWith('-01-01')) return y + ' Q1';
      if(s.endsWith('-04-01')) return y + ' Q2';
      if(s.endsWith('-07-01')) return y + ' Q3';
      if(s.endsWith('-10-01')) return y + ' Q4';
      return y;
    }
    return y + '年' + parseInt(mo,10) + '月';
  }

  // 日频序列：tooltip 精确到日，避免"2026年11月"掩盖具体哪一天
  function formatDay(v){
    var m = String(v).match(/^(\d{4})-(\d{2})-(\d{2})$/);
    return m ? (m[1] + '年' + parseInt(m[2],10) + '月' + parseInt(m[3],10) + '日') : v;
  }

  function tooltipFormatter(params, releaseRule, unit, dayFmt){
    if(!params || !params.length) return '';
    var isQuarterly = releaseRule && releaseRule.indexOf('统计季度') !== -1;
    var period = dayFmt ? formatDay(params[0].axisValue) : formatPeriod(params[0].axisValue, isQuarterly);
    var s = '<div style="font-weight:600;margin-bottom:2px;">统计期：' + period + '</div>';
    params.forEach(function(p){
      var v;
      if(p.value==null || p.value==='') v = '—';
      else if(unit === 'bp') v = fmtBp(p.value) + 'bp';   // 差值类图表带符号，便于分辨正负
      else v = Number(p.value).toFixed(2);
      s += p.marker + p.seriesName + '：' + v + '<br/>';
    });
    if(releaseRule){
      s += '<div style="margin-top:4px;font-size:11px;opacity:0.75;border-top:1px solid rgba(128,128,128,0.3);padding-top:3px;">' + releaseRule + '</div>';
    }
    return s;
  }

  // 构建 Y 轴配置：双轴（dual_axis）时左轴=series[yAxisIndex 0]，右轴=series[yAxisIndex 1]
  function buildYAxis(data, big){
    var dual = data.dual_axis === true;
    var base = {
      type:'value',
      axisLine:{show:false}, axisTick:{show:false},
      axisLabel:{color:THEME.text3, fontSize: big?11:10}
    };
    if(!dual){
      base.splitLine = {lineStyle:{color:THEME.splitline}};
      return base;
    }
    var left = Object.assign({}, base);
    left.position = 'left';
    left.splitLine = {lineStyle:{color:THEME.splitline}};
    left.axisLabel = {color:THEME.text3, fontSize: big?11:10};
    var right = Object.assign({}, base);
    right.position = 'right';
    right.splitLine = {show:false};
    right.axisLabel = {color:THEME.text3, fontSize: big?11:10};
    return [left, right];
  }

  // 构建折线图 option（支持 dataZoom 拖动缩放；big 模式显示 slider 且字号更大）
  // zoomStartIndex: 默认缩放起始的数据点索引（如 2022 年对应的索引），未提供则显示全部
  function buildLineOption(data, big, zoomStartIndex){
    var series = data.series.map(function(s, i){
      var dashed = !!s.dashed;
      return {
        name: s.name, type:'line', data: s.values,
        smooth: dashed ? false : true,
        showSymbol: s.showSymbol === true,
        symbol: s.showSymbol === true ? 'circle' : 'none',
        symbolSize: big ? 7 : 5,
        connectNulls: s.connectNulls === true,
        lineStyle:{width: big?2.5:2, color:s.color, type: dashed ? 'dashed' : 'solid'},
        itemStyle:{color:s.color},
        areaStyle: (i===0 && data.series.length===1) ? {color:s.color, opacity:0.15} : null,
        emphasis:{focus:'series'},
        yAxisIndex: s.yAxisIndex === 1 ? 1 : 0
      };
    });
    var fs = big ? 13 : 11;   // 字号
    var n = data.dates.length;
    // 用百分比设置默认缩放范围（比 startValue 更可靠，不依赖精确字符串匹配）
    var zoomCfg = {};
    if(zoomStartIndex != null && zoomStartIndex > 0 && zoomStartIndex < n){
      zoomCfg.start = Math.round(zoomStartIndex / n * 1000) / 10;   // 转百分比
      zoomCfg.end = 100;
    }
    var option = {
      backgroundColor:THEME.bg,
      grid:{left: big?64:48, right: data.dual_axis ? (big?72:56) : 20, top:28, bottom: big?64:44},
      tooltip:{trigger:'axis',
        backgroundColor:THEME.card, borderColor:THEME.line,
        textStyle:{color:THEME.text, fontSize:12},
        formatter:function(params){ return tooltipFormatter(params, data.release_rule, data.unit, data.day_format === true); }
      },
      legend:{top:0, right:0, textStyle:{color:THEME.text2, fontSize:fs}, itemWidth:14, itemHeight:8},
      xAxis:{type:'category', data:data.dates, boundaryGap:false,
        axisLine:{lineStyle:{color:THEME.line}},
        axisLabel:{color:THEME.text3, fontSize: big?11:10},
        axisTick:{show:false}
      },
      yAxis: buildYAxis(data, big),
      // 拖拽/滚轮缩放：周期较长时自由拖动范围
      dataZoom:[
        Object.assign({ type:'inside', xAxisIndex:0, filterMode:'none', zoomOnMouseWheel:true, moveOnMouseMove:true }, zoomCfg),
        Object.assign({ type:'slider', xAxisIndex:0, show:big, height: big?22:18, bottom: big?10:6,
          borderColor:THEME.line, backgroundColor:'transparent',
          fillerColor:'rgba(139,92,246,0.15)',
          handleStyle:{color:THEME.purple}, moveHandleStyle:{color:THEME.purple},
          textStyle:{color:THEME.text3, fontSize:10},
          dataBackground:{lineStyle:{color:THEME.line}, areaStyle:{color:'rgba(139,92,246,0.06)'}} }, zoomCfg)
      ]
    };
    option.series = series;
    // 可选参考线（如利差/差值的 0 轴）：data.mark_line = 0
    if(data.mark_line != null && series.length){
      series[0].markLine = {
        silent: true, symbol: 'none', animation: false,
        data: [{yAxis: data.mark_line}],
        lineStyle: {color: THEME.text3, type: 'dashed', width: 1, opacity: 0.9},
        label: {show: false}
      };
    }
    return option;
  }

  // 根据 dataZoom 当前可见区间，动态重设 Y 轴范围（随 X 轴缩放自动适配）
  // 双轴（dual_axis）时，左轴拟合 yAxisIndex=0 的序列，右轴拟合 yAxisIndex=1 的序列，各自独立缩放
  function fitYAxis(chart, data){
    if(!chart || !data) return;
    var opt = chart.getOption();
    var dz = opt.dataZoom;
    if(!dz || !dz.length) return;
    var startPct = dz[0].start == null ? 0 : dz[0].start;   // 0~100
    var endPct = dz[0].end == null ? 100 : dz[0].end;
    var n = data.dates.length;
    if(!n) return;
    var i0 = Math.floor(n * startPct / 100);
    var i1 = Math.ceil(n * endPct / 100);
    if(i1 > n) i1 = n;
    if(i0 < 0) i0 = 0;
    if(i1 <= i0) i1 = i0 + 1;

    function rangeFor(axisIndex){
      var lo = Infinity, hi = -Infinity;
      data.series.forEach(function(s){
        if((s.yAxisIndex === 1 ? 1 : 0) !== axisIndex) return;
        for(var i=i0;i<i1;i++){
          var v = s.values[i];
          if(v==null || v==='' || isNaN(v)) continue;
          if(v < lo) lo = v;
          if(v > hi) hi = v;
        }
      });
      if(lo === Infinity || hi === -Infinity) return null;
      var pad = (hi - lo) * 0.08;
      if(pad === 0) pad = Math.abs(hi) * 0.05 || 1;
      var ymin = Math.round((lo - pad) * 10000) / 10000;
      var ymax = Math.round((hi + pad) * 10000) / 10000;
      if(!(ymax > ymin)){ ymax = ymin + 1; }
      return { min: ymin, max: ymax };
    }

    if(data.dual_axis){
      var left = rangeFor(0), right = rangeFor(1);
      var axes = [{}, {}];
      if(left){ axes[0] = { min: left.min, max: left.max }; }
      if(right){ axes[1] = { min: right.min, max: right.max }; }
      chart.setOption({ yAxis: axes });
      return;
    }
    var r = rangeFor(0);
    if(r) chart.setOption({ yAxis:{ min: r.min, max: r.max } });
  }

  // 把日期字符串（如 '2022-01-01'）转成 dates 数组中第一个 >= 该日期的索引
  function dateToIndex(dates, target){
    if(!dates || !dates.length) return null;
    if(!target) return 0;
    // 归一化比较：取前 7 个字符 YYYY-MM 或全字符串，简单字符串比较即可（日期为升序）
    for(var i=0;i<dates.length;i++){
      if(String(dates[i]) >= String(target)) return i;
    }
    return dates.length - 1;
  }

  window.renderLineChart = function(el, data, opts){
    opts = opts || {};
    if(!data || !data.dates || data.dates.length < 2) return;
    var chart = echarts.init(el, null, {renderer:'canvas'});
    // 默认缩放起点：优先用调用方传入的索引，其次用数据里的 zoom_start 日期
    var zi = opts.zoomStartIndex;
    if(zi == null && data.zoom_start) zi = dateToIndex(data.dates, data.zoom_start);
    chart.setOption(buildLineOption(data, opts.big === true, zi));
    // Y 轴随 X 轴缩放自动适配
    chart.on('datazoom', function(){ fitYAxis(chart, data); });
    // 初始化后立即按当前可见区间拟合一次 Y 轴（避免默认 0 起/异常极值）
    fitYAxis(chart, data);
    chartInstances.push(chart);
    window.addEventListener('resize', function(){ chart.resize(); });
    return chart;
  };

  // 散点图（菲利普斯曲线等）：data = { xName, yName, series:[{name, color, symbolSize, data:[[x,y],...]}], markLine... }
  window.renderScatter = function(el, data){
    if(!data || !data.series || !data.series.length) return;
    var series = data.series.map(function(s){
      return {
        name: s.name, type:'scatter', data: s.data,
        symbolSize: s.symbolSize || 8,
        itemStyle: {color: s.color, opacity: s.opacity == null ? 0.75 : s.opacity},
        emphasis: {itemStyle:{opacity:1}}
      };
    });
    var option = {
      backgroundColor: THEME.bg,
      grid:{left:56, right:24, top:40, bottom:48},
      tooltip:{trigger:'item',
        backgroundColor:THEME.card, borderColor:THEME.line,
        textStyle:{color:THEME.text, fontSize:12},
        formatter:function(p){
          var pt = p.value;
          return '<div style="font-weight:600;margin-bottom:2px;">'+p.seriesName+'</div>'+
                 (data.xName||'x')+'：'+pt[0]+'<br/>'+
                 (data.yName||'y')+'：'+Number(pt[1]).toFixed(2)+'<br/>'+
                 (p.data[2] ? '统计期：'+formatPeriod(p.data[2], false) : '');
        }
      },
      legend:{top:0, right:0, textStyle:{color:THEME.text2, fontSize:11}, itemWidth:12, itemHeight:8},
      xAxis:{type:'value', name:data.xName||'', nameLocation:'middle', nameGap:30,
        nameTextStyle:{color:THEME.text2, fontSize:12},
        axisLine:{lineStyle:{color:THEME.line}},
        axisLabel:{color:THEME.text3, fontSize:11},
        splitLine:{lineStyle:{color:THEME.splitline}},
        scale:true},
      yAxis:{type:'value', name:data.yName||'', nameLocation:'middle', nameGap:42,
        nameTextStyle:{color:THEME.text2, fontSize:12},
        axisLine:{lineStyle:{color:THEME.line}},
        axisLabel:{color:THEME.text3, fontSize:11},
        splitLine:{lineStyle:{color:THEME.splitline}},
        scale:true},
      series: series
    };
    var chart = echarts.init(el, null, {renderer:'canvas'});
    chart.setOption(option);
    chartInstances.push(chart);
    window.addEventListener('resize', function(){ chart.resize(); });
    return chart;
  };

  // ===== 瀑布图：BEI 变动归因 =====
  // data = {kind:'waterfall', unit:'bp', default:'1m', windows:[
  //   {key,label,from,to,nom0,nom1,real0,real1,bei0,bei1,leg_nom,leg_real}]}
  // 恒等式：BEI = 名义 − 实际（bp）；名义腿贡献 = Δ名义，实际腿贡献 = −Δ实际
  var wfCharts = {};

  function fmtBp(v){
    var n = Number(v);
    if(isNaN(n)) return '—';
    return (n > 0 ? '+' : (n < 0 ? '−' : '')) + Math.abs(n).toFixed(1);
  }
  function md(s){ return s ? String(s).slice(5).replace('-', '/') : ''; }

  function wfOption(w, data){
    var t = THEME;
    var a = w.bei0, b = a + w.leg_nom, c = b + w.leg_real;     // 逐步累计（期末应等于 bei1）
    var names  = ['期初 BEI', '名义腿', '实际腿', '期末 BEI'];
    var base   = [Math.min(0, a), Math.min(a, b), Math.min(b, c), Math.min(0, c)];
    var size   = [Math.abs(a), Math.abs(w.leg_nom), Math.abs(w.leg_real), Math.abs(c)];
    var colors = [t.text2,
                  w.leg_nom  >= 0 ? t.red : t.green,
                  w.leg_real >= 0 ? t.red : t.green,
                  t.purple];
    var texts  = [a.toFixed(1), fmtBp(w.leg_nom) + 'bp', fmtBp(w.leg_real) + 'bp', c.toFixed(1)];

    var lo = Math.min(a, b, c), hi = Math.max(a, b, c);
    var pad = Math.max((hi - lo) * 0.45, 6);

    return {
      backgroundColor: t.bg,
      grid: {left: 52, right: 24, top: 34, bottom: 30},
      tooltip: {
        trigger: 'item',
        backgroundColor: t.card, borderColor: t.line,
        textStyle: {color: t.text, fontSize: 12},
        formatter: function(p){
          var i = p.dataIndex;
          var head = '<div style="font-weight:600;margin-bottom:3px;">' + names[i] + '</div>';
          if(i === 0) return head + 'BEI ' + a.toFixed(1) + 'bp<br/><span style="opacity:.7">' + w.from + '</span>';
          if(i === 3) return head + 'BEI ' + c.toFixed(1) + 'bp<br/><span style="opacity:.7">' + w.to + '</span>';
          if(i === 1) return head + '名义 10Y：' + (w.nom0/100).toFixed(2) + '% → ' + (w.nom1/100).toFixed(2) +
                            '%（' + fmtBp(w.nom1 - w.nom0) + 'bp）<br/>对 BEI 贡献：' + fmtBp(w.leg_nom) + 'bp';
          return head + 'TIPS 实际 10Y：' + (w.real0/100).toFixed(2) + '% → ' + (w.real1/100).toFixed(2) +
                 '%（' + fmtBp(w.real1 - w.real0) + 'bp）<br/>对 BEI 贡献：' + fmtBp(w.leg_real) + 'bp';
        }
      },
      xAxis: {
        type: 'category', data: names,
        axisLine: {lineStyle: {color: t.line}},
        axisTick: {show: false},
        axisLabel: {color: t.text3, fontSize: 11}
      },
      yAxis: {
        type: 'value', name: 'bp', nameTextStyle: {color: t.text3, fontSize: 10},
        min: Math.floor(lo - pad), max: Math.ceil(hi + pad),
        axisLine: {show: false}, axisTick: {show: false},
        axisLabel: {color: t.text3, fontSize: 10},
        splitLine: {lineStyle: {color: t.splitline}}
      },
      series: [
        {name: 'base', type: 'bar', stack: 'wf', silent: true, barWidth: '46%',
         data: base, itemStyle: {color: 'transparent'}, emphasis: {disabled: true}},
        {name: 'value', type: 'bar', stack: 'wf', barWidth: '46%',
         data: size.map(function(v, i){
           return {value: v, itemStyle: {color: colors[i], borderRadius: 2}};
         }),
         label: {show: true, position: 'top', distance: 6, color: t.text2, fontSize: 11,
                 formatter: function(p){ return texts[p.dataIndex]; }},
         emphasis: {focus: 'series'}}
      ]
    };
  }

  window.renderWaterfall = function(el, data, key){
    if(!el || !data || !data.windows || !data.windows.length) return;
    var k = key || el.getAttribute('data-wf-key') || data.default;
    var w = null;
    data.windows.forEach(function(x){ if(x.key === k) w = x; });
    if(!w) w = data.windows[0];
    el.setAttribute('data-wf-key', w.key);

    var chart = wfCharts[el.id];
    if(!chart || (chart.isDisposed && chart.isDisposed())){
      if(chart){ try{ chart.dispose(); }catch(e){} }
      chart = echarts.init(el, null, {renderer:'canvas'});
      wfCharts[el.id] = chart;
      chartInstances.push(chart);
      window.addEventListener('resize', function(){ chart.resize(); });
    }
    chart.setOption(wfOption(w, data), true);

    // 同步卡片里的动态口径行
    var note = document.getElementById(el.id + '-note');
    if(note){
      note.innerHTML = '区间 ' + md(w.from) + ' → ' + md(w.to) +
        '：名义 ' + fmtBp(w.nom1 - w.nom0) + 'bp · 实际 ' + fmtBp(w.real1 - w.real0) + 'bp · ' +
        'BEI ' + fmtBp(w.bei1 - w.bei0) + 'bp（其中名义腿 ' + fmtBp(w.leg_nom) +
        '、实际腿 ' + fmtBp(w.leg_real) + '）';
    }
    return chart;
  };

  // 点击图表卡片，弹出全屏模态框放大展示，支持拖动范围缩放
  var modalChart = null;
  function closeModal(){
    var m = document.getElementById('chart-modal');
    if(m) m.classList.remove('show');
    if(modalChart){ try{ modalChart.dispose(); }catch(e){} modalChart = null; }
    document.body.style.overflow = '';
  }
  window.openChartModal = function(card, data, title, sub){
    var m = document.getElementById('chart-modal');
    if(!m) return;
    document.getElementById('modal-title').textContent = title || '';
    document.getElementById('modal-sub').textContent = sub || '';
    m.classList.add('show');
    document.body.style.overflow = 'hidden';
    // 等模态框布局完成后再初始化，确保尺寸正确
    setTimeout(function(){
      var box = document.getElementById('modal-chart');
      if(modalChart){ try{ modalChart.dispose(); }catch(e){} }
      modalChart = echarts.init(box, null, {renderer:'canvas'});
      // 默认从 2022 年开始展示（避开疫情期异常值），Y 轴随缩放自动适配
      var si = dateToIndex(data.dates, '2022-01-01');
      modalChart.setOption(buildLineOption(data, true, si));
      modalChart.on('datazoom', function(){ fitYAxis(modalChart, data); });
      // 初始化后立即按 2022 起的可见区间拟合一次 Y 轴
      fitYAxis(modalChart, data);
      window.addEventListener('resize', function(){ modalChart && modalChart.resize(); });
    }, 30);
  };

  window.renderSpark = function(el){
    var raw = el.getAttribute('data-spark');
    var vals;
    try{ vals = JSON.parse(raw || '[]'); }catch(e){ vals = []; }
    if(!Array.isArray(vals) || vals.length < 2) return;
    var chart = echarts.init(el, null, {renderer:'canvas'});
    var up = vals[vals.length-1] >= vals[0];
    var color = up ? THEME.red : THEME.green;
    chart.setOption({
      backgroundColor:THEME.bg,
      grid:{left:0, right:0, top:4, bottom:0},
      xAxis:{type:'category', show:false, data:vals.map(function(_,i){return i;}), boundaryGap:false},
      yAxis:{type:'value', show:false, scale:true},
      series:[{type:'line', data:vals, smooth:true, showSymbol:false,
        lineStyle:{width:1.5, color:color},
        areaStyle:{color:color, opacity:0.12}}]
    });
    chartInstances.push(chart);
  };

  // 页面加载后自动渲染：大图用 data-chart 属性，迷你图用 data-spark
  document.addEventListener('DOMContentLoaded', function(){
    initTheme();
    document.querySelectorAll('.m-spark').forEach(function(el){
      try{ window.renderSpark(el); }catch(e){}
    });
    // 图表卡片点击放大：卡片带 data-chart-id 则绑定
    document.querySelectorAll('.chart-card').forEach(function(card){
      var box = card.querySelector('.chart-box');
      if(!box) return;
      if(card.hasAttribute('data-nozoom')) return;   // 瀑布图等不参与放大
      var id = box.id;
      card.classList.add('zoomable');
      card.addEventListener('click', function(ev){
        // 点击 dataZoom slider 手柄时不触发放大
        if(ev.target && ev.target.closest && ev.target.closest('.echarts-datanone')) return;
        var data = window.__CHARTS && window.__CHARTS[id];
        if(!data || data.kind === 'waterfall') return;
        var t = card.querySelector('.c-title');
        var s = card.querySelector('.c-sub');
        window.openChartModal(card, data,
          t ? t.textContent : '',
          s ? s.textContent : '');
      });
    });
    // 瀑布图窗口切换（近1周/1月/3月/6月/1年）
    document.querySelectorAll('.wf-tabs').forEach(function(box){
      box.addEventListener('click', function(ev){
        var btn = ev.target && ev.target.closest ? ev.target.closest('.wf-tab') : null;
        if(!btn) return;
        ev.stopPropagation();
        box.querySelectorAll('.wf-tab').forEach(function(x){ x.classList.toggle('active', x === btn); });
        var id = box.getAttribute('data-target');
        var el = document.getElementById(id);
        var rec = window.__WATERFALLS && window.__WATERFALLS[id];
        if(el && rec){
          rec.key = btn.getAttribute('data-key');
          window.renderWaterfall(el, rec.data, rec.key);
        }
      });
    });
    // 关闭模态框
    var modal = document.getElementById('chart-modal');
    if(modal){
      modal.addEventListener('click', function(ev){
        if(ev.target === modal || ev.target.classList.contains('modal-close')) closeModal();
      });
      var closeBtn = modal.querySelector('.modal-close');
      if(closeBtn) closeBtn.addEventListener('click', closeModal);
    }
    document.addEventListener('keydown', function(ev){
      if(ev.key === 'Escape') closeModal();
    });
    // 绑定主题切换按钮
    var btn = document.querySelector('.theme-toggle');
    if(btn){
      btn.addEventListener('click', function(){
        var cur = document.documentElement.getAttribute('data-theme');
        applyTheme(cur === 'light' ? 'dark' : 'light', true);
        // 重渲染所有图表以应用新配色
        chartInstances.forEach(function(c){ try{ c.dispose(); }catch(e){} });
        chartInstances = [];
        document.querySelectorAll('.m-spark').forEach(function(el){
          try{ window.renderSpark(el); }catch(e){}
        });
        if(window.__CHARTS){
          Object.keys(window.__CHARTS).forEach(function(id){
            var el = document.getElementById(id);
            var d = window.__CHARTS[id];
            if(!el || !d || d.kind === 'waterfall') return;
            window.renderLineChart(el, d);
          });
        }
        if(window.__WATERFALLS){
          Object.keys(window.__WATERFALLS).forEach(function(id){
            var el = document.getElementById(id);
            if(el){
              var rec = window.__WATERFALLS[id];
              window.renderWaterfall(el, rec.data, el.getAttribute('data-wf-key') || rec.key);
            }
          });
        }
        if(window.__SCATTERS){
          Object.keys(window.__SCATTERS).forEach(function(id){
            var el = document.getElementById(id);
            if(el) window.renderScatter(el, window.__SCATTERS[id]);
          });
        }
      });
    }
  });
})();
