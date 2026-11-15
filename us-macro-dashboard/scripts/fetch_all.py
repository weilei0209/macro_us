#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美国宏观数据看板 - 数据抓取与指标计算主脚本
用法：
  python3 scripts/fetch_all.py            # 全量抓取（首次回填 / 手动刷新）
  python3 scripts/fetch_all.py --incremental  # 精准增量（仅抓发布日历到期的指标）
产出：
  data/cache/<series>.json   原始序列缓存
  data/series.json           标准化后的全量序列（供渲染/分析用）
  data/latest.json           最新值快照 + 派生指标 + 专题触发状态
"""
import os, sys, json, datetime, math

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from indicators import (FRED_SERIES, FRED_META, BLS_SERIES, RELEASE_CALENDAR,
                        DERIVED_INDICATORS, TOPIC_RULES)
from fetcher import (FredClient, BlsClient, BeaClient, CensusClient,
                     load_cache, save_cache, which_indicators_due,
                     cache_path)

DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

TODAY = datetime.date.today()
THIS_YEAR = TODAY.year


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


# ---------------------------------------------------------------------------
# 指标计算工具
# ---------------------------------------------------------------------------
def pct_change_yoy(index_series):
    """指数序列 -> 同比 %（取最新值与 12 个月前的值）。"""
    pts = [(p["date"], p["value"]) for p in index_series if p["value"] is not None]
    if len(pts) < 13:
        return None
    latest = pts[-1]
    # 找 12 个月前的点
    d0 = datetime.date.fromisoformat(latest[0])
    target = d0.replace(year=d0.year - 1)
    best = None
    for date, v in pts:
        dd = datetime.date.fromisoformat(date)
        if dd <= target:
            best = (date, v)
        else:
            break
    if best is None:
        return None
    return (latest[1] / best[1] - 1) * 100


def latest_value(series):
    for p in reversed(series):
        if p["value"] is not None:
            return p
    return None


def latest_n(series, n):
    out = []
    for p in reversed(series):
        if p["value"] is not None:
            out.append(p)
            if len(out) >= n:
                break
    out.reverse()
    return out


def mom_diff(level_series):
    """存量序列 -> 月环比差分（用于非农新增）。"""
    pts = latest_n(level_series, 3)
    if len(pts) < 2:
        return None
    return pts[-1]["value"] - pts[-2]["value"]


def ma3(values):
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return None
    return sum(vals[-3:]) / 3


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    incremental = "--incremental" in sys.argv

    fred = FredClient()
    bls = BlsClient()
    # bea / census 首次回填时用，但核心指标以 FRED + BLS 为主

    # 1. 确定要抓的 FRED 指标
    if incremental:
        due_inds = which_indicators_due(RELEASE_CALENDAR)
        fred_series_to_fetch = [ind for ind in due_inds if ind in FRED_SERIES]
        log(f"增量模式：今天到期 {len(due_inds)} 个指标，其中 FRED {len(fred_series_to_fetch)} 个")
    else:
        fred_series_to_fetch = list(FRED_SERIES.keys())
        log(f"全量模式：抓取 {len(fred_series_to_fetch)} 个 FRED 指标")

    # 2. 抓取 FRED 指标
    all_series = {}  # 内部指标名 -> [{date, value}]
    if incremental:
        # 增量模式：先加载旧序列，再合并新抓取的指标，避免覆盖丢失历史
        series_path = os.path.join(DATA_DIR, "series.json")
        if os.path.exists(series_path):
            try:
                with open(series_path, encoding="utf-8") as f:
                    all_series = json.load(f)
                log(f"增量模式：已加载旧序列 {len(all_series)} 个指标")
            except Exception as e:
                log(f"增量模式：读取旧 series.json 失败({e})，从空开始")
    for ind in fred_series_to_fetch:
        sid = FRED_SERIES[ind]
        try:
            obs = fred.series_observations(sid)
            all_series[ind] = obs
            save_cache(ind, obs)
            log(f"  FRED {ind} ({sid}): {len(obs)} 点, 最新 {obs[-1]['date'] if obs else 'N/A'}")
        except Exception as e:
            # 失败时读缓存
            cached = load_cache(ind)
            if cached:
                all_series[ind] = cached
                log(f"  FRED {ind} 抓取失败({e})，用缓存 {len(cached)} 点")
            else:
                log(f"  FRED {ind} 抓取失败且无缓存: {e}")

    # 3. 抓取 BLS 指标（全量模式才抓；增量模式抓 BLS 到期的）
    if not incremental:
        # BLS 系列较少，一次性抓取（近 2 年足够）
        bls_ids = {name: sid for name, sid in BLS_SERIES.items()}
        try:
            bls_data = bls.fetch(list(bls_ids.values()), THIS_YEAR - 2, THIS_YEAR)
            for name, sid in bls_ids.items():
                rows = bls_data.get(sid, [])
                # 转为 [{date, value}]
                series = []
                for r in rows:
                    try:
                        v = float(r["value"])
                    except (ValueError, TypeError):
                        continue
                    # period: M01..M12, Q1..Q4
                    p = r["period"]
                    if p.startswith("M"):
                        month = int(p[1:])
                        date = f"{r['year']}-{month:02d}-01"
                    elif p.startswith("Q"):
                        q = int(p[1:])
                        month = q * 3
                        date = f"{r['year']}-{month:02d}-01"
                    else:
                        continue
                    series.append({"date": date, "value": v})
                series.sort(key=lambda x: x["date"])
                all_series[name] = series
                save_cache(name, series)
                log(f"  BLS {name} ({sid}): {len(series)} 点")
        except Exception as e:
            log(f"  BLS 抓取失败: {e}")

    # 4. 计算派生指标
    derived = {}
    # V/U 比率 = JOLTS空缺 / 失业人数；失业人数 = 失业率 * 劳动力
    jolts = latest_value(all_series.get("jolts_open", []))
    unrate = latest_value(all_series.get("unrate", []))
    labor_force = latest_value(all_series.get("labor_force", []))
    if jolts and unrate and labor_force and unrate["value"] and labor_force["value"]:
        unemployed = unrate["value"] / 100 * labor_force["value"]
        derived["vu_ratio"] = {
            "value": round(jolts["value"] / unemployed, 3) if unemployed else None,
            "date": max(jolts["date"], unrate["date"], labor_force["date"]),
            "note": f"JOLTS空缺 {jolts['value']:.0f}k / 失业人数 {unemployed:.0f}k（失业率 {unrate['value']}% × 劳动力 {labor_force['value']:.0f}k）",
        }

    # 非农新增（月环比差分）与 3MMA
    payrolls = all_series.get("payrolls", [])
    if payrolls:
        d = mom_diff(payrolls)
        if d is not None:
            derived["payrolls_mom"] = {"value": round(d, 1), "date": latest_value(payrolls)["date"]}
        # 3MMA 需要近3个月的新增
        pts = latest_n(payrolls, 4)
        if len(pts) >= 4:
            diffs = [pts[i+1]["value"] - pts[i]["value"] for i in range(len(pts)-1)]
            derived["payrolls_3mma"] = {"value": round(ma3(diffs), 1), "date": pts[-1]["date"]}

    # CPI / PCE 同比
    for src, out in [("cpi", "cpi_yoy"), ("pcepi", "pce_yoy"),
                     ("cpi_core", "core_cpi_yoy"), ("pce_core", "core_pce_yoy")]:
        s = all_series.get(src, [])
        if s:
            y = pct_change_yoy(s)
            if y is not None:
                derived[out] = {"value": round(y, 2), "date": latest_value(s)["date"]}

    # CPI-PCE 剪刀差
    if "cpi_yoy" in derived and "pce_yoy" in derived:
        derived["cpi_pce_gap"] = {
            "value": round(derived["cpi_yoy"]["value"] - derived["pce_yoy"]["value"], 2),
            "date": derived["cpi_yoy"]["date"],
        }

    # r - g（实际利率 r 用 TIPS10y，g 用 GDP 环比折年近似）
    tips = latest_value(all_series.get("tips10y", []))
    gdp_qoq = latest_value(all_series.get("gdp_qoq", []))
    if tips and gdp_qoq and tips["value"] is not None and gdp_qoq["value"] is not None:
        # date 锚定在季度（g 的时点），r 为最新日频快照；二者频率不同，note 中注明
        derived["r_minus_g"] = {
            "value": round(tips["value"] - gdp_qoq["value"], 2),
            "date": gdp_qoq["date"],
            "note": f"r(TIPS10y, {tips['date']})={tips['value']}% - g(GDP环比折年, {gdp_qoq['date'][:7]})={gdp_qoq['value']}%",
        }

    # 产出缺口（需按日期对齐：用实际GDP最新日期的潜在GDP值）
    gdp_real_series = all_series.get("gdp_real", [])
    gdp_pot_series = all_series.get("gdp_pot", [])
    if gdp_real_series and gdp_pot_series:
        gr = latest_value(gdp_real_series)
        # 在潜在GDP序列中找同日期或最接近（不晚于实际GDP日期）的值
        pot_map = {p["date"]: p["value"] for p in gdp_pot_series if p["value"] is not None}
        gp = pot_map.get(gr["date"]) if gr else None
        if gp and gr and gr["value"]:
            gap = (gr["value"] / gp - 1) * 100
            derived["output_gap"] = {"value": round(gap, 2), "date": gr["date"],
                                     "note": f"实际GDP {gr['value']:.0f} / 潜在GDP {gp:.0f}"}

    log(f"  派生指标 {len(derived)} 个: {list(derived.keys())}")

    # 5. 汇总最新值快照
    # 对"指数型"通胀指标，latest 里存同比 %（而非指数水平），便于渲染直接展示
    YOY_OVERRIDE = {
        "cpi": "cpi_yoy", "cpi_core": "core_cpi_yoy",
        "pcepi": "pce_yoy", "pce_core": "core_pce_yoy", "cpi_median": None,
    }
    latest = {}
    for ind, series in all_series.items():
        meta = FRED_META.get(ind)
        label, cat = meta if isinstance(meta, tuple) else (ind, "其他")
        lv = latest_value(series)
        if not lv:
            continue
        # 指数型指标用同比替代
        if ind in YOY_OVERRIDE and YOY_OVERRIDE[ind] and YOY_OVERRIDE[ind] in derived:
            d = derived[YOY_OVERRIDE[ind]]
            latest[ind] = {
                "label": label, "category": cat,
                "value": d["value"], "date": d["date"],
                "unit": "%", "freq": RELEASE_CALENDAR.get(ind, ("FRED", "daily"))[1],
            }
        else:
            latest[ind] = {
                "label": label, "category": cat,
                "value": lv["value"], "date": lv["date"],
                "unit": "", "freq": RELEASE_CALENDAR.get(ind, ("FRED", "daily"))[1],
            }

    # 6. 写入结果
    with open(os.path.join(DATA_DIR, "series.json"), "w", encoding="utf-8") as f:
        json.dump(all_series, f, ensure_ascii=False)
    with open(os.path.join(DATA_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"updated": TODAY.isoformat(), "latest": latest, "derived": derived},
                  f, ensure_ascii=False, indent=2)

    log(f"完成。series.json 与 latest.json 已更新，最新值 {len(latest)} 个指标")


if __name__ == "__main__":
    main()
