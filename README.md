# 📊 指数基金定投决策系统

A 股指数基金智能筛选 + 定投买卖时机推荐系统。

## 功能

- **🎯 定投决策** — 买入/卖出信号检测、定投倍数建议（0x~2x）、止盈策略、持仓诊断
- **📋 基金筛选** — 多因子评分排名（估值/收益/风控/技术/跟踪误差/基本面）
- **💵 定投模式** — 专为定投优化的评分体系（估值优先+趋势确认+波动率区间最优）
- **📈 回测验证** — 策略 vs 沪深300 对比，含 IRR/夏普/信息比率/最大回撤
- **🔍 复权净值** — 自动处理分红除权，走势图与支付宝一致

## 快速开始

### 环境要求

- Python 3.11+
- Windows / macOS / Linux

### 1. 克隆项目

```bash
git clone <repo-url>
cd 基金
```

### 2. 安装依赖

```bash
pip install -r backend/requirements.txt
```

### 3. 初始化数据（首次运行，约 30 分钟）

```bash
cd backend
python scheduler.py
```

这一步会拉取全市场指数型基金列表、历史净值和基准指数数据。

### 4. 启动系统

**Windows — 双击 `start.bat`**

**macOS/Linux — 终端运行：**
```bash
python start.py
```

浏览器自动打开 `http://localhost:3000`

## 项目结构

```
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 权重/阈值配置
│   ├── scheduler.py         # 数据初始化 + 定时更新
│   ├── engine/
│   │   ├── scorer.py        # 综合评分引擎
│   │   ├── indicators.py    # 技术指标计算（MA/MACD/RSI/复权）
│   │   ├── signals.py       # 信号评分
│   │   ├── rank.py          # 排名 + 数据刷新
│   │   ├── backtest.py      # 回测引擎
│   │   └── aip_advisor.py   # 定投时机顾问（买入/卖出信号）
│   ├── data/
│   │   ├── fetcher.py       # AkShare 数据采集
│   │   └── cleaner.py       # 数据清洗
│   ├── models/
│   │   └── database.py      # SQLite 数据库
│   └── api/
│       └── routes.py        # API 路由
├── frontend/
│   ├── index.html           # 单页应用
│   ├── app.js               # 前端逻辑
│   └── style.css            # 样式
├── docs/
│   └── 选基逻辑说明文档.md    # 详细设计文档
├── start.py                 # 一键启动脚本
├── start.bat                # Windows 启动
└── README.md
```

## 配置

所有可调参数在 `backend/config.py`：

- 评分维度权重（买入/定投两套）
- PE 分位阈值
- 定投倍数映射
- 止盈触发线
- 买入/卖出信号参数

修改后重启后端即可生效。

## 数据更新

- 系统启动时自动注册每日 18:30 净值更新任务
- 手动触发：`POST /api/admin/refresh`
- 建议每个交易日保持后端运行

## 技术栈

Python 3.11+ / FastAPI / SQLite / Pandas / NumPy / AkShare / ECharts
