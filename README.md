# 指数基金 Top20 买入推荐

每天打开，看到当天最适合买入的 20 只 A 类指数基金。

## 评分逻辑

采用 **Graham-Buffett 价值投资** 5 维评分体系（满分 100）：

| 维度 | 权重 | 核心逻辑 |
|------|------|----------|
| 估值分位 | 30 分 | PE/PB 处于历史低位 → 安全边际 |
| 均线系统 | 25 分 | 低于 MA60/120/240 → 金字塔抄底 |
| 回撤买入 | 20 分 | 从 1 年高点回撤幅度 → 越跌越买 |
| 质量保障 | 15 分 | 成立年限 + 规模 + 夏普比率 |
| 技术信号 | 10 分 | RSI 超卖 + MACD 底部拐头 |

**过滤条件：** A 类基金 / 排除走平线基金 / 排除净值长期不更新 / 近 1 年收益 > 2%

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

### 3. 启动系统

**Windows — 双击 `start.bat`**

**macOS/Linux — 终端运行：**
```bash
python start.py
```

浏览器自动打开 `http://localhost:3000`

### 4. 首次运行需要数据

数据库文件 `data/fund.db` 不包含在仓库中（太大）。首次运行前需要初始化数据，或从已有备份恢复。

## 项目结构

```
├── backend/
│   ├── main.py              # FastAPI 入口（单一 /api/top20 端点 + 5分钟缓存）
│   ├── config.py            # 阈值/过滤参数
│   ├── refresh_data.py      # 数据刷新脚本（供计划任务调用）
│   ├── engine/
│   │   ├── top20.py         # 5维评分引擎（估值+均线+回撤+质量+技术）
│   │   ├── indicators.py    # 技术指标计算（MA/MACD/RSI/复权）
│   │   └── signals.py       # 信号计算
│   ├── data/
│   │   ├── fetcher.py       # AkShare 数据采集
│   │   └── cleaner.py       # 数据清洗
│   └── models/
│       └── database.py      # SQLite 数据库
├── frontend/
│   ├── index.html           # 单页 Top20 表格
│   ├── app.js               # 前端逻辑
│   └── style.css            # 样式
├── docs/
│   └── 选基逻辑说明文档.md    # 详细评分设计文档
├── start.py                 # 一键启动脚本
├── start.bat                # Windows 启动
├── refresh_daily.bat        # Windows 计划任务脚本
└── README.md
```

## 数据更新

- Windows 计划任务 `FundRefresh`：每个工作日 18:30 自动运行 `refresh_daily.bat`
- 手动刷新：页面点击"刷新数据"跳过缓存重新计算
- 净值数据来源：AkShare → 东方财富

## API

| 端点 | 说明 |
|------|------|
| `GET /api/top20` | 获取 Top20 推荐（5 分钟缓存） |
| `GET /api/top20?refresh=true` | 跳过缓存，重新计算 |
| `GET /api/health` | 健康检查 |

## 技术栈

Python 3.11+ / FastAPI / SQLite / Pandas / NumPy / AkShare
