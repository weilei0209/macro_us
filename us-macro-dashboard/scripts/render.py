#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美国宏观数据看板 - 多页面静态站点渲染器（暗色金融终端风格）
读取 data/latest.json 与 data/series.json，生成 site/ 目录下的多页面站点：
  index.html        首页：全景速览 + KPI + 预警信号灯 + 关键趋势 + 月度节奏
  employment.html   主题页：就业
  inflation.html    主题页：通胀
  growth.html       主题页：增长
  fiscal.html       主题页：财政
  monetary.html     主题页：货币
  leading.html      主题页：领先指标
  topics.html       专题页：7 篇专题分析
  about.html        关于：方法论 + 数据口径速查
图表层用 ECharts（assets/echarts.min.js 本地引入），离线可看。
"""
import os, sys, json, datetime, html, shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
DATA_DIR = os.path.join(BASE_DIR, "data")
SITE_DIR = os.path.join(BASE_DIR, "site")
ASSETS_SRC = os.path.join(BASE_DIR, "assets")

from indicators import (FRED_META, TOPIC_RULES, RELEASE_CALENDAR, RELEASE_RULE,
                        FREQ_SHORT, INDICATOR_META)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def esc(s):
    return html.escape(str(s)) if s is not None else ""


def fmt_val(v, unit="", kind="num"):
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v:+.2f}%"
    # 带单位的数值：% / 指数等符号型单位紧贴数字，文字型单位（千人/十亿美元）前加空格
    if unit in ("%", "指数", "倍"):
        u = unit
    elif unit:
        u = " " + unit
    else:
        u = ""
    if abs(v) >= 1000:
        return f"{v:,.1f}{u}"
    if abs(v) >= 100:
        return f"{v:.1f}{u}"
    if abs(v) >= 1:
        return f"{v:.2f}{u}"
    return f"{v:.3f}{u}"


def fmt_date(d, freq=""):
    if not d:
        return ""
    # 季频数据：FRED 用 01-01/04-01/07-01/10-01 表示 Q1~Q4，显示为季度
    if freq == "quarterly":
        qmap = {"-01-01": "Q1", "-04-01": "Q2", "-07-01": "Q3", "-10-01": "Q4"}
        for suf, q in qmap.items():
            if d.endswith(suf):
                return d[:4] + q
        return d[:4]
    # 其余（日/周/月频）：统一显示为 YYYY/MM/DD（月度即 YYYY/MM/01，可读为统计月）
    return d.replace("-", "/")


def meta_note(ind, info=None):
    """生成指标卡的"数据说明"行：来源 · 单位 · 更新周期（发布规则）。
    ind 为内部指标名；info 为 latest.json 里该指标的元数据（可含 source/unit/freq）。"""
    info = info or {}
    im = INDICATOR_META.get(ind, {})
    source = info.get("source") or im.get("source", "")
    unit = info.get("unit") or im.get("unit", "")
    freq = info.get("freq", "")
    release = RELEASE_RULE.get(freq, "")
    # 来源 · 单位 · 发布规则 三段拼接（缺省项自动省略）
    parts = []
    if source:
        parts.append(f"来源 {source}")
    if unit:
        parts.append(f"单位 {unit}")
    if release:
        parts.append(release)
    if not parts:
        return ""
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# 分类 / 页面映射
# ---------------------------------------------------------------------------
CAT_ORDER = ["就业", "通胀", "通胀预期", "增长", "消费", "货币", "利率",
             "金融条件", "领先", "地产", "汇率", "其他"]
CAT_COLORS = {
    "就业": "#e5484d", "通胀": "#e5484d", "通胀预期": "#f5a623",
    "增长": "#3b82f6", "消费": "#3b82f6", "货币": "#8b5cf6",
    "利率": "#e5484d", "金融条件": "#a78bfa", "领先": "#f5a623",
    "地产": "#34d399", "汇率": "#8b5cf6", "其他": "#6b7280",
}
CAT_ICONS = {
    "就业": "💼", "通胀": "📈", "通胀预期": "🎯", "增长": "📊",
    "消费": "🛒", "货币": "🏦", "利率": "💹", "金融条件": "📉",
    "领先": "🔮", "地产": "🏠", "汇率": "💱", "其他": "📌",
}

# 主题页定义：页面文件名 -> (标题, 副标题, 包含的分类)
THEME_PAGES = [
    ("employment.html", "就业", "数据之王：非农 / 失业率 / JOLTS / 工资，判断经济冷暖的第一维度", ["就业"]),
    ("inflation.html", "通胀", "政策之锚：CPI / PCE / 通胀预期，美联储 2% 目标的全部口径", ["通胀", "通胀预期"]),
    ("growth.html", "增长", "国民账户：GDP / GDI / 消费 / 投资，产出缺口的剥洋葱四层", ["增长", "消费"]),
    ("fiscal.html", "财政", "债务可持续性：赤字 / 债务率 / r-g，化债路径与美债供给", ["增长"]),
    ("monetary.html", "货币", "货币政策：联邦基金 / SOFR / 资产负债表 / ON RRP，缩表与流动性", ["货币", "利率"]),
    ("leading.html", "领先指标", "领先与情绪：PMI / 地产 / 金融条件 / 汇率，周期位置与资产映射", ["领先", "地产", "金融条件", "汇率"]),
]

# 导航项（首页 + 主题页 + 专题 + 关于）
NAV_ITEMS = [
    ("index.html", "首页"),
    ("employment.html", "就业"),
    ("inflation.html", "通胀"),
    ("growth.html", "增长"),
    ("fiscal.html", "财政"),
    ("monetary.html", "货币"),
    ("leading.html", "领先"),
    ("topics.html", "专题"),
    ("about.html", "关于"),
]

# KPI 大卡
KPI_CARDS = [
    ("vu_ratio",      "V/U 比率",      "岗位空缺 / 失业人数",     "num", "", "var(--orange)"),
    ("payrolls_mom",  "非农新增",      "当月环比（千）",           "num", "千", "var(--red)"),
    ("payrolls_3mma", "非农 3MMA",     "3 个月移动平均",          "num", "千", "var(--red)"),
    ("cpi_yoy",       "CPI 同比",      "总通胀同比",               "pct", "", "var(--red)"),
    ("core_pce_yoy",  "核心 PCE 同比", "美联储最关注口径",          "pct", "", "var(--red)"),
    ("cpi_pce_gap",   "CPI-PCE 剪刀差","正常 +0.3~0.5pp",         "pct", "", "var(--purple)"),
    ("r_minus_g",     "r - g",         "增长化债空间",             "pct", "", "var(--green)"),
    ("output_gap",    "产出缺口",      "实际 / 潜在 GDP",          "pct", "", "var(--blue)"),
]


# ---------------------------------------------------------------------------
# 图表数据构造
# ---------------------------------------------------------------------------
# 小图默认展示的起始日期（放大图默认 2022 起，小图保留更长历史，2000 年后都有）
CHART_HISTORY_START = "2000-01-01"
# 单图数据点安全上限（防异常序列过大）
MAX_POINTS = 10000

def series_points(series, n=MAX_POINTS):
    # 优先按"2000 年以后"过滤，保证小图有完整长期走势；
    # 若 2000 后点数超过上限 n，则回退到最近 n 点（避免极端密集）
    pts = [p for p in series if p["value"] is not None]
    since = [p for p in pts if p["date"] >= CHART_HISTORY_START]
    if len(since) >= 24:
        pts = since
    if len(pts) > n:
        pts = pts[-n:]
    return {"dates": [p["date"] for p in pts], "values": [p["value"] for p in pts]}


def vu_series(series_data):
    jolts = series_data.get("jolts_open", [])
    unrate = series_data.get("unrate", [])
    lf = series_data.get("labor_force", [])
    jmap = {p["date"]: p["value"] for p in jolts if p["value"] is not None}
    umap = {p["date"]: p["value"] for p in unrate if p["value"] is not None}
    lmap = {p["date"]: p["value"] for p in lf if p["value"] is not None}
    dates = sorted(set(jmap) & set(umap) & set(lmap))
    vals = []
    for d in dates:
        unemployed = umap[d] / 100.0 * lmap[d]
        vals.append(jmap[d] / unemployed if unemployed > 0 else None)
    return {"dates": dates, "values": vals}


def yoy_series(series):
    # 保留 1999-01 起的数据用于计算同比基准，输出时仅展示 2000-01 起
    pts = [p for p in series if p["value"] is not None and p["date"] >= "1999-01-01"]
    pts.sort(key=lambda x: x["date"])
    idx = {p["date"]: i for i, p in enumerate(pts)}
    dates, vals = [], []
    for p in pts:
        i = idx[p["date"]]
        if i >= 12:
            base = pts[i - 12]["value"]
            if base and base != 0:
                if p["date"] >= CHART_HISTORY_START:
                    vals.append((p["value"] / base - 1) * 100)
                    dates.append(p["date"])
    return {"dates": dates, "values": vals}


def yoy_by_date(series):
    """基于日期对齐的同比（%）：对每个点找 12 个月前（含季频/月频均适用）的点算同比。
    季频数据（如 ECI，3 个月一点）用 12 个月前的点正好是去年同季。"""
    pts = [p for p in series if p["value"] is not None]
    pts.sort(key=lambda x: x["date"])
    pmap = {p["date"]: p["value"] for p in pts}
    dates = [p["date"] for p in pts]
    from datetime import date as _date
    out_dates, out_vals = [], []
    for d in dates:
        y, m = int(d[:4]), int(d[5:7])
        # 12 个月前的目标日期（月频对齐）
        ty = y - 1 if m > 1 else y - 2
        tm = m - 1 if m > 1 else 12
        # 找 <= 目标日期的最近点（季频时可能无精确匹配，取不超过的最近点）
        target = f"{ty:04d}-{tm:02d}-01"
        best = None
        for pd in dates:
            if pd <= target:
                best = pd
            else:
                break
        if best and best in pmap and pmap[best] != 0 and d >= CHART_HISTORY_START:
            out_dates.append(d)
            out_vals.append((pmap[d] / pmap[best] - 1) * 100)
    return {"dates": out_dates, "values": out_vals}


def freq_rule_for_chart(chart):
    """根据图表的数据源指标，返回其发布规则说明（无则返回空字符串）。"""
    sids = chart.get("series", [])
    if not sids:
        # 派生图表（V/U、CPI/PCE 同比），按其依赖的底层指标推断
        cid = chart["id"]
        if cid in ("chart_vu", "emp_vu", "td_vu"):
            sids = ["jolts_open"]  # 滞后最严重的那个决定"最新一期"的错位感
        elif cid in ("chart_infl_yoy", "inf_yoy", "td_yoy"):
            sids = ["cpi"]
    # 多序列且频率不一致时，标注混合频率说明
    freqs = []
    for sid in sids:
        f = RELEASE_CALENDAR.get(sid, ("", ""))[1]
        if f:
            freqs.append(f)
    uniq = sorted(set(freqs))
    if len(uniq) > 1:
        # 有日频/周频 + 月频/季频混合的情况，逐一说明
        parts = []
        for f in uniq:
            parts.append(RELEASE_RULE.get(f, f))
        return "；".join(parts)
    if uniq:
        return RELEASE_RULE.get(uniq[0], "")
    return ""


def payrolls_revision_chart(series_data):
    """非农新增 + 修订对比图表：实线=最新修订值（2000 至今全量），虚线=n-1/n-2 月调整前数据。
    实线从 series.json 的 payrolls 存量差分算全量；虚线读 data/payrolls_revisions.json。"""
    # 实线：从 payrolls 存量差分算非农新增（2000 至今）
    payrolls = series_data.get("payrolls", [])
    pts = [p for p in payrolls if p["value"] is not None and p["date"] >= "1999-01-01"]
    pts.sort(key=lambda x: x["date"])
    dates, latest = [], []
    for i in range(1, len(pts)):
        d = pts[i]["date"]
        if d >= CHART_HISTORY_START:
            dates.append(d)
            latest.append(round(pts[i]["value"] - pts[i-1]["value"], 1))

    series = [{"name": "非农新增（最新）", "values": latest, "color": "#e5484d"}]

    # 虚线：从 payrolls_revisions.json 取修订数据（仅最近 2-3 月显示）
    path = os.path.join(DATA_DIR, "payrolls_revisions.json")
    rev = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                rev = json.load(f)
        except Exception:
            rev = None

    def sparse(vals, ref_vals=None):
        """生成虚线序列：只对"确实发生过修订"的月份显示虚线点。
        判定：该月修订值存在、且与最新值不同（相差 >= 0.05）。"""
        out = [None] * len(dates)
        if not rev:
            return out
        # 建立 month -> 修订值 与 month -> 最新值 映射
        rm = dict(zip(rev.get("months", []), vals))
        lm = dict(zip(rev.get("months", []), rev.get("latest_mom", [])))
        n = len(dates)
        for i in range(n):
            m = dates[i][:7]
            if m not in rm or rm[m] is None:
                continue
            # 仅当修订值与最新值不同（发生过修订）时，才画虚线点
            if m in lm and lm[m] is not None and abs(rm[m] - lm[m]) < 0.05:
                continue
            out[i] = rm[m]
        return out

    if rev:
        initial = rev.get("initial_mom", [])
        rev1 = rev.get("rev1_mom", [])
        series.append({"name": "首次发布值（调整前）", "values": sparse(initial),
                       "color": "#f5a623", "dashed": True, "showSymbol": True})
        series.append({"name": "1 次修正后", "values": sparse(rev1),
                       "color": "#3b82f6", "dashed": True, "showSymbol": True})

    return {
        "dates": dates,
        "release_rule": "统计月数据 · 次月首周周五发布（虚线为历史发布时的初值/一次修正值）",
        "series": series,
    }


def mom_diff(series, start="1999-01-01"):
    """把存量序列转为月度环比新增（差分），返回 {"dates": [...], "values": [...]}。
    与 payrolls_revision_chart 里非农新增的差分口径一致：当月值 - 上月值。"""
    pts = [p for p in series if p["value"] is not None and p["date"] >= start]
    pts.sort(key=lambda x: x["date"])
    dates, vals = [], []
    for i in range(1, len(pts)):
        d = pts[i]["date"]
        if d >= CHART_HISTORY_START:
            dates.append(d)
            vals.append(round(pts[i]["value"] - pts[i-1]["value"], 1))
    return {"dates": dates, "values": vals}


def align_series(dates, series):
    """把序列值按给定 dates 对齐（缺值填 null），供多序列不同频率图表使用。"""
    m = {p["date"]: p["value"] for p in series if p["value"] is not None}
    return [m.get(d) for d in dates]


def goods_vs_payrolls_chart(series_data):
    """工业新增就业 vs 非农新增就业：双 Y 轴（左=非农新增，右=工业新增）。
    两个轴各自独立缩放，使均值视觉接近，突出周期波动的同步/领先关系。"""
    payrolls = mom_diff(series_data.get("payrolls", []))
    goods = mom_diff(series_data.get("goods_emp", []))
    # 以非农新增的日期为基准对齐工业新增（两者均月频，日期应一致）
    dates = payrolls["dates"]
    goods_aligned = align_series(dates, [{"date": d, "value": v} for d, v in zip(goods["dates"], goods["values"])])
    return {
        "dates": dates,
        "release_rule": "统计月数据 · 次月首周周五发布（左轴=非农新增，右轴=工业新增，双轴各自缩放）",
        "dual_axis": True,
        "series": [
            {"name": "非农新增（左轴）", "values": payrolls["values"], "color": "#e5484d", "yAxisIndex": 0},
            {"name": "工业新增（右轴）", "values": goods_aligned, "color": "#3b82f6", "yAxisIndex": 1},
        ],
    }


def build_chart(series_data, chart):
    cid = chart["id"]
    rule = freq_rule_for_chart(chart)
    # 非农新增 + 修订对比（实线最新值 + 虚线初值/1次修正）
    if cid == "emp_payrolls":
        return payrolls_revision_chart(series_data)
    if cid in ("chart_vu", "emp_vu", "td_vu"):
        d = vu_series(series_data)
        return {"dates": d["dates"], "release_rule": rule, "series": [{"name": "V/U 比率", "values": d["values"], "color": "#e5484d"}]}
    if cid in ("chart_infl_yoy", "inf_yoy", "td_yoy"):
        cpi = yoy_series(series_data.get("cpi", []))
        pce = yoy_series(series_data.get("pcepi", []))
        return {"dates": cpi["dates"], "release_rule": rule, "series": [
            {"name": "CPI 同比", "values": cpi["values"], "color": "#e5484d"},
            {"name": "PCE 同比", "values": pce["values"], "color": "#3b82f6"},
        ]}
    # ---- 就业页新增图表 ----
    if cid == "emp_diffusion":
        d = series_points(series_data.get("emp_diffusion", []))
        return {"dates": d["dates"], "release_rule": "统计月数据 · 次月首周周五发布",
                "series": [{"name": "就业扩散指数", "values": d["values"], "color": "#f5a623"}]}
    if cid == "emp_cyclical":
        # 工业新增就业 vs 非农新增就业：双 Y 轴（左=非农新增，右=工业新增），
        # 各自独立量程缩放，使两个指标的均值视觉接近，便于比较周期性。
        return goods_vs_payrolls_chart(series_data)
    if cid == "emp_hours":
        # 周工时：制造业 vs 私营部门（领先指标）
        man = series_data.get("awhman", [])
        priv = series_data.get("awhaetp", [])
        dm = series_points(man)
        dates = dm["dates"]
        priv_aligned = align_series(dates, priv)
        return {"dates": dates, "release_rule": "统计月数据 · 次月首周周五发布", "series": [
            {"name": "制造业周工时", "values": dm["values"], "color": "#e5484d"},
            {"name": "私营部门周工时", "values": priv_aligned, "color": "#3b82f6"},
        ]}
    if cid == "emp_prime":
        d = series_points(series_data.get("prime_participation", []))
        return {"dates": d["dates"], "release_rule": "统计月数据 · 次月首周周五发布",
                "series": [{"name": "黄金年龄劳动参与率（25-54）", "values": d["values"], "color": "#34d399"}]}
    if cid == "emp_wages":
        # 工资：AHE 同比（月频）vs ECI 同比（季频），统一转同比对比
        ahe_yoy = yoy_by_date(series_data.get("ahe", []))
        eci_yoy = yoy_by_date(series_data.get("eci_wages", []))
        dates = ahe_yoy["dates"]
        eci_aligned = align_series(dates, [{"date": d, "value": v} for d, v in zip(eci_yoy["dates"], eci_yoy["values"])])
        return {"dates": dates, "release_rule": "AHE 统计月数据 · ECI 统计季度数据 · 同比增速对比", "series": [
            {"name": "平均时薪 AHE 同比", "values": ahe_yoy["values"], "color": "#e5484d"},
            {"name": "雇佣成本指数 ECI 同比", "values": eci_aligned, "color": "#8b5cf6"},
        ]}
    names = {"us10y": "10Y", "us2y": "2Y", "tips10y": "r(实际利率)", "gdp_qoq": "g(实际增速)",
             "fwd5y5y": "5y5y", "on_rrp": "ON RRP", "bei10y": "BEI 10Y", "unrate": "失业率",
             "payrolls": "非农存量", "claims": "首申", "cpi": "CPI", "pcepi": "PCE",
             "ffr": "联邦基金", "sofr": "SOFR", "fed_assets": "美联储总资产",
             "vix": "VIX", "hy_spread": "高收益利差", "gdp_real": "实际GDP",
             "sahm_rule": "萨姆规则"}
    multi_colors = {
        "tips10y": "#8b5cf6", "gdp_qoq": "#34d399",
        "us10y": "#e5484d", "us2y": "#3b82f6",
        "cpi": "#e5484d", "pcepi": "#3b82f6",
        "ffr": "#8b5cf6", "sofr": "#34d399",
    }
    d = series_points(series_data.get(chart["series"][0], []))
    series_list = []
    for sid in chart["series"]:
        sd = series_points(series_data.get(sid, []))
        color = multi_colors.get(sid, chart["color"]) if len(chart["series"]) > 1 else chart["color"]
        series_list.append({"name": names.get(sid, sid), "values": sd["values"], "color": color})
    return {"dates": d["dates"], "release_rule": rule, "series": series_list}


# 各页图表定义
HOME_CHARTS = [
    {"id": "chart_inflation", "title": "通胀锚定：5y5y 远期通胀补偿", "sub": "长端通胀预期对短期通胀的敏感性，最严格的锚定指标", "series": ["fwd5y5y"], "color": "#f5a623"},
    {"id": "chart_vu", "title": "就业健康度：V/U 比率", "sub": "岗位空缺 / 失业人数（领先工资通胀 2 季度）", "series": [], "color": "#e5484d"},
    {"id": "chart_rg", "title": "增长化债空间：r 与 g", "sub": "实际利率 vs 实际增速，r<g 可自然化债", "series": ["tips10y", "gdp_qoq"], "color": "#3b82f6"},
    {"id": "chart_infl_yoy", "title": "通胀口径：CPI vs PCE 同比", "sub": "CPI（拉氏）vs PCE（链式），剪刀差为口径差异", "series": [], "color": "#e5484d"},
    {"id": "chart_curve", "title": "收益率曲线：10Y vs 2Y", "sub": "期限利差，倒挂常预示衰退", "series": ["us10y", "us2y"], "color": "#8b5cf6"},
    {"id": "chart_rrp", "title": "流动性：ON RRP 余额", "sub": "缩表终点信号，归零则提示钱荒风险", "series": ["on_rrp"], "color": "#34d399"},
]

THEME_CHARTS = {
    "employment": [
        {"id": "emp_payrolls", "title": "非农新增（含历史修订）", "sub": "实线=最新修订值；虚线=首次发布值与 1 次修正值（非农发布后回溯修正前 2 个月）", "series": ["payrolls"], "color": "#e5484d"},
        {"id": "emp_vu", "title": "V/U 比率", "sub": "岗位空缺 / 失业人数", "series": [], "color": "#e5484d"},
        {"id": "emp_unrate", "title": "失业率 U3", "sub": "家庭调查（CPS）口径", "series": ["unrate"], "color": "#f5a623"},
        {"id": "emp_claims", "title": "首申失业金", "sub": "唯一周度就业指标，领先失业率", "series": ["claims"], "color": "#3b82f6"},
    ],
    "inflation": [
        {"id": "inf_yoy", "title": "CPI vs PCE 同比", "sub": "两套口径的差异，美联储盯 PCE", "series": [], "color": "#e5484d"},
        {"id": "inf_5y5y", "title": "5y5y 远期通胀补偿", "sub": "最严格的锚定指标", "series": ["fwd5y5y"], "color": "#f5a623"},
        {"id": "inf_bei", "title": "10Y 盈亏平衡通胀率", "sub": "市场定价的通胀预期", "series": ["bei10y"], "color": "#8b5cf6"},
    ],
    "growth": [
        {"id": "gro_gdp", "title": "实际 GDP", "sub": "季频，环比折年看边际", "series": ["gdp_real"], "color": "#3b82f6"},
        {"id": "gro_qoq", "title": "GDP 环比折年", "sub": "增长动能", "series": ["gdp_qoq"], "color": "#e5484d"},
        {"id": "gro_rg", "title": "r vs g", "sub": "增长化债空间", "series": ["tips10y", "gdp_qoq"], "color": "#3b82f6"},
    ],
    "fiscal": [
        {"id": "fis_rg", "title": "r - g 化债空间", "sub": "实际利率 vs 实际增速", "series": ["tips10y", "gdp_qoq"], "color": "#3b82f6"},
        {"id": "fis_debt", "title": "10Y 美债收益率", "sub": "供给冲击 → 期限溢价", "series": ["us10y"], "color": "#e5484d"},
    ],
    "monetary": [
        {"id": "mon_ffr", "title": "联邦基金 vs SOFR", "sub": "政策利率走廊", "series": ["ffr", "sofr"], "color": "#8b5cf6"},
        {"id": "mon_rrp", "title": "ON RRP 余额", "sub": "缩表终点信号", "series": ["on_rrp"], "color": "#34d399"},
        {"id": "mon_assets", "title": "美联储总资产", "sub": "资产负债表规模", "series": ["fed_assets"], "color": "#f5a623"},
    ],
    "leading": [
        {"id": "lea_curve", "title": "收益率曲线：10Y vs 2Y", "sub": "期限利差，倒挂预示衰退", "series": ["us10y", "us2y"], "color": "#8b5cf6"},
        {"id": "lea_vix", "title": "VIX 恐慌指数", "sub": "市场情绪", "series": ["vix"], "color": "#f5a623"},
        {"id": "lea_hy", "title": "高收益债信用利差", "sub": "信用风险", "series": ["hy_spread"], "color": "#e5484d"},
    ],
}

# 各主题页的口径提示（方法论固化）
THEME_TIPS = {
    "employment": [
        ("CES vs CPS 两套调查", "非农（CES 企业调查，统计岗位，12 万家企业/63 万工作地点）与失业率（CPS 家庭调查，统计人数，6 万户）口径不同。看新增读 CES，看结构读 CPS。"),
        ("盈亏平衡就业增速", "非农新增要读三层：对比一致预期 → 3 个月移动平均 → 对比盈亏平衡就业增速（2023-24 年 16-23 万，2025 年降至小几万）。"),
        ("V/U 比率领先工资", "岗位空缺 / 失业人数，领先工资通胀约 2 季度。低招聘 + 低解雇的'冻僵'状态是当前关注点。"),
    ],
    "inflation": [
        ("CPI '6211' 结构", "6 核心服务 / 2 核心商品 / 1 食品 / 1 能源。住房权重 36% 且统计滞后。"),
        ("超级核心服务", "鲍威尔三分类里，剔除住房的核心服务是美联储最警惕的分项。"),
        ("CPI vs PCE 四重差异", "医疗权重 8% vs 17%、住房 36% vs 15%、拉氏 vs 链式、权重来源不同——解释了美联储盯 PCE、市场盯 CPI 的分歧。"),
        ("锚定观测", "最严格地衡量通胀预期是否锚定，看 5y5y 远期通胀补偿，而非绝对通胀水平。"),
    ],
    "growth": [
        ("GDP '411' 结构", "4 消费 / 1 投资 / 1 政府。看趋势看消费，看边际看投资。"),
        ("剥洋葱四层", "GDP → Final Sales → 国内购买者最终销售 → PDFP。PDFP 才是'核心 GDP'。"),
        ("NBER vs 技术性衰退", "连续两季负增长是'技术性衰退'；NBER 用一揽子（就业/消费/工业生产）判定。20% 以上的美股深度回撤几乎全发生在 NBER 衰退期。"),
    ],
    "fiscal": [
        ("债务率看路径", "债务可持续性看债务率路径是否收敛，而非绝对水平。"),
        ("三种化债路径", "增长化债（r<g）/ 通胀化债 / 违约重组。当前 r-g 缺口决定空间。"),
        ("美债供给 → 期限溢价", "净发行量上升 → 期限溢价抬升 → 长端收益率承压。"),
    ],
    "monetary": [
        ("SOFR 是事实政策利率", "联邦基金利率是目标，SOFR 才是事实成交利率。两者利差反映准备金充裕度。"),
        ("缩表终点信号", "ON RRP 余额归零 + 银行间开始拆借 = 缩表接近终点，SOFR 可能突破走廊上限。"),
        ("长期中性利率", "点阵图长期中性利率是否上移（当前约 3.1%），决定利率路径锚。"),
    ],
    "leading": [
        ("ISM 制造业 PMI", "全球大类资产的共同因子，月初发布，领先经济拐点。"),
        ("韩国出口是金丝雀", "半导体出口领先全球 PMI 约 1-2 个月。"),
        ("金融条件五渠道", "利率、汇率、信用利差、股市、地产——货币政策通过金融条件传导至实体。"),
    ],
}


# ---------------------------------------------------------------------------
# 就业页专属：按 CES / CPS / 其他 三大调查体系分块（用分割线分隔）
# ---------------------------------------------------------------------------
EMPLOYMENT_SECTIONS = [
    {
        "icon": "🏭", "title": "一、CES 企业调查（岗位口径）",
        "desc": "12 万家企业/63 万工作地点，产出非农新增、行业就业、周工时、工资。看新增读 CES。",
        "charts": [
            {"id": "emp_payrolls", "title": "非农新增（含历史修订）", "sub": "实线=最新修订值；虚线=首次发布值与 1 次修正值（非农发布后回溯修正前 2 个月）", "series": ["payrolls"], "color": "#e5484d"},
            {"id": "emp_diffusion", "title": "就业扩散指数", "sub": "11 个主要行业环比上升占比，参考 PMI 构造（3MMA），衡量就业改善的广度", "series": ["emp_diffusion"], "color": "#f5a623"},
            {"id": "emp_cyclical", "title": "工业新增就业 vs 非农新增", "sub": "工业部门（制造+建筑+采矿）新增就业 vs 总非农新增，双轴对比周期性", "series": ["goods_emp", "payrolls"], "color": "#e5484d"},
            {"id": "emp_hours", "title": "周工时（领先指标）", "sub": "制造业 vs 私营部门平均周工时，领先失业率与衰退", "series": ["awhman", "awhaetp"], "color": "#e5484d"},
        ],
    },
    {
        "icon": "👥", "title": "二、CPS 家庭调查（人数口径）",
        "desc": "6 万户家庭，产出失业率、劳动参与率。看结构与失业读 CPS。",
        "charts": [
            {"id": "emp_unrate", "title": "失业率 U3", "sub": "家庭调查（CPS）口径", "series": ["unrate"], "color": "#f5a623"},
            {"id": "emp_prime", "title": "黄金年龄劳动参与率（25-54）", "sub": "剔除年龄结构噪音，才有周期含义", "series": ["prime_participation"], "color": "#34d399"},
        ],
    },
    {
        "icon": "💵", "title": "三、其他：匹配效率与工资",
        "desc": "JOLTS / 首申衡量劳动力市场匹配与流动，AHE / ECI 衡量工资通胀。",
        "charts": [
            {"id": "emp_vu", "title": "V/U 比率", "sub": "岗位空缺 / 失业人数，领先工资通胀约 2 季度", "series": [], "color": "#e5484d"},
            {"id": "emp_claims", "title": "首申失业金", "sub": "唯一周度就业指标，领先失业率", "series": ["claims"], "color": "#3b82f6"},
            {"id": "emp_wages", "title": "工资增速：AHE vs ECI", "sub": "平均时薪（构成偏差）vs 雇佣成本指数（固定权重、美联储首选），同比对比", "series": ["ahe", "eci_wages"], "color": "#e5484d"},
        ],
    },
]


# 专题独立页的图表定义（topic_id -> 图表列表）
TOPIC_DETAIL_CHARTS = {
    "inflation_anchor": [
        {"id": "td_fwd5y5y", "title": "5y5y 远期通胀补偿", "sub": "最严格的锚定指标，偏离近1年均值超 50bp 视为动摇", "series": ["fwd5y5y"], "color": "#f5a623"},
        {"id": "td_bei", "title": "10Y 盈亏平衡通胀率", "sub": "市场定价的通胀预期", "series": ["bei10y"], "color": "#8b5cf6"},
    ],
    "labor_freeze": [
        {"id": "td_vu", "title": "V/U 比率", "sub": "岗位空缺 / 失业人数，领先工资通胀约 2 季度", "series": [], "color": "#e5484d"},
        {"id": "td_claims", "title": "首申失业金", "sub": "唯一周度就业指标", "series": ["claims"], "color": "#3b82f6"},
        {"id": "td_unrate", "title": "失业率 U3", "sub": "家庭调查口径", "series": ["unrate"], "color": "#f5a623"},
    ],
    "beveridge": [],  # 贝弗里奇用独立 Canvas 页，不走 ECharts
    "qt_end": [
        {"id": "td_rrp", "title": "ON RRP 余额", "sub": "缩表终点信号，归零提示钱荒", "series": ["on_rrp"], "color": "#34d399"},
        {"id": "td_ffr", "title": "联邦基金 vs SOFR", "sub": "政策利率走廊，利差反映准备金充裕度", "series": ["ffr", "sofr"], "color": "#8b5cf6"},
    ],
    "technical_recession": [
        {"id": "td_qoq", "title": "GDP 环比折年", "sub": "连续两季负增长 = 技术性衰退", "series": ["gdp_qoq"], "color": "#e5484d"},
        {"id": "td_gdp", "title": "实际 GDP", "sub": "季频存量", "series": ["gdp_real"], "color": "#3b82f6"},
    ],
    "r_minus_g": [
        {"id": "td_rg", "title": "r 与 g", "sub": "实际利率 vs 实际增速", "series": ["tips10y", "gdp_qoq"], "color": "#3b82f6"},
        {"id": "td_tips", "title": "10Y TIPS 实际利率", "sub": "r 的代理", "series": ["tips10y"], "color": "#8b5cf6"},
    ],
    "cpi_pce_inversion": [
        {"id": "td_yoy", "title": "CPI vs PCE 同比", "sub": "剪刀差为口径差异", "series": [], "color": "#e5484d"},
    ],
    "sahm_rule": [
        {"id": "td_sahm", "title": "萨姆规则（Sahm Rule）", "sub": "失业率 3MMA 高出 12 个月最低 3MMA，≥0.5pp 触发衰退预警", "series": ["sahm_rule"], "color": "#e5484d"},
        {"id": "td_sahm_unrate", "title": "失业率 U3", "sub": "萨姆规则的底层输入，家庭调查口径", "series": ["unrate"], "color": "#3b82f6"},
    ],
}


# ---------------------------------------------------------------------------
# HTML 骨架模板
# ---------------------------------------------------------------------------
def page_head(title, active, updated):
    nav_links = []
    for fn, name in NAV_ITEMS:
        cls = ' class="active"' if fn == active else ""
        nav_links.append(f'<a href="{fn}"{cls}>{name}</a>')
    return f'''<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · 美国宏观数据看板</title>
<link rel="icon" type="image/png" sizes="256x256" href="assets/koala-us-macro.png">
<link rel="icon" type="image/x-icon" href="assets/favicon.ico">
<link rel="apple-touch-icon" href="assets/koala-us-macro-180.png">
<link rel="stylesheet" href="assets/style.css">
<script src="assets/echarts.min.js"></script>
<script src="assets/charts.js"></script>
</head><body>
<div class="nav"><div class="nav-inner">
  <a href="index.html" class="logo"><span class="logo-dot"></span><h1>美国宏观数据看板</h1></a>
  <div class="links">{''.join(nav_links)}</div>
  <div class="spacer"></div>
  <div class="update">上次更新<br><b>{esc(updated)}</b></div>
  <button class="theme-toggle" aria-label="切换主题" title="切换明暗主题">🌙</button>
</div></div>
<div class="wrap">
'''


def page_foot():
    return '''</div>
<div class="footer">
  美国宏观数据看板 · 数据来源 FRED / BLS / BEA / Census · 自动更新<br>
  基于「美国宏观数据训练营（829/830）」方法论构建 · 仅供研究参考，不构成投资建议
</div>
<div id="chart-modal" class="chart-modal">
  <div class="modal-backdrop"></div>
  <div class="modal-panel">
    <div class="modal-head">
      <div class="modal-title-wrap">
        <div id="modal-title" class="modal-title"></div>
        <div id="modal-sub" class="modal-sub"></div>
      </div>
      <button class="modal-close" title="关闭（Esc）">✕</button>
    </div>
    <div class="modal-hint">🖱️ 滚轮缩放 · 拖动底部滑块选择时间范围 · 拖动图表平移 · Esc 关闭</div>
    <div id="modal-chart" class="modal-chart"></div>
  </div>
</div>
</body></html>
'''


def section_head(icon, title, count=None, more=None):
    c = f'<span class="count">{count}</span>' if count is not None else ""
    m = f'<a class="more" href="topics.html">{esc(more)}</a>' if more else ""
    return (f'<div class="section-head"><span class="icon">{icon}</span><h3>{esc(title)}</h3>'
            f'<span class="line"></span>{c}{m}</div>')


def metric_cards(groups, series_data, cats):
    parts = ['<div class="metric-grid">']
    for cat in cats:
        if cat not in groups:
            continue
        for ind, info in sorted(groups[cat], key=lambda x: x[0]):
            val = info["value"]
            unit = info.get("unit", "")
            cls = ""
            if ind in ("cpi", "cpi_core", "pcepi", "pce_core"):
                cls = "up" if val is not None and val >= 2.0 else "down"
            elif ind in ("t10y2y", "t10y3m", "r_minus_g"):
                cls = "down" if val is not None and val < 0 else "up"
            elif ind == "cpi_pce_gap":
                cls = "up" if val is not None and val >= 0 else "down"
            spark_pts = [p["value"] for p in series_data.get(ind, []) if p["value"] is not None][-40:]
            spark_json = json.dumps(spark_pts)
            # 数据说明：来源 · 单位 · 更新周期（发布规则）
            note = meta_note(ind, info)
            note_html = f'<div class="m-release">{esc(note)}</div>' if note else ''
            parts.append(
                f'<div class="metric"><div class="m-label"><span>{esc(info["label"])}</span>'
                f'<span class="freq">{esc(FREQ_SHORT.get(info.get("freq", ""), info.get("freq", "")))}</span></div>'
                f'<div class="m-value {cls}">{fmt_val(val, unit)}</div>'
                f'<div class="m-date">{esc(fmt_date(info["date"], info.get("freq", "")))}</div>'
                f'{note_html}'
                f'<div class="m-spark" data-spark=\'{spark_json}\'></div></div>'
            )
    parts.append('</div>')
    return "".join(parts)


def charts_html(chart_defs, series_data, data_map=None):
    """渲染一组图表卡片的 HTML。若传入 data_map（dict），则把图表数据累积进去，
    由调用方最后统一用 charts_script(data_map) 输出渲染脚本（避免多次定义 window.__CHARTS 互相覆盖）。"""
    boxes = []
    for c in chart_defs:
        note = chart_meta(c)
        note_html = f'<div class="c-meta">{esc(note)}</div>' if note else ''
        boxes.append(
            f'<div class="chart-card"><div class="c-title">{esc(c["title"])}'
            f'<span class="c-zoom" title="点击放大">⤢</span></div>'
            f'<div class="c-sub">{esc(c["sub"])}</div>'
            f'{note_html}'
            f'<div class="chart-box" id="{c["id"]}"></div></div>'
        )
        if data_map is not None:
            data_map[c["id"]] = build_chart(series_data, c)
    return '<div class="chart-grid">' + "".join(boxes) + '</div>'


def charts_script(data_map):
    """输出 window.__CHARTS 数据 + 渲染脚本（页面级统一调用一次）。"""
    js = (
        '<script>\n'
        'window.__CHARTS = ' + json.dumps(data_map, ensure_ascii=False) + ';\n'
        'document.addEventListener("DOMContentLoaded", function(){\n'
        '  Object.keys(window.__CHARTS).forEach(function(id){\n'
        '    var el = document.getElementById(id);\n'
        '    if(el) window.renderLineChart(el, window.__CHARTS[id]);\n'
        '  });\n'
        '});\n'
        '</script>\n'
    )
    return js


def chart_meta(chart):
    """生成图表的"数据说明"行：来源 · 单位 · 更新周期。
    普通图表取 series 指标的元数据；派生图表（series 为空）用内置口径说明。"""
    sids = chart.get("series", [])
    # 派生图表的固定口径说明
    derived_note = {
        "chart_vu": "来源 BLS（JOLTS + CPS） · 单位 倍 · 岗位空缺 ÷ 失业人数",
        "emp_vu": "来源 BLS（JOLTS + CPS） · 单位 倍 · 岗位空缺 ÷ 失业人数",
        "td_vu": "来源 BLS（JOLTS + CPS） · 单位 倍 · 岗位空缺 ÷ 失业人数",
        "chart_infl_yoy": "来源 BLS / BEA · 单位 % · CPI 与 PCE 同比对比",
        "inf_yoy": "来源 BLS / BEA · 单位 % · CPI 与 PCE 同比对比",
        "td_yoy": "来源 BLS / BEA · 单位 % · CPI 与 PCE 同比对比",
        # 就业页新增
        "emp_diffusion": "来源 BLS · 单位 % · 11 个主要行业环比上升占比（参考 PMI 扩散指数构造，3MMA）",
        "emp_cyclical": "来源 BLS · 单位 千人（月度新增） · 工业新增=制造+建筑+采矿环比增量，双轴对比非农新增的周期性",
        "emp_hours": "来源 BLS · 单位 小时 · 周工时领先失业率与衰退（制造 vs 私营）",
        "emp_prime": "来源 BLS（CPS） · 单位 % · 黄金年龄 25-54 岁劳动参与率，剔年龄结构噪音",
        "emp_wages": "来源 BLS · 单位 % · AHE（构成偏差）vs ECI（固定权重、美联储首选），同比对比",
    }
    cid = chart["id"]
    if cid in derived_note:
        return derived_note[cid]
    if not sids:
        return ""
    # 单序列或双序列：取各指标来源/单位，来源去重合并
    sources, units = [], []
    for sid in sids:
        im = INDICATOR_META.get(sid, {})
        s = im.get("source", "")
        u = im.get("unit", "")
        if s and s not in sources:
            sources.append(s)
        if u and u not in units:
            units.append(u)
    rule = freq_rule_for_chart(chart)
    parts = []
    if sources:
        parts.append("来源 " + " / ".join(sources))
    if units:
        parts.append("单位 " + " / ".join(units))
    if rule:
        parts.append(rule)
    return " · ".join(parts)


def kpi_html(derived):
    # 派生指标 -> 代表性底层指标（用于推断发布规则）
    kpi_base = {
        "vu_ratio": "jolts_open", "payrolls_mom": "payrolls", "payrolls_3mma": "payrolls",
        "cpi_yoy": "cpi", "core_pce_yoy": "pce_core", "cpi_pce_gap": "pcepi",
        "r_minus_g": "gdp_qoq", "output_gap": "gdp_real",
    }
    parts = ['<div class="kpi-grid">']
    for key, title, sub, kind, unit, accent in KPI_CARDS:
        if key not in derived:
            continue
        v = derived[key]
        val = v["value"]
        cls = kpi_color(key, val)
        freq = RELEASE_CALENDAR.get(kpi_base.get(key, ""), ("", ""))[1]
        release_note = RELEASE_RULE.get(freq, "") if freq else ""
        release_html = f'<div class="m-release">{esc(release_note)}</div>' if release_note else ''
        parts.append(
            f'<div class="kpi"><span class="k-accent" style="background:{accent}"></span>'
            f'<div class="k-label">{esc(title)}</div>'
            f'<div class="k-value {cls}">{fmt_val(val, unit, kind)}</div>'
            f'<div class="k-note">{esc(sub)}</div>'
            f'<div class="k-date">{esc(fmt_date(v["date"], freq))}</div>'
            f'{release_html}</div>'
        )
    parts.append('</div>')
    return "".join(parts)


def kpi_color(key, val):
    if val is None:
        return "neutral"
    if key in ("cpi_yoy", "core_pce_yoy"):
        return "up" if val >= 2.0 else "down"
    if key == "cpi_pce_gap":
        return "up" if val >= 0 else "down"
    if key == "r_minus_g":
        return "down" if val < 0 else "up"
    if key == "output_gap":
        return "up" if val > 0 else "down"
    return "neutral"


def signals_html(reports):
    parts = ['<div class="signal-grid">']
    for r in reports:
        triggered = r.get("triggered")
        sev = r.get("severity", "normal")
        if triggered:
            light = "red"
        elif sev == "info":
            light = "gray"
        else:
            light = "green"
        desc = r.get("analysis", "")
        if len(desc) > 40:
            desc = desc[:40] + "…"
        href = f"topics/{r['id']}.html"
        parts.append(
            f'<a class="signal" href="{href}"><span class="light {light}"></span>'
            f'<div class="s-body"><div class="s-title">{esc(r["title"])}</div>'
            f'<div class="s-desc">{esc(desc)}</div></div></a>'
        )
    parts.append('</div>')
    return "".join(parts)


def topics_html(reports):
    parts = ['<div class="topic-grid">']
    for r in reports:
        sev = r.get("severity", "normal")
        triggered = r.get("triggered")
        badge_cls = "warn" if triggered else ("info" if sev == "info" else "ok")
        badge_txt = "⚠ 预警" if triggered else ("观察" if sev == "info" else "正常")
        data_html = ""
        if r.get("data"):
            items = []
            for k, v in r["data"].items():
                if isinstance(v, float):
                    v = f"{v:.2f}"
                items.append(f"{esc(k)}={esc(v)}")
            data_html = f'<div class="t-data">{" · ".join(items)}</div>'
        href = f"topics/{r['id']}.html"
        parts.append(
            f'<a class="topic {sev}" href="{href}"><div class="t-head">'
            f'<div class="t-title">{esc(r["title"])}</div>'
            f'<span class="t-badge {badge_cls}">{badge_txt}</span></div>'
            f'{data_html}'
            f'<div class="t-analysis">{esc(r.get("analysis",""))}</div>'
            f'<div class="t-framework">📌 {esc(r.get("framework",""))}</div>'
            f'<div class="t-watch">{esc(r.get("watch",""))}</div>'
            f'<div class="t-more">查看完整分析 →</div></a>'
        )
    parts.append('</div>')
    return "".join(parts)


def tips_html(tips):
    parts = []
    for title, body in tips:
        parts.append(
            f'<div class="tip"><div class="tip-title">💡 {esc(title)}</div>'
            f'<div class="tip-body">{esc(body)}</div></div>'
        )
    return "".join(parts)


# ---------------------------------------------------------------------------
# 数据加载与分组
# ---------------------------------------------------------------------------
def load_data():
    with open(os.path.join(DATA_DIR, "latest.json"), encoding="utf-8") as f:
        latest_data = json.load(f)
    with open(os.path.join(DATA_DIR, "series.json"), encoding="utf-8") as f:
        series_data = json.load(f)
    reports_path = os.path.join(DATA_DIR, "reports.json")
    reports = []
    if os.path.exists(reports_path):
        with open(reports_path, encoding="utf-8") as f:
            reports = json.load(f).get("reports", [])
    return latest_data, series_data, reports


def build_groups(latest):
    groups = {}
    for ind, info in latest.items():
        cat = info.get("category", "其他")
        groups.setdefault(cat, []).append((ind, info))
    return groups


# ---------------------------------------------------------------------------
# 各页面渲染
# ---------------------------------------------------------------------------
def render_home(latest_data, series_data, reports):
    latest = latest_data["latest"]
    derived = latest_data["derived"]
    updated = latest_data["updated"]
    groups = build_groups(latest)

    H = [page_head("首页", "index.html", updated)]
    H.append('<div class="hero"><h2>美国宏观全景 · 实时监测</h2>')
    H.append('<div class="desc">基于「美国宏观数据训练营（829/830）」方法论构建，覆盖就业、通胀、增长、财政、货币、领先指标六大维度，配套专题自动分析引擎。数据由 FRED / BLS / BEA / Census 四大官方源自动更新。</div>')
    H.append('<div class="status"><span class="live"></span>数据自动更新 · 每日 07:30 精准刷新</div></div>')

    H.append(section_head("🎯", "核心派生指标"))
    H.append(kpi_html(derived))

    H.append(section_head("🚨", "预警信号灯", more="查看全部专题"))
    H.append(signals_html(reports))

    H.append(section_head("📊", "关键趋势"))
    home_charts_data = {}
    H.append(charts_html(HOME_CHARTS, series_data, home_charts_data))
    H.append(charts_script(home_charts_data))

    H.append(section_head("🗓️", "月度发布节奏（该盯什么数据）"))
    H.append(render_calendar())

    H.append(page_foot())
    return "".join(H)


def render_calendar():
    items = [
        ("月初 · 第1个工作日", "ISM 制造业 PMI", "全球大类资产共同因子，领先经济拐点"),
        ("首周周五", "非农就业报告", "NFP + 失业率 + 平均时薪，数据之王"),
        ("月中 · 约12-15日", "CPI / 零售销售", "通胀政策之锚 + 消费压舱石"),
        ("每周四", "首申失业金", "唯一周度就业指标，领先失业率"),
        ("月末", "PCE / GDP（BEA）", "美联储 2% 目标口径 + 国民账户"),
        ("FOMC 周（年8次）", "点阵图 / SEP / 声明", "利率路径与长期中性利率锚"),
    ]
    parts = ['<div class="cal-grid">']
    for t, name, desc in items:
        parts.append(
            f'<div class="cal"><div class="cal-time">{esc(t)}</div>'
            f'<div class="cal-name">{esc(name)}</div>'
            f'<div class="cal-desc">{esc(desc)}</div></div>'
        )
    parts.append('</div>')
    return "".join(parts)


def render_theme(fn, title, desc, cats, latest_data, series_data):
    updated = latest_data["updated"]
    groups = build_groups(latest_data["latest"])
    key = fn.replace(".html", "")
    charts = THEME_CHARTS.get(key, [])
    tips = THEME_TIPS.get(key, [])

    H = [page_head(title, fn, updated)]
    H.append(f'<div class="pagehead"><div class="crumb">主题</div><h2>{esc(title)}</h2>'
             f'<div class="desc">{esc(desc)}</div></div>')

    if tips:
        H.append(section_head("💡", "口径要点"))
        H.append(tips_html(tips))

    if key == "employment":
        # 就业页专属：CES / CPS / 其他 三大部分，用分割线分隔（不用"核心图表+全部指标"模板）
        H.append(employment_sections_html(series_data))
    else:
        if charts:
            H.append(section_head("📊", "核心图表"))
            theme_charts_data = {}
            H.append(charts_html(charts, series_data, theme_charts_data))
            H.append(charts_script(theme_charts_data))
        H.append(section_head("📌", "全部指标", count=sum(len(groups.get(c, [])) for c in cats)))
        H.append(metric_cards(groups, series_data, cats))

    H.append(page_foot())
    return "".join(H)


def employment_sections_html(series_data):
    """就业页三大部分：CES / CPS / 其他，用分割线（.divider）分隔，每个图表支持点击放大。"""
    blocks = []
    data_map = {}
    for i, sec in enumerate(EMPLOYMENT_SECTIONS):
        if i > 0:
            blocks.append('<div class="divider"></div>')
        blocks.append(
            f'<div class="part-head"><span class="part-icon">{sec["icon"]}</span>'
            f'<div class="part-text"><h3>{esc(sec["title"])}</h3>'
            f'<p>{esc(sec["desc"])}</p></div></div>'
        )
        blocks.append(charts_html(sec["charts"], series_data, data_map))
    blocks.append(charts_script(data_map))
    return "".join(blocks)


def render_topics(latest_data, series_data, reports):
    updated = latest_data["updated"]
    H = [page_head("专题分析", "topics.html", updated)]
    H.append('<div class="pagehead"><div class="crumb">分析</div><h2>专题分析</h2>'
             '<div class="desc">把核心框架固化为自动触发规则，数据刷新时命中即生成专题短析。点击任一专题卡片进入独立分析页面。</div></div>')
    H.append(section_head("🧭", f"全部专题（{len(reports)} 篇）"))
    H.append(topics_html(reports))
    H.append(page_foot())
    return "".join(H)


def render_topic_detail(r, series_data, updated, beveridge_html=None):
    """渲染单个专题的独立分析页面。beveridge 用独立 Canvas 页。"""
    tid = r["id"]
    title = r["title"]
    sev = r.get("severity", "normal")
    triggered = r.get("triggered")
    charts = TOPIC_DETAIL_CHARTS.get(tid, [])

    H = [f'''<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · 美国宏观数据看板</title>
<link rel="icon" type="image/png" sizes="256x256" href="../assets/koala-us-macro.png">
<link rel="icon" type="image/x-icon" href="../assets/favicon.ico">
<link rel="apple-touch-icon" href="../assets/koala-us-macro-180.png">
<link rel="stylesheet" href="../assets/style.css">
<script src="../assets/echarts.min.js"></script>
<script src="../assets/charts.js"></script>
</head><body>
<div class="nav"><div class="nav-inner">
  <a href="../index.html" class="logo"><span class="logo-dot"></span><h1>美国宏观数据看板</h1></a>
  <div class="links">
    <a href="../index.html">首页</a>
    <a href="../employment.html">就业</a>
    <a href="../inflation.html">通胀</a>
    <a href="../growth.html">增长</a>
    <a href="../fiscal.html">财政</a>
    <a href="../monetary.html">货币</a>
    <a href="../leading.html">领先</a>
    <a href="../topics.html" class="active">专题</a>
    <a href="../about.html">关于</a>
  </div>
  <div class="spacer"></div>
  <div class="update">上次更新<br><b>{esc(updated)}</b></div>
</div></div>
<div class="wrap">
''']

    badge_cls = "warn" if triggered else ("info" if sev == "info" else "ok")
    badge_txt = "⚠ 预警" if triggered else ("观察" if sev == "info" else "正常")
    H.append(f'<div class="pagehead"><div class="crumb"><a href="../topics.html" style="color:var(--cyan)">← 返回专题列表</a></div>'
             f'<h2>{esc(title)}</h2>'
             f'<span class="t-badge {badge_cls}" style="font-size:12px;padding:3px 12px">{badge_txt}</span></div>')

    if r.get("data"):
        items = []
        for k, v in r["data"].items():
            if isinstance(v, float):
                v = f"{v:.2f}"
            items.append(f'<span class="t-data">{esc(k)} = {esc(v)}</span>')
        H.append('<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px">' + "".join(items) + '</div>')

    H.append(section_head("📝", "分析结论"))
    H.append(f'<div class="tip"><div class="tip-body" style="font-size:14px;line-height:1.9">{esc(r.get("analysis",""))}</div></div>')

    if r.get("framework"):
        H.append(section_head("📌", "分析框架"))
        H.append(f'<div class="tip"><div class="tip-body">{esc(r["framework"])}</div></div>')

    if tid == "beveridge" and beveridge_html:
        H.append(section_head("📊", "贝弗里奇曲线（互动图）"))
        H.append(beveridge_html)
    elif charts:
        H.append(section_head("📊", "数据图表"))
        topic_charts_data = {}
        H.append(charts_html(charts, series_data, topic_charts_data))
        H.append(charts_script(topic_charts_data))

    if r.get("watch"):
        H.append(section_head("🔭", "下一步关注"))
        H.append(f'<div class="tip"><div class="tip-title">需要盯的下一个数据</div><div class="tip-body">{esc(r["watch"])}</div></div>')

    H.append(page_foot())
    return "".join(H)


def render_about(latest_data, series_data, reports):
    updated = latest_data["updated"]
    H = [page_head("关于", "about.html", updated)]
    H.append('<div class="pagehead"><div class="crumb">说明</div><h2>关于本看板</h2>'
             '<div class="desc">数据口径速查与方法论来源，帮你快速理解每个指标"该怎么读"。</div></div>')

    H.append(section_head("📖", "关键口径速查"))
    dict_rows = [
        ("CPI vs PCE", "拉氏 vs 链式；医疗 8% vs 17%、住房 36% vs 15%；美联储盯 PCE，市场盯 CPI", "正常 CPI ≈ PCE + 0.3~0.5pp"),
        ("CES vs CPS", "企业调查（岗位）vs 家庭调查（人数）；12 万家企业 vs 6 万户", "新增看 CES，结构看 CPS"),
        ("NBER vs 技术性衰退", "一揽子（就业/消费/工业生产）vs 连续两季负增长", "1948 以来 10 次技术性衰退全为 NBER"),
        ("U3 vs U6", "官方失业率 vs 广义（含不充分就业）", "U6 更能反映就业市场松紧"),
        ("超级核心服务", "剔除住房的核心服务，鲍威尔最警惕", "通胀最顽固的分项"),
        ("PDFP", "国内购买者最终销售，剔除净出口+库存", "'核心 GDP'，看真实内需"),
        ("5y5y 远期补偿", "5 年后的 5 年通胀预期，最严格锚定", "显著抬升 = 市场不信任美联储"),
        ("V/U 比率", "岗位空缺 / 失业人数", "领先工资通胀约 2 季度"),
        ("r - g", "实际利率 - 实际增速", "r<g 可增长化债"),
        ("统计月 vs 发布日", "图表日期戳（如 2018-03）指统计参考期，非发布当天", "数据通常在次月才发布，详见各指标卡标注"),
    ]
    H.append('<table class="dict-table"><thead><tr><th style="width:160px">口径</th><th>含义</th><th style="width:220px">用法/阈值</th></tr></thead><tbody>')
    for k, meaning, usage in dict_rows:
        H.append(f'<tr><td><span class="k">{esc(k)}</span></td><td>{esc(meaning)}</td><td>{esc(usage)}</td></tr>')
    H.append('</tbody></table>')

    H.append(section_head("🗓️", "日期语义说明"))
    H.append('<div class="tip"><div class="tip-title">统计月份 ≠ 发布时间</div>'
             '<div class="tip-body">所有月度/季度数据的日期戳代表<b>统计参考期</b>（数据描述的是哪一个月/季度的经济状况），'
             '而非数据发布的当天。例如"2018-03 失业率 4.0%"指<b>2018 年 3 月</b>的失业率为 4.0%，这一数据由 BLS 在 '
             '<b>2018 年 4 月首周周五</b>才发布。各指标卡与图表悬浮提示中均已标注对应的发布规则。'
             '滞后最明显的是 JOLTS（岗位空缺，滞后约 1~2 个月）与季度 GDP（次季首月月末才发布），阅读时请勿把日期戳误读为"最新可得数据的那一天"。</div></div>')

    H.append(section_head("🎓", "方法论来源"))
    H.append('<div class="tip"><div class="tip-title">📚 美国宏观数据训练营（腾讯会议 829/830）</div>'
             '<div class="tip-body">829 主体（8h）+ 尾段（28min）：数据体系 / 就业 / 通胀 / 滞胀 / GDP；830 上午（约 2h53m）：财税立法 / 债务可持续性 / 化债路径；830 下午（约 4h）：货币政策框架 / FOMC / 消费 / 房地产 / PMI。</div></div>')
    H.append('<div class="tip"><div class="tip-title">🔧 技术实现</div>'
             '<div class="tip-body">数据源 FRED / BLS / BEA / Census 四大官方 API；发布日历驱动的精准增量更新；专题规则引擎自动生成分析；ECharts 本地渲染。</div></div>')

    H.append(page_foot())
    return "".join(H)


def beveridge_canvas_block():
    """贝弗里奇曲线 Canvas 互动图（暗色适配），返回 HTML 片段 + 内嵌数据 JS。"""
    data_path = os.path.join(DATA_DIR, "beveridge_data.json")
    if not os.path.exists(data_path):
        return '<div class="tip"><div class="tip-body">贝弗里奇数据未就绪（缺 data/beveridge_data.json）。</div></div>'
    with open(data_path, encoding="utf-8") as f:
        bev = json.load(f)
    bev_json = json.dumps(bev, ensure_ascii=False)

    # 侧边统计卡 + 主图 Canvas + 时间轨迹 Canvas（暗色版）
    stats = bev["stats"]
    return f'''<style>
.bv-wrap{{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px;align-items:start}}
.bv-canvas-card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px 8px}}
.bv-canvas-card h4{{font-size:14px;font-weight:700;margin-bottom:2px}}
.bv-canvas-card .sub{{font-size:11.5px;color:var(--text3);margin-bottom:10px}}
.bv-canvas-card canvas{{display:block;width:100%}}
#bc_canvas{{height:440px}}
#ts_canvas{{height:230px}}
.bv-side{{display:flex;flex-direction:column;gap:12px}}
.bv-stat{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 15px}}
.bv-stat .k{{font-size:11.5px;color:var(--text3)}}
.bv-stat .v{{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;margin-top:2px}}
.bv-stat .v small{{font-size:12px;font-weight:500;color:var(--text2);margin-left:3px}}
.bv-stat .m{{font-size:11.5px;color:var(--text2);margin-top:3px;line-height:1.5}}
.bv-stat.hero{{border-left:3px solid var(--blue)}}
.bv-stat.warn{{border-left:3px solid var(--red)}}
.bv-stat.warn .v{{color:var(--red)}}
.bv-verdict{{background:rgba(234,179,8,.06);border:1px solid rgba(234,179,8,.3);border-left:3px solid var(--gold);border-radius:12px;padding:13px 15px;font-size:12.5px;color:var(--text);line-height:1.65}}
.bv-verdict b{{color:var(--gold)}}
.bv-verdict ul{{margin:6px 0 0;padding-left:16px}}
.bv-verdict li{{margin:3px 0}}
.bv-legend{{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}}
.bv-chip{{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--text2);background:var(--card2);border:1px solid var(--line);border-radius:999px;padding:3px 9px;cursor:pointer;user-select:none}}
.bv-chip i{{width:8px;height:8px;border-radius:50%;display:block}}
.bv-chip.off{{opacity:.38}}
@media(max-width:960px){{.bv-wrap{{grid-template-columns:1fr}}}}
</style>
<div class="bv-wrap">
  <div style="display:flex;flex-direction:column;gap:14px;min-width:0">
    <div class="bv-canvas-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
        <div><h4>贝弗里奇曲线</h4><div class="sub">职位空缺率 × 失业率 · 虚线为 V/U=1 供需平衡线</div></div>
        <div class="bv-legend" id="bv_legend"></div>
      </div>
      <canvas id="bc_canvas"></canvas>
    </div>
    <div class="bv-canvas-card">
      <h4>空缺率与失业率的时间轨迹</h4>
      <div class="sub">阴影区间：2020–21 疫情错配 / 2022–24 回落期</div>
      <canvas id="ts_canvas"></canvas>
    </div>
  </div>
  <div class="bv-side">
    <div class="bv-stat hero">
      <div class="k">最新月份 · <span id="bv_lm">—</span></div>
      <div class="v"><span id="bv_vac">—</span><small>% 空缺率</small></div>
      <div class="m">失业率 <b id="bv_un">—</b>%　·　V/U <b id="bv_ratio">—</b></div>
    </div>
    <div class="bv-stat warn">
      <div class="k">距离 B-S「6%」门槛</div>
      <div class="v"><span id="bv_gap">—</span><small>个百分点</small></div>
      <div class="m">Blanchard-Summers 认为失业率需升至 6%+ 才能让通胀回到 2%。</div>
    </div>
    <div class="bv-stat">
      <div class="k">自空缺率峰值（<span id="bv_pkd">—</span>）以来</div>
      <div class="m">空缺率 <b id="bv_dv">—</b>，失业率 <b id="bv_du">—</b>，历经 <b id="bv_pkn">—</b> 个月，曲线近乎垂直回落。</div>
    </div>
    <div class="bv-stat">
      <div class="k">曲线与 V/U=1 交点（自然失业率近似）</div>
      <div class="v" id="bv_nat">—</div>
      <div class="m">约 <b id="bv_natv">—</b>% 空缺率（<span id="bv_natd">—</span>）</div>
    </div>
    <div class="bv-verdict">
      <b>判读</b>
      <ul id="bv_verdict_list"></ul>
    </div>
  </div>
</div>
<script>
window.BEVERIDGE_DATA = {bev_json};
</script>
<script>
(function(){{
  "use strict";
  var D = window.BEVERIDGE_DATA;
  if(!D) return;
  var P = D.points, S = D.stats;
  var SEG = [
    {{k:"pre",   label:"2001–19",             from:"2000-01", to:"2019-12", color:"#6b7a90", r:2.2, lw:1.1}},
    {{k:"covid", label:"2020–21 疫情错配",    from:"2020-01", to:"2021-12", color:"#f5a623", r:3.0, lw:1.7}},
    {{k:"tight", label:"2022–24 软着陆(垂直)",from:"2022-01", to:"2024-12", color:"#e5484d", r:3.0, lw:1.7}},
    {{k:"now",   label:"2025– 至今",          from:"2025-01", to:"9999-12", color:"#3b82f6", r:3.3, lw:1.9}}
  ];
  var segOf = function(d){{ var m=d.slice(0,7); for(var i=0;i<SEG.length;i++){{ if(m>=SEG[i].from && m<=SEG[i].to) return SEG[i]; }} return SEG[0]; }};
  P.forEach(function(p){{ p.s = segOf(p.d); }});
  var hidden = {{}};
  var fmt1 = function(x){{ return (Math.round(x*10)/10).toFixed(1); }};
  var fmt2 = function(x){{ return (Math.round(x*100)/100).toFixed(2); }};
  var sgn = function(x){{ return (x>0?"+":"")+fmt1(x); }};
  var ym = function(d){{ return d.slice(0,7).replace("-","年")+"月"; }};
  var ymS = function(d){{ return d.slice(0,7); }};

  document.getElementById("bv_lm").textContent = ymS(S.latest_period+"-01");
  document.getElementById("bv_vac").textContent = fmt1(S.latest_v);
  document.getElementById("bv_un").textContent = fmt1(S.latest_u);
  document.getElementById("bv_ratio").textContent = fmt2(S.latest_ratio);
  document.getElementById("bv_gap").textContent = (S.gap_to_6>0?fmt1(S.gap_to_6):"0");
  document.getElementById("bv_pkd").textContent = ymS(S.peak_period+"-01");
  document.getElementById("bv_dv").textContent = sgn(S.dv_since_peak)+"pct";
  document.getElementById("bv_dv").style.color = "#2ea043";
  document.getElementById("bv_du").textContent = sgn(S.du_since_peak)+"pct";
  document.getElementById("bv_du").style.color = "#e5484d";
  document.getElementById("bv_pkn").textContent = S.months_since_peak;
  document.getElementById("bv_nat").innerHTML = fmt1(S.nat_u_est)+"<small>% 失业率</small>";
  document.getElementById("bv_natd").textContent = ymS(S.nat_period+"-01");
  document.getElementById("bv_natv").textContent = fmt1(S.nat_v_est);

  document.getElementById("bv_verdict_list").innerHTML = [
    "空缺率自峰值 "+fmt1(S.peak_v)+"% 回落 <b>"+fmt1(Math.abs(S.dv_since_peak))+"pct</b> 至 "+fmt1(S.latest_v)+"%，同期失业率仅从 "+fmt1(S.peak_u)+"% 升至 <b>"+fmt1(S.latest_u)+"%</b>（"+sgn(S.du_since_peak)+"pct）。",
    "V/U 由 "+fmt2(S.peak_ratio)+" 降至 <b>"+fmt2(S.latest_ratio)+"</b>，已回到供需平衡线附近，2019 年均值为 "+fmt2(S.pre2019_ratio)+"。",
    "过程中失业率最高 <b>"+fmt1(Math.max.apply(null, P.filter(function(p){{return p.d>="2022-01";}}).map(function(p){{return p.u;}})))+"%</b>，始终未触及 6% 门槛，B-S 的「深度衰退」路径未兑现。"
  ].map(function(t){{return "<li>"+t+"</li>";}}).join("");

  var legend = document.getElementById("bv_legend");
  SEG.forEach(function(s){{
    var b = document.createElement("span");
    b.className = "bv-chip";
    b.innerHTML = '<i style="background:'+s.color+'"></i>'+s.label;
    b.onclick = function(){{
      if(hidden[s.k]){{ delete hidden[s.k]; b.classList.remove("off"); }}
      else{{ hidden[s.k]=1; b.classList.add("off"); }}
      drawBC(); drawTS();
    }};
    legend.appendChild(b);
  }});

  var T = {{grid:"#1a2230", axis:"#2c3748", tick:"#6b7a90", text:"#9aa7b8", ink:"#e6edf3"}};
  function fit(cv, cssH){{
    var dpr = window.devicePixelRatio||1;
    var w = cv.clientWidth || cv.parentNode.clientWidth;
    cv.width = Math.round(w*dpr); cv.height = Math.round(cssH*dpr);
    var ctx = cv.getContext("2d");
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,w,cssH);
    return {{ctx:ctx,w:w,h:cssH}};
  }}
  function roundRect(ctx,x,y,w,h,r){{
    ctx.beginPath();
    ctx.moveTo(x+r,y);ctx.lineTo(x+w-r,y);ctx.quadraticCurveTo(x+w,y,x+w,y+r);
    ctx.lineTo(x+w,y+h-r);ctx.quadraticCurveTo(x+w,y+h,x+w-r,y+h);
    ctx.lineTo(x+r,y+h);ctx.quadraticCurveTo(x,y+h,x,y+h-r);
    ctx.lineTo(x,y+r);ctx.quadraticCurveTo(x,y,x+r,y);ctx.closePath();
  }}

  var cvBC = document.getElementById("bc_canvas");
  var uAll = P.map(function(p){{return p.u;}}), vAll = P.map(function(p){{return p.v;}});
  var DOM = {{
    xMin: Math.min(3, Math.floor(Math.min.apply(null,uAll))),
    xMax: Math.max(15, Math.ceil(Math.max.apply(null,uAll))),
    yMin: Math.max(0, Math.min(1, Math.floor(Math.min.apply(null,vAll)))),
    yMax: Math.max(8, Math.ceil(Math.max.apply(null,vAll)))
  }};
  var geoBC = null;

  function drawBC(){{
    var r = fit(cvBC, cvBC.clientHeight);
    var ctx=r.ctx, w=r.w, h=r.h;
    var pad = {{l:60,r:22,t:24,b:48}};
    var pw = w-pad.l-pad.r, ph = h-pad.t-pad.b;
    var X = function(u){{return pad.l+(u-DOM.xMin)/(DOM.xMax-DOM.xMin)*pw;}};
    var Y = function(v){{return pad.t+ph-(v-DOM.yMin)/(DOM.yMax-DOM.yMin)*ph;}};
    geoBC = {{X:X,Y:Y}};
    ctx.strokeStyle = T.grid; ctx.lineWidth=1;
    ctx.font = "11px 'Segoe UI','Microsoft YaHei',sans-serif"; ctx.fillStyle=T.tick;
    for(var u=Math.ceil(DOM.xMin/2)*2; u<=DOM.xMax-1; u+=2){{
      ctx.beginPath();ctx.moveTo(X(u),pad.t);ctx.lineTo(X(u),pad.t+ph);ctx.stroke();
      ctx.textAlign="center";ctx.textBaseline="top";ctx.fillText(u,X(u),pad.t+ph+9);
    }}
    for(var v=Math.ceil(DOM.yMin); v<=DOM.yMax; v++){{
      ctx.beginPath();ctx.moveTo(pad.l,Y(v));ctx.lineTo(pad.l+pw,Y(v));ctx.stroke();
      ctx.textAlign="right";ctx.textBaseline="middle";ctx.fillText(v,pad.l-10,Y(v));
    }}
    ctx.strokeStyle=T.axis; ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(pad.l,pad.t);ctx.lineTo(pad.l,pad.t+ph);ctx.lineTo(pad.l+pw,pad.t+ph);ctx.stroke();
    // B-S 6% 门槛
    ctx.save();ctx.setLineDash([2,4]);ctx.strokeStyle="rgba(229,72,77,.5)";ctx.lineWidth=1.2;
    ctx.beginPath();ctx.moveTo(X(6),pad.t+2);ctx.lineTo(X(6),pad.t+ph);ctx.stroke();ctx.restore();
    ctx.save();ctx.textAlign="left";ctx.textBaseline="top";ctx.fillStyle="rgba(229,72,77,.85)";ctx.font="10.5px 'Segoe UI','Microsoft YaHei',sans-serif";
    ctx.fillText("B-S 门槛 6%", X(6)+5, pad.t+4);ctx.restore();
    // V/U=1 线
    ctx.save();ctx.setLineDash([6,5]);ctx.strokeStyle="#5b6572";ctx.lineWidth=1.3;
    ctx.beginPath();ctx.moveTo(X(DOM.xMin),Y(DOM.xMin));ctx.lineTo(X(DOM.yMax),Y(DOM.yMax));ctx.stroke();ctx.restore();
    ctx.save();ctx.translate(X(7.0),Y(7.0)-10);ctx.rotate(-Math.atan2(Y(7)-Y(6),X(7)-X(6)));
    ctx.fillStyle="#5b6572";ctx.font="10.5px 'Segoe UI','Microsoft YaHei',sans-serif";ctx.textAlign="left";ctx.textBaseline="bottom";
    ctx.fillText("V/U = 1 供需平衡线",6,-4);ctx.restore();
    // 系列
    SEG.forEach(function(sg){{
      if(hidden[sg.k]) return;
      var pts = P.filter(function(p){{return p.s.k===sg.k;}});
      if(!pts.length) return;
      ctx.lineWidth=sg.lw; ctx.strokeStyle=sg.color;
      ctx.globalAlpha = sg.k==="pre"?0.55:0.85;
      ctx.beginPath();
      pts.forEach(function(p,i){{ var x=X(p.u),y=Y(p.v); if(i)ctx.lineTo(x,y); else ctx.moveTo(x,y); }});
      ctx.stroke(); ctx.globalAlpha=1;
      pts.forEach(function(p){{
        ctx.beginPath();ctx.arc(X(p.u),Y(p.v),sg.r,0,7);ctx.fillStyle=sg.color;ctx.fill();
        if(sg.k!=="pre"){{ctx.strokeStyle="#0b0f14";ctx.lineWidth=1;ctx.stroke();}}
      }});
    }});
    // 最新点高亮
    var last = P[P.length-1];
    if(!hidden[last.s.k]){{
      var x=X(last.u), y=Y(last.v);
      ctx.beginPath();ctx.arc(x,y,11,0,7);ctx.fillStyle="rgba(59,130,246,.16)";ctx.fill();
      ctx.beginPath();ctx.arc(x,y,5.5,0,7);ctx.fillStyle="#0b0f14";ctx.fill();
      ctx.lineWidth=2.4;ctx.strokeStyle=last.s.color;ctx.stroke();
    }}
    ctx.fillStyle=T.text; ctx.font="12px 'Segoe UI','Microsoft YaHei',sans-serif";
    ctx.textAlign="center";ctx.textBaseline="top";ctx.fillText("失业率 %", pad.l+pw/2, pad.t+ph+30);
    ctx.save();ctx.translate(16,pad.t+ph/2);ctx.rotate(-Math.PI/2);ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillText("职位空缺率 %",0,0);ctx.restore();
  }}

  var cvTS = document.getElementById("ts_canvas");
  function drawTS(){{
    var r = fit(cvTS, cvTS.clientHeight);
    var ctx=r.ctx, w=r.w, h=r.h;
    var pad = {{l:40,r:22,t:14,b:30}};
    var pw=w-pad.l-pad.r, ph=h-pad.t-pad.b, n=P.length;
    var X = function(i){{return pad.l+(n<=1?0:i/(n-1))*pw;}};
    var TS_MAX=16;
    var Y = function(v){{return pad.t+ph-(v-0)/TS_MAX*ph;}};
    var band = function(from,to,fill){{
      var i0=P.findIndex(function(p){{return p.d.slice(0,7)>=from;}});
      var i1=-1;
      for(var i=P.length-1;i>=0;i--){{ if(P[i].d.slice(0,7)<=to){{i1=i;break;}} }}
      if(i0<0||i1<0) return;
      ctx.fillStyle=fill; ctx.fillRect(X(i0),pad.t,Math.max(1,X(i1)-X(i0)),ph);
    }};
    band("2020-01","2021-12","rgba(245,166,35,.10)");
    band("2022-01","2024-12","rgba(229,72,77,.075)");
    ctx.strokeStyle=T.grid; ctx.lineWidth=1;
    ctx.font="11px 'Segoe UI','Microsoft YaHei',sans-serif"; ctx.fillStyle=T.tick;
    for(var v=0; v<=TS_MAX; v+=4){{
      ctx.beginPath();ctx.moveTo(pad.l,Y(v));ctx.lineTo(pad.l+pw,Y(v));ctx.stroke();
      ctx.textAlign="right";ctx.textBaseline="middle";ctx.fillText(v,pad.l-8,Y(v));
    }}
    var seen={{}};
    P.forEach(function(p,i){{
      var y=p.d.slice(0,4);
      if(!seen[y] && (+y)%2===0 && (+p.d.slice(5,7))<=2){{seen[y]=1;ctx.textAlign="center";ctx.textBaseline="top";ctx.fillText(y,X(i),pad.t+ph+8);}}
    }});
    var line = function(field,color,lw){{
      ctx.strokeStyle=color;ctx.lineWidth=lw;ctx.lineJoin="round";ctx.beginPath();
      P.forEach(function(p,i){{var x=X(i),y=Y(p[field]); if(i)ctx.lineTo(x,y); else ctx.moveTo(x,y);}});
      ctx.stroke();
    }};
    line("v","#f5a623",1.9); line("u","#9aa7b8",1.9);
    var pi = P.reduce(function(a,p,i){{return p.v>P[a].v?i:a;}},0);
    ctx.setLineDash([3,3]);ctx.strokeStyle="rgba(245,166,35,.7)";ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(X(pi),Y(P[pi].v));ctx.lineTo(X(pi),pad.t+ph);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle="#f5a623";ctx.textAlign="center";ctx.textBaseline="bottom";ctx.font="10.5px 'Segoe UI','Microsoft YaHei',sans-serif";
    ctx.fillText("空缺率峰值 "+fmt1(P[pi].v)+"%", X(pi), Y(P[pi].v)-6);
  }}

  function redrawAll(){{ drawBC(); drawTS(); }}
  var raf=null;
  window.addEventListener("resize",function(){{cancelAnimationFrame(raf);raf=requestAnimationFrame(redrawAll);}});
  if(window.ResizeObserver) new ResizeObserver(function(){{cancelAnimationFrame(raf);raf=requestAnimationFrame(redrawAll);}}).observe(document.body);
  redrawAll();
}})();
</script>'''


def render():
    os.makedirs(SITE_DIR, exist_ok=True)
    site_assets = os.path.join(SITE_DIR, "assets")
    os.makedirs(site_assets, exist_ok=True)
    for f in ["echarts.min.js", "style.css", "charts.js"]:
        src = os.path.join(ASSETS_SRC, f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(site_assets, f))

    latest_data, series_data, reports = load_data()

    pages = {
        "index.html": render_home(latest_data, series_data, reports),
        "topics.html": render_topics(latest_data, series_data, reports),
        "about.html": render_about(latest_data, series_data, reports),
    }
    for fn, title, desc, cats in THEME_PAGES:
        pages[fn] = render_theme(fn, title, desc, cats, latest_data, series_data)

    for fn, content in pages.items():
        with open(os.path.join(SITE_DIR, fn), "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  ✓ {fn}  ({len(content)} 字节)")

    # 专题详情页：site/topics/<topic_id>.html
    topics_dir = os.path.join(SITE_DIR, "topics")
    os.makedirs(topics_dir, exist_ok=True)
    updated = latest_data["updated"]
    n_topics = 0
    for r in reports:
        tid = r.get("id")
        if not tid:
            continue
        # 贝弗里奇用独立 Canvas 页（复用现有实现，暗色适配）
        bev_html = None
        if tid == "beveridge":
            bev_html = beveridge_canvas_block()
        content = render_topic_detail(r, series_data, updated, beveridge_html=bev_html)
        with open(os.path.join(topics_dir, f"{tid}.html"), "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  ✓ topics/{tid}.html  ({len(content)} 字节)")
        n_topics += 1

    print(f"\n渲染完成 -> {SITE_DIR}/ 共 {len(pages)} 个主页面 + {n_topics} 个专题详情页")


if __name__ == "__main__":
    render()
