#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美国宏观数据看板 - 专题分析规则引擎
把核心框架固化为自动触发规则，命中即生成一篇专题短析。
输出：data/reports.json（每篇专题：标题、触发状态、解读、需盯数据）
"""
import os, sys, json, datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
DATA_DIR = os.path.join(BASE_DIR, "data")

from indicators import TOPIC_RULES


def latest_value(series):
    for p in reversed(series):
        if p["value"] is not None:
            return p
    return None


def mean(series, n=12):
    pts = [p["value"] for p in series if p["value"] is not None][-n:]
    return sum(pts) / len(pts) if pts else None


# ---------------------------------------------------------------------------
# 各专题判断函数：输入 series / derived / latest，输出 dict 或 None
# ---------------------------------------------------------------------------
def topic_inflation_anchor(series, derived, latest):
    """5y5y 远期通胀补偿显著抬升（相对近1年均值偏离>50bp）。"""
    s = series.get("fwd5y5y", [])
    lv = latest_value(s)
    if not lv:
        return None
    avg = mean(s, 12)  # 近12个月日均值
    if avg is None:
        return None
    dev = lv["value"] - avg
    triggered = abs(dev) > 0.5
    direction = "抬升" if dev > 0 else "回落"
    return {
        "id": "inflation_anchor",
        "title": "通胀锚定是否动摇（5y5y 远期通胀补偿）",
        "triggered": triggered,
        "severity": "high" if triggered else "normal",
        "data": {"current": round(lv["value"], 2), "avg_12m": round(avg, 2), "dev_bp": round(dev * 100, 0)},
        "analysis": (
            f"5y5y 远期通胀补偿当前 {lv['value']:.2f}%，近12个月均值 {avg:.2f}%，"
            f"偏离 {dev*100:.0f}bp（{direction}）。"
            + ("⚠️ 显著偏离，提示市场对美联储长期控通胀能力（独立性）的信任度发生变化，需重点跟踪。"
               if triggered else
               "仍在历史区间内，通胀预期大致锚定。")
        ),
        "framework": TOPIC_RULES["inflation_anchor"]["framework"],
        "watch": "后续关注：盈亏平衡通胀率 BEI10y、黄金/美元、5y5y 是否持续同向",
    }


def topic_labor_freeze(series, derived, latest):
    """V/U 比率持续 < 1 且首申抬升。"""
    vu = derived.get("vu_ratio", {}).get("value")
    claims = latest_value(series.get("claims", []))
    if vu is None:
        return None
    triggered = vu < 1.0
    claims_note = f"首申失业金当前 {claims['value']:,.0f}（{claims['date']}）" if claims else "首申数据缺失"
    return {
        "id": "labor_freeze",
        "title": "就业市场是否'冻僵'（V/U 比率）",
        "triggered": triggered,
        "severity": "high" if triggered else "normal",
        "data": {"vu": vu, "claims": claims["value"] if claims else None},
        "analysis": (
            f"V/U 比率当前 {vu:.2f}（{'< 1，就业市场趋冷' if triggered else '≥ 1，就业市场大致平衡'}）。"
            f"{claims_note}。"
            + ("⚠️ V/U < 1 且首申抬升时，指向'低招聘+低解雇'的冻僵状态，工资通胀压力下降。"
               if triggered else
               "就业市场处于平衡区间，未见明显冻僵信号。")
        ),
        "framework": TOPIC_RULES["labor_freeze"]["framework"],
        "watch": "后续关注：JOLTS 空缺、非农新增 3MMA、亚特兰大工资跟踪器",
    }


def topic_beveridge(series, derived, latest):
    """贝弗里奇曲线：用失业率 vs 岗位空缺率的历史轨迹判断外移/内移。"""
    unrate = latest_value(series.get("unrate", []))
    jolts = latest_value(series.get("jolts_open", []))
    lf = latest_value(series.get("labor_force", []))
    if not (unrate and jolts and lf):
        return None
    # 岗位空缺率 = JOLTS空缺 / (就业人数 + 空缺)，近似用 JOLTS/劳动力
    vacancy_rate = jolts["value"] / lf["value"] * 100
    return {
        "id": "beveridge",
        "title": "贝弗里奇曲线（失业率 vs 岗位空缺率）",
        "triggered": False,  # 贝弗里奇是观察型，不设硬阈值
        "severity": "info",
        "data": {"unrate": unrate["value"], "vacancy_rate": round(vacancy_rate, 2)},
        "analysis": (
            f"当前失业率 {unrate['value']}%，岗位空缺率约 {vacancy_rate:.2f}%。"
            f"观察曲线位置：若空缺率快速下降而失业率未明显上升（曲线垂直下移），"
            f"对应 2021-22 年美联储'软着陆'情景。"
        ),
        "framework": TOPIC_RULES["beveridge_curve"]["framework"],
        "watch": "后续关注：失业率与空缺率的月度联动轨迹",
    }


def topic_qt_end(series, derived, latest):
    """缩表终点：ON RRP 余额接近归零 + SOFR 突破走廊。"""
    onrrp = latest_value(series.get("on_rrp", []))
    sofr = latest_value(series.get("sofr", []))
    ffr = latest_value(series.get("ffr", []))
    if not onrrp:
        return None
    # RRPONTSYD 单位是 十亿美元（Billions of USD），值 = 千亿美元
    onrrp_usd_bil = onrrp["value"] * 1000  # 换算成亿美元
    triggered = onrrp_usd_bil < 500  # 低于 5000 亿美元视为接近归零
    sofr_note = ""
    if sofr and ffr and sofr["value"] is not None and ffr["value"] is not None:
        spread = sofr["value"] - ffr["value"]
        sofr_note = f"SOFR {sofr['value']:.2f}% vs 联邦基金 {ffr['value']:.2f}%（利差 {spread:+.0f}bp）"
    return {
        "id": "qt_end",
        "title": "缩表是否接近终点（ON RRP 余额）",
        "triggered": triggered,
        "severity": "high" if triggered else "normal",
        "data": {"on_rrp_bil_usd": onrrp_usd_bil, "sofr": sofr["value"] if sofr else None},
        "analysis": (
            f"隔夜逆回购 ON RRP 余额当前约 {onrrp_usd_bil:,.0f} 亿美元。{sofr_note}。"
            + ("⚠️ ON RRP 已降至低位（低于 5000 亿美元），若进一步归零且银行间开始拆借、SOFR 突破走廊上限，"
               "提示缩表接近终点、可能出现钱荒。"
               if triggered else
               "ON RRP 仍有缓冲，流动性充裕，缩表暂无终点信号。")
        ),
        "framework": TOPIC_RULES["qt_end"]["framework"],
        "watch": "后续关注：准备金余额、SRF 使用量、SOFR 与走廊上限关系",
    }


def topic_technical_recession(series, derived, latest):
    """技术性衰退：实际 GDP 连续两季环比折年负增长。"""
    s = series.get("gdp_qoq", [])
    pts = [p for p in s if p["value"] is not None][-3:]
    if len(pts) < 2:
        return None
    last2 = [p["value"] for p in pts[-2:]]
    triggered = all(v < 0 for v in last2)
    return {
        "id": "technical_recession",
        "title": "是否技术性衰退（连续两季 GDP 负增长）",
        "triggered": triggered,
        "severity": "high" if triggered else "normal",
        "data": {"recent_qoq": [round(p["value"], 1) for p in pts]},
        "analysis": (
            f"最近季度 GDP 环比折年：{', '.join(p['date'][:7] + '=' + str(p['value']) + '%' for p in pts)}。"
            + ("⚠️ 连续两季负增长，触发技术性衰退定义；需用 NBER 一揽子（就业/消费/工业生产）交叉验证。"
               if triggered else
               "未触发技术性衰退（需连续两季负增长）。")
        ),
        "framework": TOPIC_RULES["technical_recession"]["framework"],
        "watch": "后续关注：非农新增、实际消费、工业生产（NBER 一揽子）",
    }


def topic_r_minus_g(series, derived, latest):
    """r-g：实际利率 vs 实际增速，增长化债空间。"""
    rg = derived.get("r_minus_g")
    if not rg:
        return None
    v = rg["value"]
    triggered = v >= 0
    return {
        "id": "r_minus_g",
        "title": "增长化债空间（r - g）",
        "triggered": triggered,
        "severity": "medium" if triggered else "normal",
        "data": {"r_minus_g": v, "note": rg.get("note", "")},
        "analysis": (
            f"r - g 当前 {v:.2f}%。"
            + ("⚠️ r ≥ g，债务率趋于发散，增长化债空间消失，需警惕通胀化债或被迫财政整顿。"
               if triggered else
               "r < g，债务率可自然收敛，仍存在增长化债空间。")
        ),
        "framework": TOPIC_RULES["r_minus_g"]["framework"],
        "watch": "后续关注：TIPS10y 实际利率、GDP 实际增速、债务率轨迹",
    }


def topic_cpi_pce_inversion(series, derived, latest):
    """CPI-PCE 倒挂。"""
    gap = derived.get("cpi_pce_gap")
    if not gap:
        return None
    v = gap["value"]
    triggered = v < 0
    return {
        "id": "cpi_pce_inversion",
        "title": "CPI-PCE 剪刀差（口径异常）",
        "triggered": triggered,
        "severity": "medium" if triggered else "normal",
        "data": {"gap": v},
        "analysis": (
            f"CPI - PCE 剪刀差当前 {v:+.2f}pp。"
            + ("⚠️ 罕见倒挂（CPI 跌破 PCE），源于住房降温 + AI 推升 PCE 分项，需关注 BEA 权重调整。"
               if triggered else
               "处于正常区间（CPI 通常高于 PCE 0.3~0.5pp），口径正常。")
        ),
        "framework": TOPIC_RULES["cpi_pce_inversion"]["framework"],
        "watch": "后续关注：住房通胀、软件与消费电子价格、BEA 权重微调",
    }


TOPIC_FUNCS = [
    topic_inflation_anchor, topic_labor_freeze, topic_beveridge, topic_qt_end,
    topic_technical_recession, topic_r_minus_g, topic_cpi_pce_inversion,
]


def run():
    with open(os.path.join(DATA_DIR, "latest.json"), encoding="utf-8") as f:
        latest_data = json.load(f)
    with open(os.path.join(DATA_DIR, "series.json"), encoding="utf-8") as f:
        series_data = json.load(f)

    derived = latest_data["derived"]
    latest = latest_data["latest"]

    reports = []
    for fn in TOPIC_FUNCS:
        try:
            r = fn(series_data, derived, latest)
            if r:
                reports.append(r)
        except Exception as e:
            reports.append({"id": fn.__name__, "title": fn.__name__,
                            "triggered": False, "severity": "error",
                            "analysis": f"规则执行异常: {e}"})

    out = {"updated": datetime.date.today().isoformat(), "reports": reports}
    with open(os.path.join(DATA_DIR, "reports.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"专题分析 {len(reports)} 篇已生成 -> data/reports.json")
    for r in reports:
        mark = "⚠️" if r.get("triggered") else "·"
        print(f"  {mark} {r['title']}")


if __name__ == "__main__":
    run()
