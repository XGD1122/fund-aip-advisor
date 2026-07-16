# 指数基金智能投顾系统 (Fund AIP Advisor) v2.0

全自动指数基金筛选、评分、持仓管理、卖出决策系统。每天打开，看到当天最值得买入/卖出的信号。

## 核心功能

### 买入推荐 (Top20)
基于专业六维评分体系，每日从全市场指数基金中筛选最优 20 只：
- **估值安全边际** (30分) — NAV 历史分位，格雷厄姆核心原则
- **收益能力** (20分) — 夏普比率 + 绝对收益 + 正收益稳定性
- **趋势与均线** (20分) — 均线偏离价值 + MA 斜率方向
- **技术反转** (15分) — RSI 超卖 + MACD 拐头 + KDJ + 布林带
- **基本面质量** (15分) — 规模/年限/费率/跟踪误差 (对标晨星)
- **回撤与风控** (10分) — 回撤深度 + 波动率 + 连跌天数

### 卖出信号
10 维卖出信号体系，对标机构策略：
- 目标止盈（持有期自适应） / 亏损止损 / 移动止盈
- 估值退出（PE/PB 参考） / 多周期均线破位
- MACD 顶背离 / RSI 背离 / 布林带超买 / KDJ 超买
- 多因子共振加成 → 综合卖出紧迫度 0-100 分
- 分层减仓建议：10% → 30% → 50% → 100%

### 持仓管理
- 添加/合并/删除持仓
- 实时盈亏计算 + 卖出信号联动
- 赛道集中度分析 + 相关性检测
- 组合风险评估 + 再平衡建议
- 部分卖出支持（按比例减仓）
- 卖出历史记录

### 买卖信号一致性
买卖引擎共享统一的趋势判断框架：低于均线+趋势改善=价值机会，低于均线+趋势恶化=卖出信号，避免自相矛盾。

## 快速开始

### 环境要求
Python 3.11+

### 1. 克隆项目
```bash
git clone git@github.com:XGD1122/fund-aip-advisor.git
cd fund-aip-advisor
```

### 2. 安装依赖
```bash
pip install -r backend/requirements.txt
```

### 3. 初始化数据（首次运行，约 30-60 分钟）
```bash
cd backend
python init_data.py
```
这一步会：建表 → 拉取全市场指数型基金列表 → 拉取历史净值 → 计算技术信号。

### 4. 启动系统

**Windows — 双击 `start.bat`**

**macOS/Linux — 终端运行：**
```bash
python start.py
```

浏览器自动打开 `http://localhost:3000`，前端通过 localhost:8000 调用后端 API。

## 项目结构
```
├── backend/
│   ├── main.py              # FastAPI 入口（API 端点 + 缓存 + 自动刷新）
│   ├── config.py            # 阈值/过滤参数配置
│   ├── init_data.py         # 首次数据初始化（克隆后运行一次）
│   ├── refresh_data.py      # 每日数据刷新
│   ├── engine/
│   │   ├── top20.py         # 六维买入评分引擎
│   │   ├── advisor.py       # 卖出信号引擎 + 持仓分析
│   │   └── indicators.py    # 技术指标计算（MA/MACD/RSI/KDJ/布林带/ATR）
│   ├── data/
│   │   ├── fetcher.py       # AkShare 数据采集（东方财富）
│   │   └── cleaner.py       # 数据清洗与入库
│   └── models/
│       └── database.py      # SQLite 数据库 + 自动迁移
├── frontend/
│   ├── index.html           # 单页应用
│   ├── app.js               # 前端逻辑（含 XSS 防护）
│   └── style.css            # 样式
├── docs/
│   └── 选基逻辑说明文档.md    # 详细评分设计文档
├── start.py                 # 跨平台一键启动脚本
├── start.bat                # Windows 启动脚本
├── refresh_daily.bat        # Windows 每日计划任务脚本
└── README.md
```

## 数据更新

- 启动时自动检测数据新鲜度，过期自动刷新
- 每小时检查一次，发现数据过期自动触发 `refresh_daily()`
- Windows 计划任务 `FundRefresh`：每个工作日 18:30 运行 `refresh_daily.bat`
- 手动刷新：页面点击"刷新数据"或访问 `/api/admin/refresh`
- 净值数据来源：AkShare → 东方财富

## API 文档

启动后端后访问 `http://localhost:8000/docs` 查看 Swagger 文档。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/top20` | GET | 获取 Top20 推荐（5分钟缓存） |
| `/api/top20?refresh=true` | GET | 跳过缓存，重新计算 |
| `/api/fund/{code}` | GET | 单只基金净值历史 + 技术指标 + 收益率 |
| `/api/fund/{code}/advice` | GET | 单只基金买卖建议 |
| `/api/fund/{code}/technicals` | GET | 技术指标仪表盘 |
| `/api/fund/{code}/nav/{date}` | GET | 指定日期净值查询（含容错） |
| `/api/portfolio` | GET | 持仓列表 + 实时盈亏 + 卖出信号 |
| `/api/portfolio/add` | POST | 添加持仓（支持自动合并） |
| `/api/portfolio/{id}/sell` | PUT | 卖出持仓（支持部分卖出） |
| `/api/portfolio/{id}` | DELETE | 删除持仓 |
| `/api/portfolio/{id}` | PUT | 更新持仓备注 |
| `/api/portfolio/history` | GET | 已卖出历史记录 |
| `/api/portfolio/analysis` | GET | 持仓组合分析（风险/相关性/再平衡） |
| `/api/admin/refresh` | GET | 手动触发每日数据刷新 |
| `/api/health` | GET | 健康检查 |

## 技术栈

Python 3.11+ / FastAPI / SQLite (WAL mode) / Pandas / NumPy / AkShare / Chart.js

## 评分逻辑说明

详见 `docs/选基逻辑说明文档.md`。评分体系对标：
- **天天基金** — 五维评估（择时能力/稳定性/抗风险/收益率/选证能力）
- **晨星 Morningstar** — Medalist Rating（People/Process/Parent + Price Score）
- **机构 ETF 策略** — 四维共振法（估值→趋势→风控→多因子确认）

## 开源许可

仅供学习研究，不构成投资建议。投资有风险，入市需谨慎。
