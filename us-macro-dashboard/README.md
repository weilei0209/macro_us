# 美国宏观数据看板

基于「美国宏观数据训练营」（腾讯会议 829/830 两场）+ 培训文稿，构建的**多页面站点 + 自动更新 + 专题分析**看板。目标：本机起服务，配合 Cloudflare Tunnel 从外网访问。

## 目录结构

```
us-macro-dashboard/
├── site/                 # 多页面站点（渲染产物，本机服务托管此目录）
│   ├── index.html        # 首页：全景速览 + KPI + 预警信号灯 + 关键趋势 + 月度节奏
│   ├── employment.html   # 主题页：就业
│   ├── inflation.html    # 主题页：通胀
│   ├── growth.html       # 主题页：增长
│   ├── fiscal.html       # 主题页：财政
│   ├── monetary.html     # 主题页：货币
│   ├── leading.html      # 主题页：领先指标
│   ├── topics.html       # 专题页：7 篇专题分析（卡片可点开）
│   ├── topics/           # 专题独立分析页（每篇专题一个页面）
│   │   ├── inflation_anchor.html    通胀锚定
│   │   ├── labor_freeze.html        就业冻僵
│   │   ├── beveridge.html           贝弗里奇曲线（Canvas 互动图）
│   │   ├── qt_end.html              缩表终点
│   │   ├── technical_recession.html 技术性衰退
│   │   ├── r_minus_g.html           增长化债
│   │   └── cpi_pce_inversion.html   CPI-PCE 剪刀差
│   ├── about.html        # 关于：方法论 + 数据口径速查
│   └── assets/           # ECharts + 共享样式 + 图表 JS（本地引入，离线可看）
├── assets/               # 源资源（render 时复制到 site/assets）
├── scripts/
│   ├── indicators.py     # 指标定义 + 发布日历 + 专题规则阈值
│   ├── fetcher.py        # 四 API 客户端 + 缓存 + 发布日历判定
│   ├── fetch_all.py      # 数据抓取 + 派生指标计算
│   ├── analyze.py        # 专题分析规则引擎
│   ├── render.py         # 多页面站点渲染器（生成 site/）
│   └── update.py         # 一键更新入口
├── serve.sh              # 本机静态服务启动脚本
└── data/
    ├── cache/            # 原始序列缓存（每个指标一个 json）
    ├── series.json       # 标准化全量序列
    ├── latest.json       # 最新值快照 + 派生指标
    └── reports.json      # 专题分析结果
```

## 使用方法

### 生成/更新站点

```bash
cd us-macro-dashboard
python3 scripts/update.py          # 精准增量（推荐，只拉当日到期指标）
python3 scripts/update.py --full   # 全量更新
```

`update.py` 会依次执行：抓数据 → 算派生指标 → 跑专题规则 → 渲染 `site/` 多页面。

### 本机启动服务

```bash
bash serve.sh          # 默认 8080 端口，访问 http://127.0.0.1:8080
bash serve.sh 9000     # 自定义端口
```

### 定时更新

通过 WorkBuddy 定时任务（automation）每天清晨调用 `python3 scripts/update.py`，实现「查发布日历 → 精准增量拉取 → 跑专题规则 → 重渲染 site/」。

## 外网发布（Cloudflare Tunnel，后续步骤）

1. 准备一个托管在 Cloudflare 的域名。
2. 安装 `cloudflared`。
3. 建隧道并生成 CNAME：`cloudflared tunnel login` → `cloudflared tunnel create macro` → 在域名 DNS 加 CNAME 指向 `<tunnel-id>.cfargotunnel.com`。
4. 常驻运行：`cloudflared tunnel run macro`，配置 ingress 指向 `http://127.0.0.1:8080`。
5. 外网即可通过你的域名（自动 HTTPS）访问本机服务。

## 数据源

| API | 环境变量 | 覆盖 |
|---|---|---|
| FRED | `FRED_API_KEY` | 利率/BEI/5y5y/V-U/流动性等派生与聚合 |
| BLS | `BLS_API_KEY` | 非农/失业率/CPI/工资/JOLTS/首申 |
| BEA | `BEA_API_KEY` | GDP/PCE/GDI 国民账户 |
| Census | `CENSUS_API_KEY` | 零售/地产/贸易 |
| 纽约联储 ACM | 无需 key | 期限溢价 / 风险中性预期路径 / 拟合 10Y（`ACMTermPremium.xls`，日频） |
| Zillow | 无需 key | ZORI 新租约租金（公开 CSV，月频） |

四个 API key 均从环境变量读取，无需硬编码。ACM 与 Zillow 走公开文件下载，
其中 ACM 只有 .xls（OLE2/BIFF8）一种格式，由 `scripts/xls_lite.py`（纯标准库）解析，
不引入 pandas / xlrd。

## 专题分析（自动触发规则）

7 个专题对应核心分析框架：

1. 通胀锚定（5y5y 远期通胀补偿）
2. 就业冻僵（V/U 比率）
3. 贝弗里奇曲线（失业率 vs 岗位空缺率）
4. 缩表终点（ON RRP 余额）
5. 技术性衰退（连续两季 GDP 负增长）
6. 增长化债空间（r - g）
7. CPI-PCE 剪刀差（口径异常）

> 触发阈值集中在 `indicators.py` 的 `TOPIC_RULES`，可自行调整。

## 视觉风格

暗色金融终端风格（深色背景 + 高对比），图表层用 ECharts 本地渲染：

- **首页**：8 个 KPI 大卡 + 预警信号灯 + 6 张关键趋势图 + 月度发布节奏
- **主题页**：各自模块的核心图表 + 口径要点 + 全部指标卡（带 sparkline）
- **专题页**：7 篇专题分析卡片（可点击），每篇点开后进入独立分析页（含完整分析 + 数据图表 + 框架 + 下一步关注）
- **贝弗里奇曲线**：独立 Canvas 互动图（空缺率×失业率散点 + 时间轨迹副图 + 自动判读）
- **关于页**：关键口径速查表 + 方法论来源

涨跌配色遵循 A 股习惯：涨=红，跌=绿。

## 说明

- 数据仅供研究参考，不构成投资建议。
