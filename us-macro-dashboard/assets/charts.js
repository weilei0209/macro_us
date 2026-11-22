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

  // 日期 -> 季度标签（2026-07-01 → 2026 Q3）
  function quarterLabel(v, lag){
    var m = String(v).match(/^(\d{4})-(\d{2})/);
    if(!m) return '';
    var y = parseInt(m[1],10), q = Math.ceil(parseInt(m[2],10)/3) - (lag || 0);
    while(q <= 0){ q += 4; y -= 1; }   // 跨年回退（Q1 的上一季是去年 Q4）
    return y + ' Q' + q;
  }

  // 日期 -> 月份标签，lag 用于"阶梯延续"的月频序列（当期读到的是上月的值）
  function monthLabel(v, lag){
    var m = String(v).match(/^(\d{4})-(\d{2})/);
    if(!m) return '';
    var y = parseInt(m[1],10), mo = parseInt(m[2],10) - (lag || 0);
    while(mo <= 0){ mo += 12; y -= 1; }
    return y + '年' + mo + '月';
  }

  function tooltipFormatter(params, releaseRule, unit, dayFmt, period, seriesMeta, tipExtra){
    if(!params || !params.length) return '';
    // 横轴周期判定：显式 period 优先。像工资图（AHE 月频 + ECI 季频）规则文案里
    // 同时出现"统计月"和"统计季度"，只按"统计季度"判断会把 2026-02 这类月份点
    // 渲染成只有"2026"（formatPeriod 对非季首月返回年份）。
    var isQuarterly;
    if(period === 'quarter') isQuarterly = true;
    else if(period === 'month' || period === 'day') isQuarterly = false;
    else isQuarterly = !!(releaseRule && releaseRule.indexOf('统计季度') !== -1
                          && releaseRule.indexOf('统计月') === -1);
    var period = dayFmt ? formatDay(params[0].axisValue) : formatPeriod(params[0].axisValue, isQuarterly);
    var s = '<div style="font-weight:600;margin-bottom:2px;">统计期：' + period + '</div>';
    params.forEach(function(p){
      if(p.seriesType === 'custom') return;   // 衰退区间标注不是数据序列，不进 tooltip
      if(p.value==null || p.value==='') return;   // 缺值不占一行（多频率共图时很常见）
      // 季频序列（如 ECI 落在月频横轴上）补注对应季度，避免把 7 月的季度值读成 7 月单月；
      // quarter_lag 用于"阶梯延续"的序列（g 落在日频横轴上，当期读到的是上一季的值）
      var meta = seriesMeta && seriesMeta[p.seriesIndex];
      var v;
      // 序列自带单位优先（一张卡里同时有十亿美元柱和百分比线时，全局 unit 不够用）
      var su = meta && meta.unit;
      if(su === '$bn'){
        var n0 = Number(p.value);
        var abs0 = Math.abs(n0);
        var txt = abs0 >= 1000 ? Math.round(abs0).toLocaleString('en-US') : String(Math.round(abs0));
        v = (n0 > 0 ? '+' : (n0 < 0 ? '−' : '')) + txt + ' bn';
      }else if(su === '%'){
        v = Number(p.value).toFixed(meta.digits == null ? 2 : meta.digits) + '%';
      }else if(su === 'bp'){
        // 利差类序列（如 SOFR−FFR）带符号，正负就是钱松钱紧的方向
        var n1 = Number(p.value);
        v = (n1 > 0 ? '+' : (n1 < 0 ? '−' : '')) + Math.abs(n1).toFixed(meta.digits == null ? 0 : meta.digits) + 'bp';
      }else if(unit === 'bp') v = fmtBp(p.value) + 'bp';   // 差值类图表带符号，便于分辨正负
      else v = Number(p.value).toFixed(2);
      var suffix = '';
      if(meta && meta.freq === 'quarter'){
        suffix = '（' + quarterLabel(params[0].axisValue, meta.quarter_lag) + '）';
      }else if(meta && meta.freq === 'month'){
        suffix = '（' + monthLabel(params[0].axisValue, meta.month_lag) + '）';
      }
      s += p.marker + p.seriesName + suffix + '：' + v + '<br/>';
    });
    // 附加明细（如净发行背后的"发行 X / 到期 Y"），让净额可追溯
    var ex = tipExtra && tipExtra[params[0].axisValue];
    if(ex){
      s += '<div style="margin-top:3px;font-size:11px;opacity:0.85;">' + ex + '</div>';
    }
    if(releaseRule){
      s += '<div style="margin-top:4px;font-size:11px;opacity:0.75;border-top:1px solid rgba(128,128,128,0.3);padding-top:3px;">' + releaseRule + '</div>';
    }
    return s;
  }

  // 构建 Y 轴配置：双轴（dual_axis）时左轴=series[yAxisIndex 0]，右轴=series[yAxisIndex 1]
  // 刻度标签按量级自动取舍小数位：大数值（GDP、美联储总资产）不带四位小数，
  // 否则 fitYAxis 写入的精确上下限会渲染成 "165,378.7" 这种长标签，被左侧 grid 边距裁掉。
  function fmtTick(v){
    var a = Math.abs(v);
    if(a >= 1000) return Math.round(v).toLocaleString('en-US');
    if(a >= 100)  return String(Math.round(v));
    if(a >= 10)   return String(Math.round(v * 10) / 10);
    return String(Math.round(v * 100) / 100);
  }

  function buildYAxis(data, big){
    var dual = data.dual_axis === true;
    var tickLabel = {color:THEME.text3, fontSize: big?11:10, formatter:fmtTick};
    var base = {
      type:'value',
      axisLine:{show:false}, axisTick:{show:false},
      axisLabel: Object.assign({}, tickLabel)
    };
    if(!dual){
      base.splitLine = {lineStyle:{color:THEME.splitline}};
      return base;
    }
    var left = Object.assign({}, base);
    left.position = 'left';
    left.splitLine = {lineStyle:{color:THEME.splitline}};
    left.axisLabel = Object.assign({}, tickLabel);
    var right = Object.assign({}, base);
    right.position = 'right';
    right.splitLine = {show:false};
    right.axisLabel = Object.assign({}, tickLabel);
    // 右轴是百分比口径（如净发行里的 coupon 占比）时补上 %，否则两条轴读数无从区分
    if(data.right_pct) right.axisLabel.formatter = function(v){ return fmtTick(v) + '%'; };
    return [left, right];
  }

  // 构建折线图 option（支持 dataZoom 拖动缩放；big 模式显示 slider 且字号更大）
  // zoomStartIndex: 默认缩放起始的数据点索引（如 2022 年对应的索引），未提供则显示全部
  function buildLineOption(data, big, zoomStartIndex){
    var hasBar = false;
    var series = data.series.map(function(s, i){
      var yi = s.yAxisIndex === 1 ? 1 : 0;
      // 柱状序列（净发行这类正负流量）：同 stack 的两根柱正负各自堆叠
      if(s.type === 'bar'){
        hasBar = true;
        return {
          name: s.name, type:'bar', data: s.values,
          stack: s.stack || null,
          barMaxWidth: big ? 22 : 15,
          itemStyle:{color:s.color},
          emphasis:{focus:'series'},
          yAxisIndex: yi
        };
      }
      var dashed = !!s.dashed;
      return {
        name: s.name, type:'line', data: s.values,
        smooth: dashed ? false : true,
        showSymbol: s.showSymbol === true,
        symbol: s.showSymbol === true ? 'circle' : 'none',
        symbolSize: big ? 7 : 5,
        connectNulls: s.connectNulls === true,
        // step:'end' 用于把季频值铺到日频横轴（g 的阶梯线）：值保持到下一季发布时才跳变
        step: s.step || false,
        lineStyle:{width: big?2.5:2, color:s.color, type: dashed ? 'dashed' : 'solid'},
        itemStyle:{color:s.color},
        // 单序列默认加淡色面积；零值上下反复穿越的序列（如期限溢价）用 no_area 关掉，
        // 否则面积会从 0 轴一路铺到负值区，把走势压扁。
        // 序列级 s.area 用于双轴图里想强调"风险量"的那条（如衰退概率）
        areaStyle: (s.area === true)
          ? {color:s.color, opacity:0.12}
          : ((i===0 && data.series.length===1 && data.no_area !== true) ? {color:s.color, opacity:0.15} : null),
        emphasis:{focus:'series'},
        yAxisIndex: yi
      };
    });
    var fs = big ? 13 : 11;   // 字号
    var n = data.dates.length;
    // 衰退区间标注：半透明竖柱贯穿绘图区。
    // 用 custom series 而非 markArea —— 类目轴 boundaryGap:false 时 markArea 只能覆盖到类目中心，
    // 首尾各差半格；custom 可以按 api.size 精确扩到季度边界，且随 dataZoom 自动重算像素。
    (data.bands || []).forEach(function(b, bi){
      var ranges = (b.ranges || []).map(function(r){
        var s = data.dates.indexOf(r[0]);
        if(s < 0) return null;
        var e = data.dates.indexOf(r[1]);
        return [s, e < 0 ? s : e];
      }).filter(function(x){ return x; });
      if(!ranges.length) return;
      series.push({
        // z 让先声明的（技术性衰退）压在后声明的之上，重叠时段偏红而非偏蓝，便于分辨"两定义同时命中"
        name: b.name, type:'custom', z: (data.bands.length - bi) * 0.5, silent:true, legendHoverLink:false,
        itemStyle:{color: b.color},
        data: ranges,
        renderItem: function(params, api){
          var cs = params.coordSys;
          if(!cs) return null;
          var half = api.size([1, 0])[0] / 2;   // 扩到季度格子边界，避免首尾各差半格
          var x0 = api.coord([api.value(0), 0])[0] - half;
          var x1 = api.coord([api.value(1), 0])[0] + half;
          var l = Math.max(cs.x, x0), r = Math.min(cs.x + cs.width, x1);
          if(!(r > l)) return null;             // 区间整体在可视窗口外
          return {
            type:'rect', silent:true,
            shape:{ x:l, y:cs.y, width:r - l, height:cs.height },
            style:{ fill: b.fill }
          };
        }
      });
    });
    // 用百分比设置默认缩放范围（比 startValue 更可靠，不依赖精确字符串匹配）
    var zoomCfg = {};
    if(zoomStartIndex != null && zoomStartIndex > 0 && zoomStartIndex < n){
      zoomCfg.start = Math.round(zoomStartIndex / n * 1000) / 10;   // 转百分比
      zoomCfg.end = 100;
    }
    var option = {
      backgroundColor:THEME.bg,
      // 带滑块的卡片需要多留底部空间，否则 x 轴标签会贴着滑块、滑块又紧贴画布下沿
      grid:{left: big?64:48, right: data.dual_axis ? (big?72:56) : 34, top: big?36:32,
            bottom: (big || data.show_slider === true) ? 66 : 44},
      tooltip:{trigger:'axis',
        backgroundColor:THEME.card, borderColor:THEME.line,
        textStyle:{color:THEME.text, fontSize:12},
        formatter:function(params){ return tooltipFormatter(params, data.release_rule, data.unit, data.day_format === true, data.period, data.series, data.tip_extra); }
      },
      // 双轴图的右轴刻度就画在图例正右侧，图例贴边会跟顶端刻度标签叠在一起
      legend:{top:0, right: data.dual_axis ? 56 : 0, textStyle:{color:THEME.text2, fontSize:fs}, itemWidth:14, itemHeight:8},
      xAxis:{type:'category', data:data.dates, boundaryGap:hasBar === true,
        axisLine:{lineStyle:{color:THEME.line}},
        axisLabel:{color:THEME.text3, fontSize: big?11:10,
          // 月频柱状图（净发行这类）标签只留到年月：262 个月的地毯图再带"-01"就成了一片数字
          formatter: data.xfmt === 'ym' ? function(v){ return String(v).slice(0,7); } : null},
        axisTick:{show:false}
      },
      yAxis: buildYAxis(data, big),
      // 拖拽/滚轮缩放：周期较长时自由拖动范围
      dataZoom:[
        Object.assign({ type:'inside', xAxisIndex:0, filterMode:'none', zoomOnMouseWheel:true, moveOnMouseMove:true }, zoomCfg),
        Object.assign({ type:'slider', xAxisIndex:0, show: big || data.show_slider === true, height: big?22:20, bottom: big?10:8,
          borderColor:THEME.line, backgroundColor:THEME.splitline,
          fillerColor:'rgba(139,92,246,0.15)',
          handleStyle:{color:THEME.purple}, moveHandleStyle:{color:THEME.purple},
          textStyle:{color:THEME.text3, fontSize:10},
          dataBackground:{lineStyle:{color:THEME.line}, areaStyle:{color:'rgba(139,92,246,0.06)'}} }, zoomCfg)
      ]
    };
    option.series = series;
    // 可选参考线（如利差/差值的 0 轴）：data.mark_line = 0
    // dual_axis 下参考线要挂在右轴序列上，否则会被当成左轴刻度（如 100 会画到 100 十亿美元）
    if(data.mark_line != null && series.length){
      var mi = data.mark_line_series != null && series[data.mark_line_series] ? data.mark_line_series : 0;
      series[mi].markLine = {
        silent: true, symbol: 'none', animation: false,
        data: [{yAxis: data.mark_line}],
        lineStyle: {color: THEME.text3, type: 'dashed', width: 1, opacity: 0.9},
        label: {show: false}
      };
    }
    // 正负分向的堆叠柱需要一条 0 基线，否则分不清哪根柱是"收缩"
    if(data.zero_line === true && series.length && !series[0].markLine){
      series[0].markLine = {
        silent: true, symbol: 'none', animation: false,
        data: [{yAxis: 0}],
        lineStyle: {color: THEME.text3, type: 'dashed', width: 1, opacity: 0.9},
        label: {show: false}
      };
    }
    return option;
  }

  // 把 y 轴量程贴到"整齐刻度"上：从 1/2/2.5/5 × 10^n 的阶梯里挑最细且刻度不超过 9 格的步长。
  // 只按 span/5 取步长会把量程撑到 1.5 倍（数据 −586~585 会被画成 −1000~1000，上下各空 40%）。
  function fitAxisRange(lo, hi){
    var span = hi - lo;
    if(!(span > 0)) span = Math.abs(hi) || 1;
    var base = Math.pow(10, Math.floor(Math.log(span / 6) / Math.LN10));
    var cands = [1, 2, 2.5, 5, 10, 20].map(function(m){ return m * base; });
    for(var i = 0; i < cands.length; i++){
      var st = cands[i];
      var mn = Math.floor(lo / st) * st;
      var mx = Math.ceil(hi / st) * st;
      if((mx - mn) / st <= 9) return { min: mn, max: mx };
    }
    var st2 = cands[cands.length - 1];
    return { min: Math.floor(lo / st2) * st2, max: Math.ceil(hi / st2) * st2 };
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

    function rangeFor(axisIndex, floorZero){
      var lo = Infinity, hi = -Infinity;
      // 堆叠柱要按索引把同 stack 的正/负分量分别累加，否则轴只按单根柱子拟合、柱子会顶出画布
      var posSum = {}, negSum = {};
      data.series.forEach(function(s){
        if((s.yAxisIndex === 1 ? 1 : 0) !== axisIndex) return;
        var stacked = (s.type === 'bar' && s.stack);
        for(var i=i0;i<i1;i++){
          var v = s.values[i];
          if(v==null || v==='' || isNaN(v)) continue;
          if(stacked){
            if(v >= 0) posSum[i] = (posSum[i] || 0) + v;
            else negSum[i] = (negSum[i] || 0) + v;
          }else{
            if(v < lo) lo = v;
            if(v > hi) hi = v;
          }
        }
      });
      Object.keys(posSum).forEach(function(k){ if(posSum[k] > hi) hi = posSum[k]; });
      Object.keys(negSum).forEach(function(k){ if(negSum[k] < lo) lo = negSum[k]; });
      if(lo === Infinity || hi === -Infinity) return null;
      var pad = (hi - lo) * 0.08;
      if(pad === 0) pad = Math.abs(hi) * 0.05 || 1;
      // 上下限对齐到"整洁刻度"，避免用 10378.0043 这种原值当轴端点：
      // 一是端点标签过长会被裁切，二是刻度值本身不好读
      var span = (hi + pad) - (lo - pad);
      var fit = fitAxisRange(lo - pad, hi + pad);
      var ymin = fit.min, ymax = fit.max;
      // 百分比轴从 0 起：全正时不留负刻度（占比不可能为负）
      if(floorZero && lo >= 0 && ymin < 0) ymin = 0;
      ymin = Math.round(ymin * 1000) / 1000;
      ymax = Math.round(ymax * 1000) / 1000;
      if(!(ymax > ymin)){ ymax = ymin + span; }
      return { min: ymin, max: ymax };
    }

    if(data.dual_axis){
      var left = rangeFor(0, data.floor_zero === true), right = rangeFor(1, data.right_pct === true);
      var axes = [{}, {}];
      if(left){ axes[0] = { min: left.min, max: left.max }; }
      if(right){ axes[1] = { min: right.min, max: right.max }; }
      chart.setOption({ yAxis: axes });
      return;
    }
    var r = rangeFor(0, data.floor_zero === true);
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

  // 点阵图（美联储 SEP）：x=年份、y=利率%，每个点 = 一位 FOMC 参与者
  // data = {kind:'dots', years:['2026 年',...], cur:[[x,y,同档人数],...], prev:[...],
  //         median_lines:[[[x1,y],[x2,y]],...], now:3.88, cur_label:'9 月', prev_label:'6 月'}
  window.renderDotPlot = function(el, data){
    if(!data || !data.years || !data.years.length) return;
    var years = data.years, n = years.length;
    var legendData = [];
    var series = [];
    var curSeries = {
      name:'本次 SEP（'+(data.cur_label||'')+'）', type:'scatter', data:data.cur,
      symbolSize:9.5, z:3,
      itemStyle:{color:'#8b5cf6', opacity:0.95},
      emphasis:{scale:1.25, itemStyle:{opacity:1}}
    };
    // 中位数横线（每年一段，官方点阵图的橙色横杠）
    var ml = [];
    (data.median_lines || []).forEach(function(seg){ ml.push([{coord:seg[0]}, {coord:seg[1]}]); });
    if(ml.length){
      curSeries.markLine = {
        silent:true, symbol:'none', animation:false, data:ml,
        lineStyle:{color:'#f5a623', width:2.4, type:'solid'}, label:{show:false}
      };
    }
    legendData.push(curSeries.name);
    series.push(curSeries);
    // 当前政策利率水平（EFFR）：一条横贯全图的虚线，读"点位比现在高还是低"
    if(data.now != null){
      series.push({
        name:'__now', type:'scatter', data:[], silent:true,
        markLine:{
          silent:true, symbol:'none', animation:false,
          data:[{yAxis:data.now, lineStyle:{color:THEME.text3, type:'dashed', width:1.2},
                 label:{show:true, position:'insideEndTop', color:THEME.text3, fontSize:10,
                        formatter:'当前 '+Number(data.now).toFixed(2)+'%'}}]
        }
      });
    }
    var option = {
      backgroundColor:THEME.bg,
      grid:{left:52, right:30, top:46, bottom:34},
      tooltip:{trigger:'item',
        backgroundColor:THEME.card, borderColor:THEME.line,
        textStyle:{color:THEME.text, fontSize:12},
        formatter:function(p){
          var v = p.value || [];
          if(p.seriesName === '__now') return '';
          var yi = Math.round(v[0]);
          return '<div style="font-weight:600;margin-bottom:2px;">'+ (years[yi]||'') +'</div>'+
                 p.marker + p.seriesName +'：'+ Number(v[1]).toFixed(2) +'%'+
                 (v[2] > 1 ? '<br/><span style="opacity:.7">该档位共 '+ v[2] +' 人</span>' : '')+
                 (v[3] != null ? '<br/><span style="opacity:.7">上一期同档 '+ v[3] +' 人</span>' : '');
        }
      },
      legend:{top:0, right:0, data:legendData, textStyle:{color:THEME.text2, fontSize:11},
        itemWidth:12, itemHeight:8, icon:'circle'},
      xAxis:{type:'value', min:-0.55, max:n-0.45, interval:1,
        axisLine:{lineStyle:{color:THEME.line}},
        axisTick:{show:false},
        splitLine:{show:false},
        axisLabel:{color:THEME.text2, fontSize:12,
          formatter:function(v){ return years[Math.round(v)] || ''; }}
      },
      yAxis:{type:'value', scale:true,
        min: data.ymin, max: data.ymax, interval: data.ystep || 0.25,
        axisLine:{show:false}, axisTick:{show:false},
        splitLine:{lineStyle:{color:THEME.splitline}},
        axisLabel:{color:THEME.text3, fontSize:11,
          formatter:function(v){ return Number(v).toFixed(2) + '%'; }}
      },
      series: series
    };
    var chart = echarts.init(el, null, {renderer:'canvas'});
    chart.setOption(option);
    chartInstances.push(chart);
    window.addEventListener('resize', function(){ chart.resize(); });
    return chart;
  };

  // ===== 瀑布图：变动归因（通用）=====
  // 口径：从"期初值 v0"出发，按 legs 顺序逐腿累加，结果恒等于"期末值 v1"，起点/终点做柱、中间腿做浮动柱。
  // 现有两张图共用：通胀页 BEI 归因、财政页 ACM 期限溢价变动归因。
  // data = {kind:'waterfall', unit:'bp', level_fmt:'bp'|'pct', default:'1m',
  //         start_name, end_name,
  //         legs:[{name}],                     // 归因腿，顺序即累加顺序
  //         windows:[{key,label,from,to,v0,v1,leg_vals:[..],leg_detail:["…"]}]}
  var wfCharts = {};

  function fmtBp(v){
    var n = Number(v);
    if(isNaN(n)) return '—';
    return (n > 0 ? '+' : (n < 0 ? '−' : '')) + Math.abs(n).toFixed(1);
  }
  function md(s){ return s ? String(s).slice(5).replace('-', '/') : ''; }

  function wfLevel(v, data){
    var n = Number(v);
    if(isNaN(n)) return '—';
    return data.level_fmt === 'pct' ? n.toFixed(2) + '%' : fmtBp(n) + 'bp';
  }

  function wfOption(w, data){
    var t = THEME;
    var legs = data.legs || [];
    var isPct = data.level_fmt === 'pct';
    // 端点用"水平值"单位（% 或 bp），归因腿一律用 bp；累计前先把腿换成端点单位
    var toLevel = function(v){ return isPct ? Number(v) / 100 : Number(v); };
    var vals = [Number(w.v0)].concat((w.leg_vals || []).map(toLevel));
        // 逐步累计：cum[0] 期初，cum[1..n-1] 中间腿，cum[n] 期末（应等于 v1）
    var cum = [vals[0]];
    for(var i = 1; i < vals.length; i++){ cum.push(cum[i-1] + vals[i]); }
    var last = cum.length - 1;

    var names  = [data.start_name || '期初'].concat(legs.map(function(l){ return l.name; }))
                 .concat([data.end_name || '期末']);
    var base = [], size = [], colors = [], texts = [];
    // 柱子数 = 期初 + 各腿 + 期末 = legs.length + 2；cum 只有 legs.length + 1 个累计值，
    // 所以终点柱要单独占一格（不能和最后一条腿同格）
    var nBars = names.length;
    for(var i = 0; i < nBars; i++){
      if(i === 0){
        base.push(Math.min(0, cum[0])); size.push(Math.abs(cum[0]));
        colors.push(t.text2); texts.push(wfLevel(cum[0], data));
      }else if(i === nBars - 1){
        base.push(Math.min(0, cum[last])); size.push(Math.abs(cum[last]));
        colors.push(t.purple); texts.push(wfLevel(cum[last], data));
      }else{
        var d = cum[i] - cum[i-1];
        base.push(Math.min(cum[i-1], cum[i])); size.push(Math.abs(d));
        colors.push(d >= 0 ? t.red : t.green);      // 推高为红、压低为绿（延续 BEI 归因口径）
        texts.push(fmtBp((w.leg_vals || [])[i-1]) + 'bp');   // 腿的贡献始终用 bp 显示
      }
    }

    // 上下留白：只按累计值定范围（不强行把 0 纳入），否则 5% 附近的水平值会把变动压扁。
    // bp 口径最小留 6bp；% 口径最小留 0.08pp，并把端点对齐到 1/2/5×10ⁿ 的整齐刻度，
    // 否则会出现 3.9 与 3.8 挤在一起这种刻度。
    var isPct = data.level_fmt === 'pct';
    var lo = Math.min.apply(null, cum), hi = Math.max.apply(null, cum);
    var pad = Math.max((hi - lo) * 0.45, isPct ? 0.08 : 6);
    var ymin, ymax;
    if(isPct){
      var raw = (hi - lo + pad * 2) / 5;
      var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
      var norm = raw / mag;
      var pstep = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
      ymin = Math.round(Math.floor((lo - pad) / pstep) * pstep * 100) / 100;
      ymax = Math.round(Math.ceil((hi + pad) / pstep) * pstep * 100) / 100;
    }else{
      ymin = Math.floor(lo - pad); ymax = Math.ceil(hi + pad);
    }

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
          if(i === 0)  return head + wfLevel(cum[0], data) + '<br/><span style="opacity:.7">' + w.from + '</span>';
          if(i === last) return head + wfLevel(cum[i], data) + '<br/><span style="opacity:.7">' + w.to + '</span>';
          var detail = (w.leg_detail || [])[i-1] || '';
          return head + detail + '<br/>贡献：' + fmtBp((w.leg_vals || [])[i-1]) + 'bp';
        }
      },
      xAxis: {
        type: 'category', data: names,
        axisLine: {lineStyle: {color: t.line}},
        axisTick: {show: false},
        axisLabel: {color: t.text3, fontSize: 11}
      },
      yAxis: {
        type: 'value', name: data.axis_name || 'bp', nameTextStyle: {color: t.text3, fontSize: 10},
        min: ymin, max: ymax,
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

    // 同步卡片里的动态口径行：起点 → 终点，以及各腿贡献
    var note = document.getElementById(el.id + '-note');
    if(note){
      var legs = data.legs || [];
      var legTxt = legs.map(function(l, i){
        return l.name + ' ' + fmtBp((w.leg_vals || [])[i]) + 'bp';
      }).join(' · ');
      note.innerHTML = '区间 ' + md(w.from) + ' → ' + md(w.to) + '：' +
        wfLevel(w.v0, data) + ' → ' + wfLevel(w.v1, data) +
        (legTxt ? '（其中 ' + legTxt + '）' : '');
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
