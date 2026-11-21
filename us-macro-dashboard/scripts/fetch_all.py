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
                        DERIVED_INDICATORS, TOPIC_RULES, INDICATOR_META,
                        SCALED_INDICATORS, DIFFUSION_INDUSTRIES, SUPERCORE_WEIGHTS)
from fetcher import (FredClient, BlsClient, BeaClient, CensusClient,
                     load_cache, save_cache, which_indicators_due,
                     cache_path, fetch_zillow_zori)

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


def apply_scale(ind, series):
    """按 INDICATOR_META 的 scale 缩放序列值（如首申失业金"人"→"千人"除以 1000）。
    在抓取后立即调用，保证 series.json / latest.json / 图表全部统一为显示单位。
    未在 SCALED_INDICATORS 中的指标原样返回。"""
    scale = SCALED_INDICATORS.get(ind)
    if not scale or scale == 1:
        return series
    out = []
    for p in series:
        v = p["value"]
        out.append({"date": p["date"], "value": (v * scale) if v is not None else None})
    return out


def diffusion_series(all_series, industries=None, smooth=3):
    """就业扩散指数：环比上升的行业占比（%，参考 ISM PMI 的扩散指数构造法）。

    对每个行业取月环比差分，上升（>0）计 1，统计当月上升行业数占行业总数的百分比。
    返回 [{date, value}]（value 为 0~100 的百分比），并可选 smooth 月移动平均平滑。
    """
    industries = industries or DIFFUSION_INDUSTRIES
    # 各行业 -> {date: value}
    maps = []
    for ind in industries:
        s = all_series.get(ind, [])
        m = {p["date"]: p["value"] for p in s if p["value"] is not None}
        if m:
            maps.append(m)
    if len(maps) < 4:
        return []
    # 全部日期并集（按月）
    all_dates = set()
    for m in maps:
        all_dates.update(m.keys())
    dates = sorted(d for d in all_dates if d.endswith("-01"))
    out = []
    for i, d in enumerate(dates):
        if i == 0:
            continue
        prev = dates[i - 1]
        up = 0
        valid = 0
        for m in maps:
            cur, pv = m.get(d), m.get(prev)
            if cur is not None and pv is not None and pv != 0:
                valid += 1
                if cur > pv:
                    up += 1
        if valid == 0:
            continue
        out.append({"date": d, "value": round(up / valid * 100, 1)})
    # 平滑（3 个月移动平均）
    if smooth and smooth > 1 and len(out) >= smooth:
        sm = []
        for i in range(len(out)):
            window = out[max(0, i - smooth + 1):i + 1]
            sm.append({"date": out[i]["date"],
                       "value": round(sum(x["value"] for x in window) / len(window), 1)})
        out = sm
    return out


def sum_series(all_series, inds):
    """多个指标按日期对齐求和（用于工业部门就业 = 制造 + 建筑 + 采矿）。"""
    maps = []
    for ind in inds:
        s = all_series.get(ind, [])
        m = {p["date"]: p["value"] for p in s if p["value"] is not None}
        if m:
            maps.append(m)
    if not maps:
        return []
    dates = sorted(set().union(*[set(m.keys()) for m in maps]))
    out = []
    for d in dates:
        total = 0
        ok = True
        for m in maps:
            v = m.get(d)
            if v is None:
                ok = False
                break
            total += v
        if ok:
            out.append({"date": d, "value": total})
    return out


def sahm_rule_series(unrate_series):
    """从失业率 U3 序列计算 Sahm Rule（萨姆规则）完整历史序列。

    Sahm Rule：失业率的 3 个月移动平均，比过去 12 个月里该 3 个月移动平均的
    最低值高出 >= 0.50 个百分点时，标志经济进入衰退（实时版本）。
    返回 [{date, value}]，value 为当前 3MMA 减 12 个月最低 3MMA（百分点）。
    """
    pts = [(p["date"], p["value"]) for p in unrate_series if p["value"] is not None]
    pts.sort(key=lambda x: x[0])
    if len(pts) < 15:  # 需要至少 12 个月历史才能算
        return []
    # 逐点计算 3 个月移动平均
    dates = [d for d, _ in pts]
    vals = [v for _, v in pts]
    ma3_vals = [None] * len(vals)
    for i in range(len(vals)):
        if i >= 2:
            ma3_vals[i] = sum(vals[i-2:i+1]) / 3
    # 对每个点，取过去 12 个月（含当前）里 3MMA 的最低值
    out = []
    for i in range(len(pts)):
        if ma3_vals[i] is None:
            continue
        # 过去 12 个月的窗口：从 i-11 到 i
        window = [v for v in ma3_vals[max(0, i-11):i+1] if v is not None]
        if not window:
            continue
        min_12m = min(window)
        sahm = round(ma3_vals[i] - min_12m, 2)
        out.append({"date": dates[i], "value": sahm})
    return out


# ---------------------------------------------------------------------------
# 非农新增的修订序列重建（用 ALFRED 实时数据库）
# 非农发布后 BLS 会回溯修正前两个月。本函数抓取每个发布日（vintage）的存量快照，
# 重建每月"非农新增"的 初值 → 1次修正 → 2次修正（最终） 轨迹。
# ---------------------------------------------------------------------------
def build_payrolls_revisions(fred, years_back=3):
    """返回 {months, latest_mom, initial_mom, rev1_mom, rev2_mom}，均按时间升序。
    latest_mom   = 最新修订后的非农新增（实线，主序列）
    initial_mom  = 首次发布时的非农新增（虚线，调整前）
    rev1_mom     = 第一次修正后的非农新增（虚线）
    rev2_mom     = 第二次修正后的非农新增（虚线，最终）
    """
    start_year = THIS_YEAR - years_back
    rt_start = f"{start_year}-01-01"
    # 1. 所有 vintage 日期（每个非农发布日一个）
    try:
        vintages = fred.series_vintagedates("PAYEMS", realtime_start=rt_start,
                                            realtime_end=TODAY.isoformat())
    except Exception as e:
        log(f"  非农修订：获取 vintage 日期失败({e})")
        return None
    if not vintages:
        return None

    # 2. 每个 vintage 抓一份存量快照（取最近 months_per_vintage 个月，足够算差分）
    # 为对齐首尾月份，抓 observation_start 提前一个月
    obs_start = f"{start_year - 1}-01-01"
    snapshots = {}  # vintage_date -> {month: level}
    for v in vintages:
        try:
            obs = fred.series_observations_vintage(
                "PAYEMS", realtime_start=v, realtime_end=v,
                observation_start=obs_start, observation_end=TODAY.isoformat())
            snap = {o["date"]: o["value"] for o in obs if o["value"] is not None}
            if snap:
                snapshots[v] = snap
        except Exception as e:
            log(f"  非农修订：vintage {v} 抓取失败({e})")
    if not snapshots:
        return None

    # 3. 重建每个月的修订轨迹
    # 按月收集所有月的集合（用最新的 vintage 快照确定完整月份列表）
    latest_v = max(snapshots.keys())
    months = sorted(k for k in snapshots[latest_v].keys() if k.endswith("-01"))
    # 每月非农新增（差分）在不同 vintage 下的值
    # month -> {vintage: mom}
    mom_by_month = {}
    for v in sorted(snapshots.keys()):
        snap = snapshots[v]
        ms = sorted(k for k in snap.keys() if k.endswith("-01"))
        for i in range(1, len(ms)):
            cur, prev = ms[i], ms[i - 1]
            if snap[cur] is not None and snap[prev] is not None:
                mom = snap[cur] - snap[prev]
                mom_by_month.setdefault(cur, {})[v] = mom

    # 4. 组装输出序列
    out_months = [m for m in months if m in mom_by_month]
    latest_mom, initial_mom, rev1_mom, rev2_mom = [], [], [], []
    for m in out_months:
        vmap = mom_by_month[m]
        vs = sorted(vmap.keys())
        # 最新值 = 最新 vintage 下的差分
        latest_mom.append(round(vmap[vs[-1]], 1))
        # 初值 = 首次出现该月的 vintage（第一个能算出差分的 vintage）
        initial_mom.append(round(vmap[vs[0]], 1))
        # 1次修正 = 第二个 vintage（若存在）
        rev1_mom.append(round(vmap[vs[1]], 1) if len(vs) >= 2 else None)
        # 2次修正 = 第三个 vintage（若存在）
        rev2_mom.append(round(vmap[vs[2]], 1) if len(vs) >= 3 else None)

    return {
        "months": [m[:7] for m in out_months],
        "latest_mom": latest_mom,
        "initial_mom": initial_mom,
        "rev1_mom": rev1_mom,
        "rev2_mom": rev2_mom,
    }


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
            obs = apply_scale(ind, obs)   # 单位归一化（大数转"千/十亿"）
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

    # 3.5 抓取 Zillow ZORI（新增租约租金领先指标，非 FRED/BLS，走 Zillow 公开 CSV）
    # 全量模式与增量模式都抓（数据源小、且 ZORI 每月更新滞后约 2 周）
    try:
        zori = fetch_zillow_zori("United States")
        if zori:
            all_series["zori"] = zori
            save_cache("zori", zori)
            log(f"  Zillow ZORI: {len(zori)} 点, 最新 {zori[-1]['date'] if zori else 'N/A'}")
        else:
            log("  Zillow ZORI 抓取为空")
    except Exception as e:
        cached = load_cache("zori")
        if cached:
            all_series["zori"] = cached
            log(f"  Zillow ZORI 抓取失败({e})，用缓存 {len(cached)} 点")
        else:
            log(f"  Zillow ZORI 抓取失败且无缓存: {e}")

    # 3.5 超级核心通胀（supercore = 核心服务剔除住房）
    # 用 BLS 相对重要性加权求差：supercore = (W_S×核心服务 − W_H×住房)/(W_S−W_H)
    # 两个分项基期同为 1982-1984=100，故加权结果仍是同基期指数，可直接算同比/环比。
    sasle = all_series.get("core_services_cpi", [])
    shelter = all_series.get("cpi_shelter", [])
    w_s = SUPERCORE_WEIGHTS["services_less_energy"]
    w_h = SUPERCORE_WEIGHTS["shelter"]
    net_w = w_s - w_h
    if sasle and shelter and net_w > 0:
        smap = {p["date"]: p["value"] for p in sasle if p["value"] is not None}
        hmap = {p["date"]: p["value"] for p in shelter if p["value"] is not None}
        sup_pts = [{"date": d, "value": round((w_s * smap[d] - w_h * hmap[d]) / net_w, 3)}
                   for d in sorted(set(smap) & set(hmap))]
        if sup_pts:
            all_series["cpi_supercore"] = sup_pts
            log(f"  派生 cpi_supercore（核心服务剔住房）: {len(sup_pts)} 点, 最新 {sup_pts[-1]['date']}")
    else:
        log("  跳过 cpi_supercore：core_services_cpi 或 cpi_shelter 缺失")

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
                     ("cpi_core", "core_cpi_yoy"), ("pce_core", "core_pce_yoy"),
                     ("core_goods_cpi", "core_goods_yoy"),
                     ("core_services_cpi", "core_services_yoy"),
                     ("cpi_supercore", "cpi_supercore_yoy"),
                     ("cpi_rent", "cpi_rent_yoy"),
                     ("zori", "zori_yoy")]:
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

    # Sahm Rule（萨姆规则）：失业率 3MMA 高出过去 12 个月最低 3MMA 的幅度
    unrate_series = all_series.get("unrate", [])
    if unrate_series:
        sahm_series = sahm_rule_series(unrate_series)
        if sahm_series:
            latest_sahm = sahm_series[-1]
            derived["sahm_rule"] = {
                "value": latest_sahm["value"],
                "date": latest_sahm["date"],
                "note": f"失业率 3MMA 高出过去 12 个月最低 3MMA {latest_sahm['value']:.2f}pp（阈值 0.50pp）",
            }
            # 把 Sahm Rule 完整历史序列也存入 all_series，供图表展示
            all_series["sahm_rule"] = sahm_series

    # 就业扩散指数（环比上升行业占比，参考 PMI 构造）
    diff = diffusion_series(all_series)
    if diff:
        all_series["emp_diffusion"] = diff
        derived["emp_diffusion"] = {"value": diff[-1]["value"], "date": diff[-1]["date"],
                                    "note": f"{len(DIFFUSION_INDUSTRIES)} 个主要行业中环比上升的占比（3MMA）"}
    # 工业部门就业 = 制造业 + 建筑业 + 采矿业（周期敏感行业之一）
    goods_emp = sum_series(all_series, ["manemp", "uscons", "usmine"])
    if goods_emp:
        all_series["goods_emp"] = goods_emp

    log(f"  派生指标 {len(derived)} 个: {list(derived.keys())}")

    # 5. 汇总最新值快照
    # 对"指数型"通胀指标，latest 里存同比 %（而非指数水平），便于渲染直接展示
    YOY_OVERRIDE = {
        "cpi": "cpi_yoy", "cpi_core": "core_cpi_yoy",
        "pcepi": "pce_yoy", "pce_core": "core_pce_yoy", "cpi_median": None,
        "core_goods_cpi": "core_goods_yoy", "core_services_cpi": "core_services_yoy",
        "cpi_rent": "cpi_rent_yoy", "zori": "zori_yoy",
    }
    latest = {}
    # 派生序列（仅供图表/专题使用，不作为独立指标卡展示）
    DERIVED_SERIES_SKIP = {"sahm_rule", "emp_diffusion", "goods_emp"}
    for ind, series in all_series.items():
        if ind in DERIVED_SERIES_SKIP:
            continue
        meta = FRED_META.get(ind)
        label, cat = meta if isinstance(meta, tuple) else (ind, "其他")
        lv = latest_value(series)
        if not lv:
            continue
        # 元数据（来源 / 单位）：来自 INDICATOR_META
        im = INDICATOR_META.get(ind, {})
        source = im.get("source", "")
        unit = im.get("unit", "")
        # 指数型指标用同比替代
        if ind in YOY_OVERRIDE and YOY_OVERRIDE[ind] and YOY_OVERRIDE[ind] in derived:
            d = derived[YOY_OVERRIDE[ind]]
            latest[ind] = {
                "label": label, "category": cat,
                "value": d["value"], "date": d["date"],
                "unit": "%", "source": source, "freq": RELEASE_CALENDAR.get(ind, ("FRED", "daily"))[1],
            }
        else:
            latest[ind] = {
                "label": label, "category": cat,
                "value": lv["value"], "date": lv["date"],
                "unit": unit, "source": source, "freq": RELEASE_CALENDAR.get(ind, ("FRED", "daily"))[1],
            }

    # 6. 写入结果
    with open(os.path.join(DATA_DIR, "series.json"), "w", encoding="utf-8") as f:
        json.dump(all_series, f, ensure_ascii=False)
    with open(os.path.join(DATA_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"updated": TODAY.isoformat(), "latest": latest, "derived": derived},
                  f, ensure_ascii=False, indent=2)

    log(f"完成。series.json 与 latest.json 已更新，最新值 {len(latest)} 个指标")

    # 7. 非农新增修订序列（ALFRED 实时数据库，单独文件）
    log("抓取非农新增的历史修订序列（ALFRED）...")
    try:
        rev = build_payrolls_revisions(fred)
        if rev:
            rev_path = os.path.join(DATA_DIR, "payrolls_revisions.json")
            with open(rev_path, "w", encoding="utf-8") as f:
                json.dump(rev, f, ensure_ascii=False)
            n = len(rev["months"])
            log(f"  非农修订序列 {n} 个月，最新 {rev['months'][-1] if n else 'N/A'}")
        else:
            log("  非农修订序列重建失败（无数据）")
    except Exception as e:
        log(f"  非农修订序列抓取异常：{e}")


if __name__ == "__main__":
    main()
