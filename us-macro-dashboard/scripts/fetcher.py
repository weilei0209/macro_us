#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美国宏观数据看板 - 数据拉取层
四个官方 API 客户端 + 本地缓存 + 发布日历驱动的精准增量更新。
"""
import os, json, time, datetime, urllib.request, urllib.parse, csv, io

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# 环境变量读取 API key
def _key(name):
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"环境变量 {name} 未设置")
    return v

def _http_json(url, timeout=30, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

# ---------------------------------------------------------------------------
# 缓存工具
# ---------------------------------------------------------------------------
def cache_path(name):
    return os.path.join(CACHE_DIR, f"{name}.json")

def load_cache(name):
    p = cache_path(name)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_cache(name, obj):
    with open(cache_path(name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)

# ---------------------------------------------------------------------------
# 一、FRED 客户端
# ---------------------------------------------------------------------------
class FredClient:
    BASE = "https://api.stlouisfed.org/fred"
    def __init__(self):
        self.key = _key("FRED_API_KEY")

    def _get(self, path, params):
        params = dict(params)
        params["api_key"] = self.key
        params["file_type"] = "json"
        url = f"{self.BASE}/{path}?{urllib.parse.urlencode(params)}"
        return _http_json(url)

    def series_observations(self, series_id, limit=None, desc=True):
        """拉取序列观测值，返回正序（旧→新）[{date, value}]，value 为 float 或 None（. 缺失）。"""
        params = {"series_id": series_id}
        if desc:
            params["sort_order"] = "desc"
        if limit:
            params["limit"] = str(limit)
        d = self._get("series/observations", params)
        out = []
        for o in d.get("observations", []):
            v = o.get("value")
            try:
                v = float(v) if v not in (".", "", None) else None
            except ValueError:
                v = None
            out.append({"date": o.get("date"), "value": v})
        # sort_order=desc 返回从新到旧，统一转成正序（旧→新）
        if desc:
            out.reverse()
        return out

    def series_info(self, series_id):
        d = self._get("series", {"series_id": series_id})
        s = d.get("seriess", [{}])
        return s[0] if s else {}

    # ---- ALFRED（实时/历史修订数据库）----
    # 通过 realtime_start/realtime_end 指定"vintage"（数据在某个时点看到的版本），
    # 用于抓取指标的历史修订快照（如非农每月发布时的初值）。
    def series_vintagedates(self, series_id, realtime_start=None, realtime_end=None):
        """列出某序列在指定时间范围内的所有 vintage 日期（发布/修订日期）。"""
        params = {"series_id": series_id}
        if realtime_start:
            params["realtime_start"] = realtime_start
        if realtime_end:
            params["realtime_end"] = realtime_end
        d = self._get("series/vintagedates", params)
        return d.get("vintage_dates", [])

    def series_observations_vintage(self, series_id, realtime_start=None, realtime_end=None,
                                    observation_start=None, observation_end=None):
        """按 vintage 抓取序列观测值（正序 [{date, value}]）。
        realtime_start/end 相同 = 该时点看到的版本（单次快照）。"""
        params = {"series_id": series_id, "sort_order": "asc"}
        if realtime_start:
            params["realtime_start"] = realtime_start
        if realtime_end:
            params["realtime_end"] = realtime_end
        if observation_start:
            params["observation_start"] = observation_start
        if observation_end:
            params["observation_end"] = observation_end
        d = self._get("series/observations", params)
        out = []
        for o in d.get("observations", []):
            v = o.get("value")
            try:
                v = float(v) if v not in (".", "", None) else None
            except ValueError:
                v = None
            out.append({"date": o.get("date"), "value": v})
        return out


# ---------------------------------------------------------------------------
# 二、BLS 客户端（v2 API）
# ---------------------------------------------------------------------------
class BlsClient:
    URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    def __init__(self):
        self.key = _key("BLS_API_KEY")

    def fetch(self, series_ids, start_year, end_year):
        """拉取多个系列，返回 {series_id: [{year, period, periodName, value}]}。"""
        body = json.dumps({
            "seriesid": list(series_ids),
            "startyear": str(start_year),
            "endyear": str(end_year),
            "registrationkey": self.key,
        }).encode("utf-8")
        d = _http_json(self.URL, data=body, headers={"Content-Type": "application/json"})
        if d.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS 错误: {d.get('message')}")
        out = {}
        for s in d.get("Results", {}).get("series", []):
            out[s["seriesID"]] = s.get("data", [])
        return out


# ---------------------------------------------------------------------------
# 三、BEA 客户端
# ---------------------------------------------------------------------------
class BeaClient:
    URL = "https://apps.bea.gov/api/data"
    def __init__(self):
        self.key = _key("BEA_API_KEY")

    def get_data(self, dataset="NIPA", table=None, frequency="Q", year=None):
        params = {
            "UserID": self.key, "method": "GetData", "DataSetName": dataset,
            "TableName": table, "Frequency": frequency,
            "Year": str(year), "ResultFormat": "JSON",
        }
        url = f"{self.URL}?{urllib.parse.urlencode(params)}"
        d = _http_json(url, timeout=40)
        res = d.get("BEAAPI", {}).get("Results", {})
        if isinstance(res, dict):
            # 单个结果
            data = res.get("Data", [])
        else:
            data = res[0].get("Data", []) if res else []
        return data


# ---------------------------------------------------------------------------
# 四、Census 客户端
# ---------------------------------------------------------------------------
class CensusClient:
    URL = "https://api.census.gov/data"
    def __init__(self):
        self.key = _key("CENSUS_API_KEY")

    def get(self, dataset, get_vars, predicates=None):
        params = {"get": ",".join(get_vars), "key": self.key}
        if predicates:
            params.update(predicates)
        url = f"{self.URL}/{dataset}?{urllib.parse.urlencode(params)}"
        return _http_json(url, timeout=40)


# ---------------------------------------------------------------------------
# 五、Zillow ZORI 抓取（新增租约租金的领先指标）
# ---------------------------------------------------------------------------
ZORI_URL = "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfrcondomfr_sm_sa_month.csv"

def fetch_zillow_zori(region_name="United States"):
    """从 Zillow 公开数据下载 ZORI（Zillow Observed Rent Index，观测挂牌租金，季调），
    返回美国全国月度序列 [{date, value}]（value 为美元/月，smoothed + seasonally adjusted）。
    ZORI 是新挂牌房源的挂牌租金，领先 CPI 租金（含续约）约 12 个月。"""
    req = urllib.request.Request(ZORI_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read().decode("utf-8")
    rows = list(csv.reader(io.StringIO(data)))
    if not rows:
        return []
    header = rows[0]
    # 找目标地区行（RegionName 在第 3 列，索引 2）
    for row in rows[1:]:
        if len(row) > 2 and row[2].strip() == region_name:
            out = []
            for h, v in zip(header, row):
                if not h.startswith("20") or not v:
                    continue
                try:
                    val = float(v)
                except (ValueError, TypeError):
                    continue
                # 日期 "2015-01-31" -> "2015-01-01"（与 FRED 月频对齐）
                date = h[:7] + "-01"
                out.append({"date": date, "value": val})
            return out
    return []


# ---------------------------------------------------------------------------
# 五-补、纽约联储 ACM 期限溢价（Adrian-Crump-Moench）
# ACM 不在 FRED 上，纽约联储只发布一个 .xls 工作簿（OLE2/BIFF8），
# 故用 scripts/xls_lite.py（纯标准库）解析，不引入 pandas / xlrd。
# 工作簿结构："ACM Daily" 表，列 DATE / ACMY01-10（拟合收益率）/
#            ACMTP01-10（期限溢价）/ ACMRNY01-10（风险中性预期路径），单位均为 %。
# 恒等式：拟合收益率 Y = 预期路径 RN + 期限溢价 TP。数据日频，滞后约 1 个工作日。
# ---------------------------------------------------------------------------
ACM_URL = "https://www.newyorkfed.org/medialibrary/media/research/data_indicators/ACMTermPremium.xls"
ACM_START = "1990-01-01"     # 只保留 1990 年后，控制 series.json 体积（图表从 2000 起）
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def parse_acm_date(s):
    """'19-Nov-2026' -> '2026-11-19'。不用 strptime('%b')，避免受系统 locale 影响。"""
    try:
        d, mon, y = str(s).split("-")
        return f"{int(y):04d}-{_MONTHS[mon]:02d}-{int(d):02d}"
    except Exception:
        return None


def fetch_acm_term_premium():
    """下载并解析纽约联储 ACM 期限溢价工作簿，返回 10 年期三件套：
      acm_tp10 期限溢价 / acm_rn10 风险中性预期路径 / acm_y10 拟合 10Y 收益率（均 %，日频）
    解析失败时抛异常，由调用方回退到缓存。"""
    from xls_lite import read_sheet

    req = urllib.request.Request(ACM_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        blob = r.read()
    if not blob or len(blob) < 100000:
        raise RuntimeError(f"ACM 工作簿下载异常，仅 {len(blob)} 字节")
    # 原始工作簿留档，便于出问题时不重复下载（约 10MB，data/ 已 gitignore）
    raw_path = os.path.join(CACHE_DIR, "ACMTermPremium.xls")
    with open(raw_path, "wb") as f:
        f.write(blob)

    rows = read_sheet(raw_path, "ACM Daily")
    if not rows:
        raise RuntimeError("ACM Daily 表为空")
    head = [str(x).strip().upper() if x is not None else "" for x in rows[0]]
    try:
        i_date, i_y, i_tp, i_rn = (head.index("DATE"), head.index("ACMY10"),
                                   head.index("ACMTP10"), head.index("ACMRNY10"))
    except ValueError:
        raise RuntimeError(f"ACM 表头不符合预期：{head[:12]}")

    out = {"acm_tp10": [], "acm_rn10": [], "acm_y10": []}
    for row in rows[1:]:
        if len(row) <= max(i_date, i_y, i_tp, i_rn):
            continue
        date = parse_acm_date(row[i_date])
        if not date or date < ACM_START:
            continue
        vals = {}
        for key, idx in (("acm_y10", i_y), ("acm_tp10", i_tp), ("acm_rn10", i_rn)):
            v = row[idx]
            if isinstance(v, (int, float)):
                vals[key] = round(float(v), 4)
        if len(vals) == 3:
            for key, v in vals.items():
                out[key].append({"date": date, "value": v})
    if not out["acm_tp10"]:
        raise RuntimeError("ACM 解析结果为空")
    return out


# ---------------------------------------------------------------------------
# 五之二、美债拍卖明细（财政部 Fiscal Data）→ 月度 bills / coupon 净发行
# ---------------------------------------------------------------------------
AUCTIONS_URL = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
                "/v1/accounting/od/auctions_query")
AUCTION_FIELDS = ("cusip,security_type,security_term,offering_amt,reopening,"
                  "issue_date,maturity_date,original_security_term")
AUCTION_START = "1979-11"


def _num(v):
    """Fiscal Data 用字符串 "null" 表示缺失。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fetch_treasury_auctions():
    """全量拍卖明细（1979 至今约 1.1 万条，2 页）。

    字段精简到 7 个，单页约 3MB；账单类（bills）周频拍卖占大头，但这是唯一能同时
    拿到 offering_amt（公开市场发行额，不含 SOMA 增发）和 maturity_date（到期日）的源，
    没有到期日就算不出净发行。
    """
    out, page = [], 1
    while True:
        q = urllib.parse.urlencode({
            "fields": AUCTION_FIELDS,
            "sort": "issue_date",
            "page[size]": 10000,
            "page[number]": page,
        })
        data = _http_json(f"{AUCTIONS_URL}?{q}", timeout=180)
        rows = data.get("data") or []
        out.extend(rows)
        pages = int((data.get("meta") or {}).get("total-pages") or 1)
        if page >= pages or not rows:
            break
        page += 1
        time.sleep(0.5)
    if len(out) < 5000:
        raise RuntimeError(f"拍卖明细仅取到 {len(out)} 条，疑似接口异常")
    return out


def fetch_treasury_net_issuance(today=None):
    """按月汇总 bills / coupon 的净发行（发行 − 到期），单位十亿美元。

    口径要点：
    - 金额取 offering_amt，即公开市场发行额；SOMA 增发（Fed 在拍卖里的 add-on）不在其中，
      所以"剔除卖给 Fed 的部分"是数据天然带的，不需要再减。
    - 到期侧按 CUSIP 汇总：一只券所有拍卖（原始发行 + 续发 reopen）的发行额加总才是它
      到期要还的本金。这样续发既不会被当成多笔到期，也不会从净发行里漏掉。
    - 只保留本月之前的月份：数据集滞后约 1 个月，当月往往只有到期、没有新发，
      直接算会得到一个巨额负值。

    返回 4 条月频序列（gross / 到期各两条），净发行在渲染层相减，便于 tooltip 展示明细。
    """
    rows = fetch_treasury_auctions()
    today = today or datetime.date.today()
    cur_month = today.strftime("%Y-%m")
    today_s = today.isoformat()

    principal, meta = {}, {}        # cusip -> 累计发行额 / (到期月, 0=bill 1=coupon)
    gross, mat = {}, {}             # 月份 -> [bills, coupon]
    for r in rows:
        issue = (r.get("issue_date") or "")[:10]
        if not issue or issue > today_s:
            continue
        amt = _num(r.get("offering_amt"))
        cusip = r.get("cusip") or issue
        cat = 0 if r.get("security_type") == "Bill" else 1
        principal[cusip] = principal.get(cusip, 0.0) + amt
        meta[cusip] = ((r.get("maturity_date") or "")[:7], cat)
        g = gross.setdefault(issue[:7], [0.0, 0.0])
        g[cat] += amt

    for cusip, amt in principal.items():
        mm, cat = meta.get(cusip, ("", 1))
        if not mm:
            continue
        x = mat.setdefault(mm, [0.0, 0.0])
        x[cat] += amt

    months = sorted(m for m in set(list(gross) + list(mat))
                    if AUCTION_START <= m < cur_month)
    out = {"tbills_gross": [], "tbills_mat": [], "tcoupon_gross": [], "tcoupon_mat": []}
    for m in months:
        g = gross.get(m, [0.0, 0.0])
        x = mat.get(m, [0.0, 0.0])
        d = m + "-01"
        out["tbills_gross"].append({"date": d, "value": round(g[0] / 1e9, 1)})
        out["tbills_mat"].append({"date": d, "value": round(x[0] / 1e9, 1)})
        out["tcoupon_gross"].append({"date": d, "value": round(g[1] / 1e9, 1)})
        out["tcoupon_mat"].append({"date": d, "value": round(x[1] / 1e9, 1)})
    if not out["tbills_gross"]:
        raise RuntimeError("拍卖明细汇总为空")
    return out


# ---------------------------------------------------------------------------
# 五之二、纽约联储收益率曲线模型 → 未来 12 个月衰退概率（月度）
# ---------------------------------------------------------------------------
# 官方页面 https://www.newyorkfed.org/research/capital_markets/ycfaq.html
# 只发布 .xls（OLE2/BIFF8），由 xls_lite 解析；"Monthly data" 即此文件
YCFAQ_URL = ("https://www.newyorkfed.org/medialibrary/media/research/"
             "capital_markets/allmonth.xls")
YCFAQ_START = "1960-01-01"


def fetch_nyfed_recession_prob():
    """纽约联储收益率曲线模型：未来 12 个月衰退概率（月度，%）。

    模型 = Estrella-Mishkin (1996) 的 probit：自变量是 10Y 与 3M 国债的利差
    （3M 按 bond-equivalent basis 折算），被解释变量是未来 12 个月是否进入衰退。
    工作簿 rec_prob 表列：Date（Excel 序列号）/ 10Y / 3M / 3M BEY / Spread / Rec_prob / NBER_Rec。

    坑：表尾有一批日期自动递增、概率由表内公式引用最后有效值算出来的空行
    （2026-11 之后），必须截到最后一个 Spread 非空的月份，否则等于把模型
    "凭空外推"的 12 个月画进图里。
    """
    from xls_lite import read_sheet

    req = urllib.request.Request(YCFAQ_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        blob = r.read()
    if not blob or len(blob) < 20000:
        raise RuntimeError(f"收益率曲线工作簿下载异常，仅 {len(blob)} 字节")
    raw_path = os.path.join(CACHE_DIR, "ycfaq_allmonth.xls")
    with open(raw_path, "wb") as f:
        f.write(blob)

    rows = read_sheet(raw_path, "rec_prob")
    if not rows:
        raise RuntimeError("rec_prob 表为空")
    head = [str(x).strip().upper() if x is not None else "" for x in rows[0]]
    try:
        i_date = head.index("DATE")
        i_spread = head.index("SPREAD")
        i_prob = head.index("REC_PROB")
    except ValueError:
        raise RuntimeError(f"rec_prob 表头不符合预期：{head}")

    out = []
    # Excel 1900 日期系统（含 1900 闰年 bug，故基准取 1899-12-30）
    base = datetime.date(1899, 12, 30)
    for row in rows[1:]:
        if len(row) <= max(i_date, i_spread, i_prob):
            continue
        serial, spread, prob = row[i_date], row[i_spread], row[i_prob]
        if not isinstance(serial, (int, float)):
            continue
        if not isinstance(spread, (int, float)) or spread is None:
            continue          # 表尾公式行：没有当月的利差，概率是外推值
        if not isinstance(prob, (int, float)):
            continue
        date = (base + datetime.timedelta(days=int(serial))).isoformat()
        if date < YCFAQ_START:
            continue
        out.append({"date": date, "value": round(float(prob) * 100, 2)})
    if not out:
        raise RuntimeError("衰退概率解析结果为空")
    return {"nyfed_rec_prob": out}


# ---------------------------------------------------------------------------
# 六、发布日历判定
# ---------------------------------------------------------------------------
def _nth_weekday(year, month, weekday, nth):
    """返回某月第 nth 个 weekday（0=周一..6=周日）的日期。"""
    d = datetime.date(year, month, 1)
    count = 0
    while d.month == month:
        if d.weekday() == weekday:
            count += 1
            if count == nth:
                return d
        d += datetime.timedelta(days=1)
    return None

def due_today(freq, today=None):
    """判断某频率的指标今天是否该拉取。返回 True/False。"""
    today = today or datetime.date.today()
    wd = today.weekday()  # 0=周一
    if freq == "daily":
        return wd < 5  # 仅工作日
    if freq == "weekly":
        return wd == 3  # 周四
    if freq == "weekly_thu":
        return wd == 3
    if freq == "weekly_fri":
        return wd == 4
    if freq == "monthly_1st_fri":
        return today == _nth_weekday(today.year, today.month, 4, 1)
    if freq == "monthly_mid":
        return 12 <= today.day <= 18
    if freq == "monthly_end":
        return today.day >= 25
    if freq == "monthly_jolts":
        # JOLTS 约在次月上旬公布，宽松判定为每月 5-10 日
        return 5 <= today.day <= 10
    if freq == "quarterly":
        return today.month in (1, 4, 7, 10) and today.day >= 25
    return False


def which_indicators_due(calendar, today=None):
    """根据发布日历，返回今天该拉取的指标名列表。"""
    due = []
    for ind, (api, freq) in calendar.items():
        if due_today(freq, today):
            due.append(ind)
    return due


# ---------------------------------------------------------------------------
# 七、主拉取流程
# ---------------------------------------------------------------------------
def fetch_fred_series(series_ids, client=None):
    client = client or FredClient()
    result = {}
    for sid in series_ids:
        obs = client.series_observations(sid, limit=None)
        result[sid] = obs
    return result


if __name__ == "__main__":
    # 自测：打印今天该拉取的指标
    import sys
    sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
    from indicators import RELEASE_CALENDAR
    due = which_indicators_due(RELEASE_CALENDAR)
    print(f"今天 {datetime.date.today()} 应拉取指标数: {len(due)}")
    for d in due:
        print("  -", d)
