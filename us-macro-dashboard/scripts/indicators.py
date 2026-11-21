#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美国宏观数据看板 - 指标定义与映射
所有指标 ID 定义、发布日历、派生指标规则集中在此，供 fetch / analyze / render 复用。
数据源：FRED / BLS / BEA / Census 四大官方 API。
"""
import os

# ---------------------------------------------------------------------------
# 一、FRED 系列映射（跨机构聚合与派生指标的主来源）
# key: 内部指标名；value: FRED series_id
# ---------------------------------------------------------------------------
FRED_SERIES = {
    # ---- 利率与期限溢价（日频）----
    "us10y":        "DGS10",       # 10年期美债收益率
    "us2y":         "DGS2",        # 2年期美债收益率
    "ffr":          "DFF",         # 联邦基金有效利率（日）
    "sofr":         "SOFR",        # 担保隔夜融资利率
    "t10y2y":       "T10Y2Y",      # 10Y-2Y 利差
    "t10y3m":       "T10Y3M",      # 10Y-3M 利差
    "bei10y":       "T10YIE",      # 10年盈亏平衡通胀率
    "fwd5y5y":      "T5YIFR",      # 5年5年远期通胀补偿（锚定核心指标）
    "tips10y":      "DFII10",      # 10年TIPS实际收益率
    "mortgage30":   "MORTGAGE30US",# 30年固定房贷利率
    "hy_spread":    "BAMLH0A0HYM2",# 高收益债信用利差
    "vix":          "VIXCLS",      # VIX
    "dxy":          "DTWEXBGS",    # 广义美元指数
    # ---- 美联储资产负债表 / 流动性（周频/日频）----
    "fed_assets":   "WALCL",       # 美联储总资产（周）
    "on_rrp":       "RRPONTSYD",   # 隔夜逆回购余额（日）
    "reserves":     "WRESBAL",     # 准备金余额（周）
    "bank_loans":   "TOTLL",       # 银行信贷贷款（周）
    # ---- 就业（月频）----
    "payrolls":     "PAYEMS",      # 非农就业总人数（存量，用于算新增）
    "unrate":       "UNRATE",      # 失业率 U3
    "u6rate":       "U6RATE",      # 广义失业率 U6
    "participation":"CIVPART",     # 劳动参与率
    "labor_force":  "CLF16OV",     # 劳动力总量
    "emratio":      "EMRATIO",     # 就业人口比
    "jolts_open":   "JTSJOL",      # JOLTS 岗位空缺
    "claims":       "ICSA",        # 首申失业金（周）
    # ---- 就业：行业细分（CES，用于扩散指数 / 周期敏感行业）----
    "manemp":       "MANEMP",      # 制造业就业
    "uscons":       "USCONS",      # 建筑业就业
    "usmine":       "USMINE",      # 采矿业就业
    "temphelps":    "TEMPHELPS",   # 临时工服务就业
    "uspbs":        "USPBS",       # 专业与商业服务
    "usehs":        "USEHS",       # 私人教育与医疗
    "ustrade":      "USTRADE",     # 零售贸易
    "uswtrade":     "USWTRADE",    # 批发贸易
    "usfire":       "USFIRE",      # 金融活动
    "usinfo":       "USINFO",      # 信息业
    "uslah":        "USLAH",       # 休闲与酒店
    "usgovt":       "USGOVT",      # 政府
    # ---- 就业：周工时（领先指标）----
    "awhman":       "AWHMAN",      # 制造业周工时（生产与非管理岗）
    "awhaetp":      "AWHAETP",     # 私营部门总周工时
    # ---- 就业：黄金年龄劳动参与率（CPS 25-54）----
    "prime_participation": "LNU01300060",  # 黄金年龄劳动参与率
    # ---- 通胀（月频）----
    "cpi":          "CPIAUCSL",    # CPI 总
    "cpi_core":     "CPILFESL",    # 核心 CPI
    "cpi_median":   "MEDCPIM158SFRBCLE", # 中位 CPI
    "core_goods_cpi":   "CUSR0000SACL1E", # 核心商品 CPI（剔除食品能源商品，季调）
    "core_services_cpi":"CUSR0000SASLE",  # 核心服务 CPI（剔除能源服务，季调）
    "cpi_rent":     "CUSR0000SEHA", # CPI 租金（主要居所租金，季调）
    "cpi_shelter":  "CUSR0000SAH1", # CPI 住房 Shelter（季调）——仅作计算超级核心的中间量
    "pcepi":        "PCEPI",       # PCE 价格指数
    "pce_core":     "PCEPILFE",    # 核心 PCE
    "pce":          "PCE",         # PCE 名义支出
    "pce_real":     "PCEC96",      # 实际 PCE
    "mich_exp":     "MICH",        # 密歇根1年期通胀预期
    "umcsent":      "UMCSENT",     # 密歇根消费者信心
    # ---- 增长（月/季度）----
    "gdp_real":     "GDPC1",       # 实际 GDP（季）
    "gdp_qoq":      "A191RL1Q225SBEA", # 实际 GDP 环比折年
    "gdp_pot":      "GDPPOT",      # 潜在 GDP（季）
    "gdi":          "A261RX1Q020SBEA", # 实际 GDI（季）
    "inv_private":  "GPDI",        # 私人投资（季）
    "retail":       "RRSFS",       # 实际零售销售（月）
    "inv_sales":    "ISRATIO",     # 库存销售比（月）
    "saving_rate":  "PSAVERT",     # 储蓄率（月）
    # ---- 领先指标 ----
    "housing_starts":"HOUST",      # 新屋开工（月）
}

# FRED 系列的中文标签与分类（用于渲染）
FRED_META = {
    "us10y":      ("10年期美债收益率", "利率"),
    "us2y":       ("2年期美债收益率", "利率"),
    "ffr":        ("联邦基金利率", "货币"),
    "sofr":       ("SOFR 隔夜利率", "货币"),
    "t10y2y":     ("10Y-2Y 利差", "利率"),
    "t10y3m":     ("10Y-3M 利差", "利率"),
    "bei10y":     ("10年盈亏平衡通胀率", "通胀预期"),
    "fwd5y5y":    ("5y5y 远期通胀补偿", "通胀预期"),
    "tips10y":    ("10年TIPS实际利率", "利率"),
    "mortgage30": ("30年房贷利率", "地产"),
    "hy_spread":  ("高收益债利差", "金融条件"),
    "vix":        ("VIX", "金融条件"),
    "dxy":        ("广义美元指数", "汇率"),
    "fed_assets": ("美联储总资产", "货币"),
    "on_rrp":     ("隔夜逆回购余额", "货币"),
    "reserves":   ("准备金余额", "货币"),
    "bank_loans": ("商业银行贷款", "金融条件"),
    "payrolls":   ("非农就业总人数", "就业"),
    "unrate":     ("失业率 U3", "就业"),
    "u6rate":     ("广义失业率 U6", "就业"),
    "participation":("劳动参与率", "就业"),
    "labor_force":("劳动力总量", "就业"),
    "emratio":    ("就业人口比", "就业"),
    "jolts_open": ("JOLTS 岗位空缺", "就业"),
    "claims":     ("首申失业金", "就业"),
    "manemp":     ("制造业就业", "就业"),
    "uscons":     ("建筑业就业", "就业"),
    "usmine":     ("采矿业就业", "就业"),
    "temphelps":  ("临时工服务就业", "就业"),
    "uspbs":      ("专业与商业服务", "就业"),
    "usehs":      ("教育与医疗服务", "就业"),
    "ustrade":    ("零售贸易", "就业"),
    "uswtrade":   ("批发贸易", "就业"),
    "usfire":     ("金融活动", "就业"),
    "usinfo":     ("信息业", "就业"),
    "uslah":      ("休闲与酒店", "就业"),
    "usgovt":     ("政府就业", "就业"),
    "awhman":     ("制造业周工时", "就业"),
    "awhaetp":    ("私营部门周工时", "就业"),
    "prime_participation": ("黄金年龄劳动参与率", "就业"),
    "cpi":        ("CPI 同比", "通胀"),
    "cpi_core":   ("核心 CPI 同比", "通胀"),
    "cpi_median": ("中位 CPI 同比", "通胀"),
    "core_goods_cpi":   ("核心商品 CPI 同比", "通胀"),
    "core_services_cpi":("核心服务 CPI 同比", "通胀"),
    "cpi_rent":     ("CPI 租金同比", "通胀"),
    "zori":         ("ZORI 新租约租金同比", "通胀"),
    "pcepi":      ("PCE 同比", "通胀"),
    "pce_core":   ("核心 PCE 同比", "通胀"),
    "pce":        ("PCE 名义支出", "增长"),
    "pce_real":   ("实际 PCE", "增长"),
    "mich_exp":   ("密歇根1年期通胀预期", "通胀预期"),
    "umcsent":    ("密歇根消费者信心", "领先"),
    "gdp_real":   ("实际 GDP", "增长"),
    "gdp_qoq":    ("实际 GDP 环比折年", "增长"),
    "gdp_pot":    ("潜在 GDP", "增长"),
    "gdi":        ("实际 GDI", "增长"),
    "inv_private":("私人投资", "增长"),
    "retail":     ("实际零售销售", "消费"),
    "inv_sales":  ("库存销售比", "领先"),
    "saving_rate":("储蓄率", "消费"),
    "housing_starts":("新屋开工", "地产"),
}

# ---------------------------------------------------------------------------
# 二、BLS 系列映射（就业 + 通胀的官方硬数据）
# BLS v2 API，单次最多 50 系列；series id 见 BLS 官方目录
# ---------------------------------------------------------------------------
BLS_SERIES = {
    "payrolls_bls":      "CES0000000001",  # 非农总就业（可与 FRED PAYEMS 互证）
    "ahe":               "CES0500000003",  # 平均时薪（私营非农）
    "avg_weekly_hours":  "CES0500000002",  # 平均周工时（私营非农）
    "cpi_bls":           "CUUR0000SA0",    # CPI-U 未季调
    "cpi_sa":            "CUSR0000SA0",    # CPI-U 季调
    "cpi_core_bls":      "CUUR0000SA0L1E", # 核心 CPI-U
    "cpi_supercore":     "CUUR0000SA0L12E",# 核心服务（住房+医疗等，近似超级核心）
    "cpi_shelter":       "CUUR0000SAH",    # 住房（shelter）
    "cpi_energy":        "CUUR0000SA0E",   # 能源
    "cpi_food":          "CUUR0000SA0L1",  # 食品
    "eci_wages":         "CIS2020000000000I", # 雇佣成本指数-工资（季度）
    "unrate_bls":        "LNS14000000",    # 失业率 U3
    "u6_bls":            "LNS13327709",    # U6
    "participation_bls": "LNS11300000",    # 劳动参与率
    "emratio_bls":       "LNS12300000",    # 就业人口比
}

# ---------------------------------------------------------------------------
# 三、BEA 数据集映射（国民账户：GDP / PCE / GDI 详细分项）
# method=GetData, DataSetName=NIPA, TableName 见 BEA 文档
# ---------------------------------------------------------------------------
BEA_TABLES = {
    "gdp_nominal":      {"table": "T10101", "desc": "名义 GDP"},          # 需验证
    "gdp_real":         {"table": "T10106", "desc": "实际 GDP"},          # 需验证
    "pce_price":        {"table": "T20804", "desc": "PCE 价格指数"},       # 需验证
    "gdi":              {"table": "T10706", "desc": "GDI"},               # 需验证
}

# ---------------------------------------------------------------------------
# 四、Census 数据集映射（零售 / 地产 / 贸易）
# ---------------------------------------------------------------------------
CENSUS_DATASETS = {
    "retail":   {"ds": "timeseries/eits/marts",  "desc": "月度零售贸易"},
    "housing":  {"ds": "timeseries/eits/ressales","desc": "新屋销售"},
}

# ---------------------------------------------------------------------------
# 五、发布日历（精准增量更新的核心）
# 每个条目：指标 -> (API, 频率, 相对发布日期规则)
# 规则用自然月/周描述，脚本据此判断"今天是否该拉这个指标"
# ---------------------------------------------------------------------------
# 频率类型：daily=每个工作日, weekly=每周, monthly=每月, quarterly=每季, event=事件驱动
RELEASE_CALENDAR = {
    # ---- 日频市场指标（FRED，配额宽松，每个工作日更新）----
    "us10y":        ("FRED", "daily"),
    "us2y":         ("FRED", "daily"),
    "ffr":          ("FRED", "daily"),
    "sofr":         ("FRED", "daily"),
    "t10y2y":       ("FRED", "daily"),
    "t10y3m":       ("FRED", "daily"),
    "bei10y":       ("FRED", "daily"),
    "fwd5y5y":      ("FRED", "daily"),
    "tips10y":      ("FRED", "daily"),
    "hy_spread":    ("FRED", "daily"),
    "vix":          ("FRED", "daily"),
    "dxy":          ("FRED", "daily"),
    "on_rrp":       ("FRED", "daily"),
    # ---- 周频指标（每周四首申，周五资产负债表）----
    "claims":       ("FRED", "weekly_thu"),
    "fed_assets":   ("FRED", "weekly_fri"),
    "reserves":     ("FRED", "weekly_fri"),
    "bank_loans":   ("FRED", "weekly_fri"),
    "mortgage30":   ("FRED", "weekly"),
    # ---- 月频就业（首周周五非农，月中 JOLTS 略滞后）----
    "payrolls":     ("FRED", "monthly_1st_fri"),
    "unrate":       ("FRED", "monthly_1st_fri"),
    "u6rate":       ("FRED", "monthly_1st_fri"),
    "participation":("FRED", "monthly_1st_fri"),
    "labor_force":  ("FRED", "monthly_1st_fri"),
    "emratio":      ("FRED", "monthly_1st_fri"),
    "ahe":          ("BLS",  "monthly_1st_fri"),
    "avg_weekly_hours":("BLS","monthly_1st_fri"),
    "jolts_open":   ("FRED", "monthly_jolts"),
    # ---- 就业行业细分 / 周工时 / 黄金年龄参与率（随非农报告发布）----
    "manemp":       ("FRED", "monthly_1st_fri"),
    "uscons":       ("FRED", "monthly_1st_fri"),
    "usmine":       ("FRED", "monthly_1st_fri"),
    "temphelps":    ("FRED", "monthly_1st_fri"),
    "uspbs":        ("FRED", "monthly_1st_fri"),
    "usehs":        ("FRED", "monthly_1st_fri"),
    "ustrade":      ("FRED", "monthly_1st_fri"),
    "uswtrade":     ("FRED", "monthly_1st_fri"),
    "usfire":       ("FRED", "monthly_1st_fri"),
    "usinfo":       ("FRED", "monthly_1st_fri"),
    "uslah":        ("FRED", "monthly_1st_fri"),
    "usgovt":       ("FRED", "monthly_1st_fri"),
    "awhman":       ("FRED", "monthly_1st_fri"),
    "awhaetp":      ("FRED", "monthly_1st_fri"),
    "prime_participation": ("FRED", "monthly_1st_fri"),
    # ---- 月频通胀（月中 CPI，月末 PCE）----
    "cpi":          ("FRED", "monthly_mid"),
    "cpi_core":     ("FRED", "monthly_mid"),
    "cpi_median":   ("FRED", "monthly_mid"),
    "core_goods_cpi":   ("FRED", "monthly_mid"),
    "core_services_cpi":("FRED", "monthly_mid"),
    "cpi_rent":     ("FRED", "monthly_mid"),
    "cpi_shelter":  ("FRED", "monthly_mid"),
    "zori":         ("Zillow", "monthly_mid"),
    "cpi_bls":      ("BLS",  "monthly_mid"),
    "cpi_sa":       ("BLS",  "monthly_mid"),
    "cpi_core_bls": ("BLS",  "monthly_mid"),
    "cpi_supercore":("BLS",  "monthly_mid"),
    "cpi_shelter":  ("BLS",  "monthly_mid"),
    "cpi_energy":   ("BLS",  "monthly_mid"),
    "cpi_food":     ("BLS",  "monthly_mid"),
    "pcepi":        ("FRED", "monthly_end"),
    "pce_core":     ("FRED", "monthly_end"),
    "pce":          ("FRED", "monthly_end"),
    "pce_real":     ("FRED", "monthly_end"),
    "mich_exp":     ("FRED", "monthly_mid"),
    "umcsent":      ("FRED", "monthly_mid"),
    # ---- 月频消费/领先 ----
    "retail":       ("FRED", "monthly_mid"),
    "inv_sales":    ("FRED", "monthly_mid"),
    "saving_rate":  ("FRED", "monthly_end"),
    "housing_starts":("FRED","monthly_mid"),
    # ---- 季度增长（月末 BEA）----
    "gdp_real":     ("FRED", "quarterly"),
    "gdp_qoq":      ("FRED", "quarterly"),
    "gdp_pot":      ("FRED", "quarterly"),
    "gdi":          ("FRED", "quarterly"),
    "inv_private":  ("FRED", "quarterly"),
    "eci_wages":    ("BLS",  "quarterly"),
}

# ---------------------------------------------------------------------------
# 五-补、发布时间规则说明（解决"统计月份 vs 发布时间"的混淆）
# 关键语义：FRED 里月度数据的日期戳（如 2018-03-01）代表"统计参考期"（2018年3月），
# 而非数据发布的当天。下表给出每类频率的发布规则，供前端标注。
# ---------------------------------------------------------------------------
RELEASE_RULE = {
    # 日频/周频：日期即当期，无错位
    "daily":       "当期数据（每日）",
    "weekly":      "当期数据（每周）",
    "weekly_thu":  "当周数据（周四发布）",
    "weekly_fri":  "当周数据（周五发布）",
    "monthly":     "当期月份数据",
    # 月频：日期戳 = 统计月份，发布通常滞后到下月
    "monthly_1st_fri": "统计月数据 · 次月首周周五发布",
    "monthly_jolts":   "统计月数据 · 滞后约 1~2 个月发布",
    "monthly_mid":     "统计月数据 · 次月中旬发布",
    "monthly_end":     "统计月数据 · 次月末发布",
    # 季频：日期戳 = 统计季度，发布滞后到次季首月
    "quarterly":   "统计季度数据 · 次季首月月末发布",
}

# 人类可读的频率简称（用于指标卡标签）
FREQ_SHORT = {
    "daily": "日", "weekly": "周", "weekly_thu": "周", "weekly_fri": "周",
    "monthly": "月", "monthly_1st_fri": "月", "monthly_jolts": "月",
    "monthly_mid": "月", "monthly_end": "月", "quarterly": "季",
}


# ---------------------------------------------------------------------------
# 五-补、指标元数据（来源 / 显示单位 / 缩放）
# 数据说明：每个指标卡与图表下方的"数据说明"据此渲染。
#   source：发布机构（数据经 FRED/BLS/BEA 等渠道转发）
#   unit：显示单位（已按 scale 归一化后的中文单位）
#   scale：缩放因子，把原始值转成显示单位（如首申失业金由"人"转"千人"，除以 1000）
# 只对"0 太多"的大数指标做缩放，其余 scale=1 保持原始单位。
# ---------------------------------------------------------------------------
INDICATOR_META = {
    # ---- 利率 / 利差 / 通胀预期（单位 %）----
    "us10y":        {"source": "美国财政部",   "unit": "%", "scale": 1},
    "us2y":         {"source": "美国财政部",   "unit": "%", "scale": 1},
    "ffr":          {"source": "美联储",       "unit": "%", "scale": 1},
    "sofr":         {"source": "纽约联储",     "unit": "%", "scale": 1},
    "t10y2y":       {"source": "美国财政部",   "unit": "百分点", "scale": 1},
    "t10y3m":       {"source": "美国财政部",   "unit": "百分点", "scale": 1},
    "bei10y":       {"source": "美联储",       "unit": "%", "scale": 1},
    "fwd5y5y":      {"source": "美联储",       "unit": "%", "scale": 1},
    "tips10y":      {"source": "美国财政部",   "unit": "%", "scale": 1},
    "mortgage30":   {"source": "房地美",       "unit": "%", "scale": 1},
    "hy_spread":    {"source": "ICE BofA",     "unit": "百分点", "scale": 1},
    "vix":          {"source": "CBOE",         "unit": "指数", "scale": 1},
    "dxy":          {"source": "美联储",       "unit": "指数", "scale": 1},
    # ---- 美联储资产负债表 / 流动性 ----
    "fed_assets":   {"source": "美联储",       "unit": "十亿美元", "scale": 0.001},  # 原始：百万美元
    "on_rrp":       {"source": "纽约联储",     "unit": "十亿美元", "scale": 1},
    "reserves":     {"source": "美联储",       "unit": "十亿美元", "scale": 0.001},  # 原始：百万美元
    "bank_loans":   {"source": "美联储",       "unit": "十亿美元", "scale": 1},
    # ---- 就业 ----
    "payrolls":     {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "unrate":       {"source": "BLS 劳工统计局", "unit": "%", "scale": 1},
    "u6rate":       {"source": "BLS 劳工统计局", "unit": "%", "scale": 1},
    "participation":{"source": "BLS 劳工统计局", "unit": "%", "scale": 1},
    "labor_force":  {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "emratio":      {"source": "BLS 劳工统计局", "unit": "%", "scale": 1},
    "jolts_open":   {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "claims":       {"source": "劳工部 DOL",   "unit": "千人", "scale": 0.001},  # 原始：人(Number)
    "ahe":          {"source": "BLS 劳工统计局", "unit": "美元/时", "scale": 1},
    "avg_weekly_hours": {"source": "BLS 劳工统计局", "unit": "小时", "scale": 1},
    # ---- 就业行业细分 / 周工时 / 黄金年龄参与率 ----
    "manemp":       {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "uscons":       {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "usmine":       {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "temphelps":    {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "uspbs":        {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "usehs":        {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "ustrade":      {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "uswtrade":     {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "usfire":       {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "usinfo":       {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "uslah":        {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "usgovt":       {"source": "BLS 劳工统计局", "unit": "千人", "scale": 1},
    "awhman":       {"source": "BLS 劳工统计局", "unit": "小时", "scale": 1},
    "awhaetp":      {"source": "BLS 劳工统计局", "unit": "小时", "scale": 1},
    "prime_participation": {"source": "BLS 劳工统计局", "unit": "%", "scale": 1},
    # ---- 通胀 ----
    "cpi":          {"source": "BLS 劳工统计局", "unit": "%", "scale": 1},  # 已转同比
    "cpi_core":     {"source": "BLS 劳工统计局", "unit": "%", "scale": 1},
    "cpi_median":   {"source": "克利夫兰联储", "unit": "%", "scale": 1},
    "core_goods_cpi":   {"source": "BLS 劳工统计局", "unit": "%", "scale": 1},
    "core_services_cpi":{"source": "BLS 劳工统计局", "unit": "%", "scale": 1},
    "cpi_rent":     {"source": "BLS 劳工统计局", "unit": "%", "scale": 1},
    "zori":         {"source": "Zillow",       "unit": "%", "scale": 1},  # 原始美元/月，转同比后为 %
    "cpi_bls":      {"source": "BLS 劳工统计局", "unit": "指数", "scale": 1},
    "cpi_sa":       {"source": "BLS 劳工统计局", "unit": "指数", "scale": 1},
    "cpi_core_bls": {"source": "BLS 劳工统计局", "unit": "指数", "scale": 1},
    "cpi_supercore":{"source": "BLS 劳工统计局", "unit": "指数", "scale": 1},
    "cpi_shelter":  {"source": "BLS 劳工统计局", "unit": "指数", "scale": 1},
    "cpi_energy":   {"source": "BLS 劳工统计局", "unit": "指数", "scale": 1},
    "cpi_food":     {"source": "BLS 劳工统计局", "unit": "指数", "scale": 1},
    "pcepi":        {"source": "BEA 经济分析局", "unit": "%", "scale": 1},
    "pce_core":     {"source": "BEA 经济分析局", "unit": "%", "scale": 1},
    "pce":          {"source": "BEA 经济分析局", "unit": "十亿美元", "scale": 1},
    "pce_real":     {"source": "BEA 经济分析局", "unit": "十亿美元", "scale": 1},
    "mich_exp":     {"source": "密歇根大学",   "unit": "%", "scale": 1},
    "umcsent":      {"source": "密歇根大学",   "unit": "指数", "scale": 1},
    # ---- 增长 ----
    "gdp_real":     {"source": "BEA 经济分析局", "unit": "十亿美元", "scale": 1},
    "gdp_qoq":      {"source": "BEA 经济分析局", "unit": "%", "scale": 1},
    "gdp_pot":      {"source": "CBO 国会预算办", "unit": "十亿美元", "scale": 1},
    "gdi":          {"source": "BEA 经济分析局", "unit": "十亿美元", "scale": 1},
    "inv_private":  {"source": "BEA 经济分析局", "unit": "十亿美元", "scale": 1},
    "retail":       {"source": "Census 人口普查局", "unit": "十亿美元", "scale": 0.001},  # 原始：百万美元
    "inv_sales":    {"source": "Census 人口普查局", "unit": "倍", "scale": 1},
    "saving_rate":  {"source": "BEA 经济分析局", "unit": "%", "scale": 1},
    "housing_starts":{"source": "Census 人口普查局", "unit": "千套", "scale": 1},
    "eci_wages":    {"source": "BLS 劳工统计局", "unit": "指数", "scale": 1},
}

# 需要做缩放（scale != 1）的指标：抓取后对 series 与 latest 统一缩放
SCALED_INDICATORS = {k: v["scale"] for k, v in INDICATOR_META.items() if v.get("scale", 1) != 1}


# 就业扩散指数的行业清单（CES 主要 supersector，不重叠，合计≈总非农）
# 扩散指数 = 环比上升行业数 / 行业总数 × 100（参考 ISM PMI 的扩散指数构造法）
DIFFUSION_INDUSTRIES = [
    "manemp",    # 制造业
    "uscons",    # 建筑业
    "usmine",    # 采矿业
    "ustrade",   # 零售贸易
    "uswtrade",  # 批发贸易
    "uspbs",     # 专业与商业服务
    "usehs",     # 教育与医疗
    "usfire",    # 金融活动
    "usinfo",    # 信息业
    "uslah",     # 休闲与酒店
    "usgovt",    # 政府
]


# ---------------------------------------------------------------------------
# 六、派生指标计算规则（专题分析的数据基础）
# 每个派生指标：名称 -> (依赖的原始指标, 计算函数说明)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 超级核心通胀（supercore = 核心服务剔除住房）加权口径
# ---------------------------------------------------------------------------
# 权重取自 BLS《Relative importance of components in the Consumer Price Indexes》
# （U.S. city average, December 2025，Table 1 / 2024 weights，CPI-U，占 all items 百分比）。
# Shelter 是 Services less energy services 的子集，故两者基期相同（1982-1984=100），
# 可直接加权求差：supercore = (W_S × SASLE − W_H × Shelter) / (W_S − W_H)。
# 口径说明：这是美联储「supercore」的 CPI 版本（core services ex shelter），
# 剔除了能源服务与全部住房，比 BLS 官方的 "Services less rent of shelter" 更接近 supercore
# （后者仍含能源服务）。历史年份权重有漂移，此处统一用最新权重，属近似处理。
SUPERCORE_WEIGHTS = {
    "services_less_energy": 60.744,   # Services less energy services
    "shelter": 35.625,                # Shelter
}

DERIVED_INDICATORS = {
    "vu_ratio":     {"deps": ["jolts_open", "unrate"], "desc": "V/U 比率 = 岗位空缺数 / 失业人数（需 CLF16OV 与 unrate 推算失业人数）"},
    "payrolls_mom": {"deps": ["payrolls"], "desc": "非农新增 = 非农存量月环比差分"},
    "payrolls_3mma":{"deps": ["payrolls"], "desc": "非农新增 3 个月移动平均"},
    "cpi_yoy":      {"deps": ["cpi"], "desc": "CPI 同比（指数年化）"},
    "core_cpi_yoy": {"deps": ["cpi_core"], "desc": "核心 CPI 同比（剔除食品能源）"},
    "core_goods_yoy": {"deps": ["core_goods_cpi"], "desc": "核心商品 CPI 同比（剔除食品能源商品）"},
    "core_services_yoy": {"deps": ["core_services_cpi"], "desc": "核心服务 CPI 同比（剔除能源服务）"},
    "cpi_supercore": {"deps": ["core_services_cpi", "cpi_shelter"], "desc": "超级核心通胀指数 = 核心服务剔除住房（按 BLS 相对重要性加权）"},
    "cpi_supercore_yoy": {"deps": ["cpi_supercore"], "desc": "超级核心通胀同比（美联储关注的服务业内生通胀）"},
    "cpi_rent_yoy": {"deps": ["cpi_rent"], "desc": "CPI 租金同比（主要居所租金）"},
    "zori_yoy": {"deps": ["zori"], "desc": "ZORI 新租约租金同比（Zillow 挂牌租金，领先 CPI 租金约 12 个月）"},
    "pce_yoy":      {"deps": ["pcepi"], "desc": "PCE 同比"},
    "core_pce_yoy": {"deps": ["pce_core"], "desc": "核心 PCE 同比"},
    "cpi_pce_gap":  {"deps": ["cpi_yoy", "pce_yoy"], "desc": "CPI-PCE 剪刀差（正常 +0.3~0.5，倒挂为异常）"},
    "r_minus_g":    {"deps": ["tips10y", "gdp_qoq"], "desc": "实际利率 r - 实际增速 g（增长化债空间）"},
    "output_gap":   {"deps": ["gdp_real", "gdp_pot"], "desc": "产出缺口 = (实际GDP/潜在GDP - 1) * 100"},
    "sahm_rule":    {"deps": ["unrate"], "desc": "萨姆规则 = 失业率3MMA - 过去12个月最低3MMA（阈值0.5pp）"},
}

# ---------------------------------------------------------------------------
# 七、专题规则阈值（核心框架的固化）
# ---------------------------------------------------------------------------
TOPIC_RULES = {
    "inflation_anchor": {
        "name": "通胀锚定是否动摇",
        "indicator": "fwd5y5y",
        "desc": "5y5y 远期通胀补偿显著抬升（相对近 1 年均值偏离 > 50bp）",
        "threshold": 0.5,   # 百分比点
        "framework": "锚定不是看绝对水平，而是看长端预期对短期通胀的敏感性。5y5y 是最严格的锚定指标。",
    },
    "labor_freeze": {
        "name": "就业是否冻僵",
        "indicator": "vu_ratio",
        "desc": "V/U 比率持续 < 1 且首申抬升",
        "threshold_vu": 1.0,
        "framework": "低招聘 + 低解雇的'冻僵'状态；V/U 领先工资通胀约 2 季度。",
    },
    "beveridge_curve": {
        "name": "贝弗里奇曲线",
        "indicator": "beveridge",
        "desc": "失业率 vs 岗位空缺率散点轨迹，判断曲线内外移",
        "framework": "曲线外移=匹配效率下降；垂直下降=空缺崩而失业率不动（2021-22 美联储获胜）。",
    },
    "qt_end": {
        "name": "缩表是否到终点",
        "indicator": "on_rrp",
        "desc": "ON RRP 余额接近归零 + SOFR 突破走廊上限",
        "threshold": 100,   # 亿美元
        "framework": "ON RRP 归零且银行间开始拆借=缩表接近终点，SOFR 可能突破走廊上限。",
    },
    "technical_recession": {
        "name": "是否技术性衰退",
        "indicator": "gdp_qoq",
        "desc": "实际 GDP 连续两季环比折年负增长",
        "framework": "1948 以来 10 次技术性衰退全为 NBER 衰退；但需 NBER 一揽子交叉验证。",
    },
    "r_minus_g": {
        "name": "增长化债空间",
        "indicator": "r_minus_g",
        "desc": "实际利率 r vs 实际增速 g 的比较",
        "framework": "r<g 时可自然化债；r≈g 则化债空间有限，需警惕通胀化债。",
    },
    "cpi_pce_inversion": {
        "name": "CPI-PCE 倒挂",
        "indicator": "cpi_pce_gap",
        "desc": "CPI 同比跌破 PCE 同比（罕见倒挂）",
        "framework": "正常 CPI≈PCE+0.3~0.5pp；2026 年以来罕见倒挂，源于住房降温 + AI 推升 PCE 分项。",
    },
    "sahm_rule": {
        "name": "萨姆规则（衰退预警）",
        "indicator": "sahm_rule",
        "desc": "失业率 3MMA 高出过去 12 个月最低 3MMA ≥ 0.5pp 即触发",
        "threshold": 0.5,   # 百分点
        "framework": "Sahm Rule 由 Claudia Sahm 提出：当失业率的 3 个月移动平均，比过去 12 个月的最低 3 个月移动平均高出 0.50 个百分点时，经济正处于衰退的早期。它不预测衰退，而是实时确认衰退已经开始；历史上几乎每次衰退都触发，且误报极少。",
    },
    "phillips_curve": {
        "name": "菲利普斯曲线（非线性）",
        "indicator": "core_cpi_yoy",
        "desc": "失业率低于约 4% 阈值时，核心 CPI 是否非线性加速上行",
        "threshold_unrate": 4.0,   # 失业率 %，非线性拐点
        "threshold_core": 3.0,     # 核心 CPI 同比 %，通胀加速警戒
        "framework": "菲利普斯曲线的关键不是'有没有'，而是'非线性'：1995-2019 失业率从 10% 降到 3.5%，核心通胀纹丝不动（曲线'已死'）；2021-23 失业率跌破 4% 后核心 CPI 飙至 6%+（曲线'复活'）。失业率低于自然失业率（NAIRU，约 4%）时斜率陡峭，通胀对就业紧张高度敏感。",
    },
}
