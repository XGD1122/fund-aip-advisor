# 基金筛选系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 A 股公募基金智能筛选系统，支持综合评分排名、定投筛选和策略回测。

**Architecture:** 四层架构 — 数据采集层 (AkShare) → 计算引擎层 (指标/信号/评分/回测) → 存储层 (SQLite) → Web 展示层 (FastAPI + Vue 3 + ECharts)。后端 Python 做重计算，前端仅展示结果。

**Tech Stack:** Python 3.11+ / FastAPI / Vue 3 / ECharts / SQLite / Pandas / NumPy / AkShare / APScheduler

**说明：** 本项目非 git 仓库，不执行 git commit。每个 Task 完成后验证即可。

---

### Task 1: 项目初始化 & 目录结构

**Files:**
- Create: `F:\基金\backend\requirements.txt`
- Create: `F:\基金\backend\config.py`
- Create: `F:\基金\backend\main.py`
- Create: `F:\基金\backend\models\__init__.py`
- Create: `F:\基金\backend\models\database.py`
- Create: `F:\基金\backend\data\__init__.py`
- Create: `F:\基金\backend\engine\__init__.py`
- Create: `F:\基金\backend\api\__init__.py`

- [ ] **Step 1: 创建所有目录**

```powershell
New-Item -ItemType Directory -Force -Path "F:\基金\backend\models"
New-Item -ItemType Directory -Force -Path "F:\基金\backend\data"
New-Item -ItemType Directory -Force -Path "F:\基金\backend\engine"
New-Item -ItemType Directory -Force -Path "F:\基金\backend\api"
New-Item -ItemType Directory -Force -Path "F:\基金\data"
```

- [ ] **Step 2: 创建 requirements.txt**

```
fastapi==0.115.0
uvicorn==0.30.6
pandas==2.2.2
numpy==2.1.1
akshare==1.14.88
apscheduler==3.10.4
pydantic==2.9.2
```

- [ ] **Step 3: 创建 config.py**

```python
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
DB_PATH = os.path.join(DATA_DIR, "fund.db")

# 默认评分权重 — 一笔买入模式
SCORE_WEIGHTS_BUY = {
    "return_": 0.30,
    "valuation": 0.15,
    "risk": 0.12,
    "fundamental": 0.13,
    "technical": 0.30,
}

# 默认评分权重 — 定投模式
SCORE_WEIGHTS_AIP = {
    "valuation": 0.25,
    "trend": 0.20,
    "return_": 0.20,
    "volatility": 0.15,
    "risk": 0.10,
    "fundamental": 0.10,
}

# 子指标权重 — 一笔买入
SUB_WEIGHTS_BUY = {
    "return_1m": 0.05, "return_3m": 0.08, "return_6m": 0.08,
    "return_1y": 0.06, "return_3y": 0.03,
    "pe_percentile": 0.06, "nav_deviation": 0.04, "pb_percentile": 0.03, "drawdown_state": 0.02,
    "max_drawdown": 0.06, "sharpe": 0.03, "volatility": 0.02, "calmar": 0.01,
    "fund_scale": 0.03, "fund_age": 0.03, "manager_tenure": 0.03, "fee_rate": 0.02, "manager_return": 0.02,
    "ma_trend": 0.12, "macd_signal": 0.08, "rsi": 0.05, "bollinger": 0.05,
}

# 子指标权重 — 定投
SUB_WEIGHTS_AIP = {
    "pe_percentile": 0.15, "nav_deviation": 0.06, "drawdown_state": 0.04,
    "ma60_slope": 0.10, "ma120_slope": 0.10,
    "return_1y": 0.10, "return_3y": 0.10,
    "volatility": 0.15,
    "max_drawdown": 0.06, "sharpe": 0.04,
    "fund_scale": 0.03, "fund_age": 0.03, "manager_tenure": 0.04,
}

RISK_FREE_RATE = 0.025
TOP_N_DEFAULT = 20
REQUEST_DELAY_MIN = 1.0
REQUEST_DELAY_MAX = 3.0
TRAIN_TEST_SPLIT_DATE = "2024-01-01"
```

- [ ] **Step 4: 创建数据库初始化模块 models/database.py**

```python
import sqlite3
from config import DB_PATH, DATA_DIR
import os

def get_connection():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fund_basic (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            fund_type TEXT NOT NULL,
            establish_date TEXT,
            company TEXT,
            manager_name TEXT,
            manager_tenure_days INTEGER DEFAULT 0,
            scale REAL DEFAULT 0,
            fee_mgmt REAL DEFAULT 0,
            fee_custody REAL DEFAULT 0,
            benchmark TEXT,
            updated_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fund_nav (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            unit_nav REAL,
            acc_nav REAL,
            daily_return REAL,
            PRIMARY KEY (code, date)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fund_score (
            code TEXT NOT NULL,
            calc_date TEXT NOT NULL,
            mode TEXT NOT NULL,
            total_score REAL,
            return_score REAL,
            valuation_score REAL,
            risk_score REAL,
            fundamental_score REAL,
            technical_score REAL,
            rank_in_type INTEGER,
            fund_type TEXT,
            PRIMARY KEY (code, calc_date, mode)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fund_signal (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            ma5 REAL, ma20 REAL, ma60 REAL, ma120 REAL,
            macd_dif REAL, macd_dea REAL, macd_hist REAL,
            rsi14 REAL,
            bb_upper REAL, bb_mid REAL, bb_lower REAL,
            PRIMARY KEY (code, date)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS backtest_record (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT,
            mode TEXT,
            start_date TEXT,
            end_date TEXT,
            rebalance_months INTEGER,
            top_n INTEGER,
            total_return REAL,
            annual_return REAL,
            max_drawdown REAL,
            sharpe REAL,
            win_rate REAL,
            alpha REAL,
            info_ratio REAL,
            benchmark_name TEXT,
            benchmark_return REAL,
            params_json TEXT,
            created_at TEXT
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_nav_code_date ON fund_nav(code, date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_score_date ON fund_score(calc_date, mode)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_signal_code_date ON fund_signal(code, date)")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化: {DB_PATH}")
```

- [ ] **Step 5: 创建 main.py 占位**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.database import init_db

app = FastAPI(title="基金筛选系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_db()

@app.get("/api/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

- [ ] **Step 6: 创建空 __init__.py**

```powershell
New-Item -ItemType File -Force -Path "F:\基金\backend\models\__init__.py"
New-Item -ItemType File -Force -Path "F:\基金\backend\data\__init__.py"
New-Item -ItemType File -Force -Path "F:\基金\backend\engine\__init__.py"
New-Item -ItemType File -Force -Path "F:\基金\backend\api\__init__.py"
```

- [ ] **Step 7: 安装依赖并验证启动**

```powershell
cd F:\基金\backend; pip install -r requirements.txt; python main.py
# 打开 http://localhost:8000/api/health 确认返回 {"status":"ok"}
# 确认后 Ctrl+C 停止
```

---

### Task 2: 数据采集模块

**Files:**
- Create: `F:\基金\backend\data\fetcher.py`
- Create: `F:\基金\backend\data\cleaner.py`

- [ ] **Step 1: 创建 fetcher.py — 基金列表采集**

```python
import akshare as ak
import pandas as pd
import time
import random
from config import REQUEST_DELAY_MIN, REQUEST_DELAY_MAX

def _delay():
    time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

def fetch_all_fund_list() -> pd.DataFrame:
    """获取全市场公募基金列表"""
    _delay()
    try:
        df = ak.fund_name_em()
        df = df.rename(columns={
            "基金代码": "code",
            "基金名称": "name",
            "基金类型": "fund_type",
        })
        df["code"] = df["code"].astype(str).str.zfill(6)
        return df[["code", "name", "fund_type"]]
    except Exception as e:
        print(f"获取基金列表失败: {e}")
        return pd.DataFrame(columns=["code", "name", "fund_type"])

def fetch_fund_nav(code: str, start_date: str = "20180101") -> pd.DataFrame:
    """获取单只基金的历史净值"""
    _delay()
    try:
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={
            "净值日期": "date",
            "单位净值": "unit_nav",
            "累计净值": "acc_nav",
            "日增长率": "daily_return",
        })
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["code"] = code
        if "daily_return" in df.columns:
            df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce") / 100.0
        return df[["code", "date", "unit_nav", "acc_nav", "daily_return"]]
    except Exception as e:
        print(f"获取基金 {code} 净值失败: {e}")
        return pd.DataFrame()

def fetch_fund_detail(code: str) -> dict:
    """获取基金详情（规模、经理、费率）"""
    _delay()
    try:
        df = ak.fund_individual_basic_info_xq(symbol=code)
        if df is None or df.empty:
            return {}
        row = df.iloc[0]
        return {
            "code": code,
            "establish_date": str(row.get("成立日期", "")),
            "company": str(row.get("基金管理人", "")),
            "manager_name": str(row.get("基金经理", "")),
            "scale": float(row.get("基金规模", 0) or 0),
            "fee_mgmt": float(row.get("管理费率", 0) or 0),
            "fee_custody": float(row.get("托管费率", 0) or 0),
            "benchmark": str(row.get("业绩比较基准", "")),
        }
    except Exception as e:
        print(f"获取基金 {code} 详情失败: {e}")
        return {}

def fetch_index_daily(code: str = "000300", start_date: str = "20180101") -> pd.DataFrame:
    """获取指数日线数据（沪深300/中证500等）"""
    _delay()
    try:
        df = ak.stock_zh_index_daily(symbol=f"sh{code}")
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={"date": "date", "close": "close"})
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["code"] = code
        return df[["code", "date", "close"]]
    except Exception as e:
        print(f"获取指数 {code} 数据失败: {e}")
        return pd.DataFrame()

def fetch_index_valuation(index_name: str = "沪深300") -> pd.DataFrame:
    """获取指数PE/PB估值分位数据"""
    _delay()
    try:
        df = ak.index_value_name_funddb()
        if df is None or df.empty:
            return pd.DataFrame()
        df = df[df["指数名称"].str.contains(index_name, na=False)]
        if df.empty:
            return pd.DataFrame()
        row = df.iloc[0]
        return {
            "pe": float(row.get("市盈率", 0) or 0),
            "pe_percentile": float(row.get("市盈率分位", 50) or 50) / 100.0,
            "pb": float(row.get("市净率", 0) or 0),
            "pb_percentile": float(row.get("市净率分位", 50) or 50) / 100.0,
        }
    except Exception as e:
        print(f"获取指数估值失败: {e}")
        return {}
```

- [ ] **Step 2: 创建 cleaner.py — 数据清洗**

```python
import pandas as pd
import numpy as np
import sqlite3
from models.database import get_connection

def clean_nav_data(df: pd.DataFrame) -> pd.DataFrame:
    """清洗净值数据：去重、填充缺失、异常值处理"""
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["code", "date"])
    df = df.dropna(subset=["unit_nav"])
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["acc_nav"] = pd.to_numeric(df["acc_nav"], errors="coerce")
    df = df.dropna(subset=["unit_nav"])
    # 过滤异常日涨跌 (>15% 视为异常)
    if "daily_return" in df.columns:
        df["daily_return"] = df["daily_return"].clip(-0.15, 0.15)
    return df

def save_fund_list(df: pd.DataFrame):
    """保存基金列表到数据库"""
    if df.empty:
        return
    conn = get_connection()
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    for _, row in df.iterrows():
        conn.execute("""
            INSERT OR REPLACE INTO fund_basic (code, name, fund_type, updated_at)
            VALUES (?, ?, ?, ?)
        """, (row["code"], row["name"], row["fund_type"], today))
    conn.commit()
    conn.close()

def save_nav_data(df: pd.DataFrame):
    """保存净值数据到数据库，忽略重复"""
    if df.empty:
        return
    conn = get_connection()
    for _, row in df.iterrows():
        try:
            conn.execute("""
                INSERT OR IGNORE INTO fund_nav (code, date, unit_nav, acc_nav, daily_return)
                VALUES (?, ?, ?, ?, ?)
            """, (str(row["code"]), str(row["date"]),
                  float(row.get("unit_nav", 0) or 0),
                  float(row.get("acc_nav", 0) or 0),
                  float(row.get("daily_return", 0) or 0)))
        except Exception:
            continue
    conn.commit()
    conn.close()
```

- [ ] **Step 3: 验证数据采集**

```python
# 在 backend 目录下运行 python -c "
from data.fetcher import fetch_all_fund_list, fetch_fund_nav
df_list = fetch_all_fund_list()
print(f'获取基金列表: {len(df_list)} 只')
if len(df_list) > 0:
    code = df_list.iloc[0]['code']
    df_nav = fetch_fund_nav(code)
    print(f'{code} 净值数据: {len(df_nav)} 条')
"
```

---

### Task 3: 定时任务 & 数据初始化

**Files:**
- Create: `F:\基金\backend\scheduler.py`
- Modify: `F:\基金\backend\main.py`

- [ ] **Step 1: 创建 scheduler.py**

```python
import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import pandas as pd
from data.fetcher import fetch_all_fund_list, fetch_fund_nav, fetch_fund_detail, fetch_index_daily
from data.cleaner import clean_nav_data, save_fund_list, save_nav_data
from models.database import get_connection

scheduler = BackgroundScheduler()

def job_fetch_fund_list():
    """每周拉取基金列表"""
    print(f"[{datetime.now()}] 拉取基金列表...")
    df = fetch_all_fund_list()
    if not df.empty:
        save_fund_list(df)
        print(f"  基金列表更新: {len(df)} 只")

def job_fetch_nav_daily():
    """每日拉取净值数据"""
    print(f"[{datetime.now()}] 拉取净值数据...")
    conn = get_connection()
    codes = [r["code"] for r in conn.execute("SELECT code FROM fund_basic").fetchall()]
    conn.close()

    count = 0
    for code in codes:
        df = fetch_fund_nav(code)
        if not df.empty:
            df = clean_nav_data(df)
            save_nav_data(df)
            count += 1
            if count % 50 == 0:
                print(f"  已拉取 {count}/{len(codes)} 只基金净值")
    print(f"  净值更新完成: {count}/{len(codes)}")

def job_fetch_index():
    """每日拉取基准指数"""
    print(f"[{datetime.now()}] 拉取指数数据...")
    for idx_code in ["000300", "000905"]:  # 沪深300, 中证500
        df = fetch_index_daily(idx_code)
        if not df.empty:
            conn = get_connection()
            for _, row in df.iterrows():
                conn.execute("""
                    INSERT OR IGNORE INTO index_daily (code, date, close)
                    VALUES (?, ?, ?)
                """, (idx_code, str(row["date"]), float(row["close"])))
            conn.commit()
            conn.close()
    print("  指数数据更新完成")

def init_data():
    """首次运行：全量拉取"""
    print(f"[{datetime.now()}] 首次全量数据初始化...")
    # 1. 拉取基金列表
    df_list = fetch_all_fund_list()
    if not df.empty:
        save_fund_list(df_list)
        print(f"  基金列表: {len(df_list)} 只")

    # 2. 拉取净值（全量，耗时较长）
    codes = df_list["code"].tolist() if not df_list.empty else []
    total = len(codes)
    for i, code in enumerate(codes):
        df = fetch_fund_nav(code)
        if not df.empty:
            df = clean_nav_data(df)
            save_nav_data(df)
        if (i + 1) % 100 == 0:
            print(f"  净值进度: {i+1}/{total}")

    # 3. 拉取指数
    job_fetch_index()

    # 4. 创建指数日线表
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS index_daily (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL,
            PRIMARY KEY (code, date)
        )
    """)
    conn.commit()
    conn.close()

    print(f"[{datetime.now()}] 数据初始化完成")

def start_scheduler():
    scheduler.add_job(job_fetch_nav_daily, "cron", hour=18, minute=30, id="nav_daily")
    scheduler.add_job(job_fetch_fund_list, "cron", day_of_week="sat", hour=8, minute=0, id="fund_list_weekly")
    scheduler.add_job(job_fetch_index, "cron", hour=18, minute=0, id="index_daily")
    scheduler.start()
    print("定时任务已启动")
```

- [ ] **Step 2: 更新 main.py，集成调度器**

```python
# 在 main.py 的 startup 事件后添加调度器启动，完整 main.py:

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.database import init_db
from scheduler import start_scheduler

app = FastAPI(title="基金筛选系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_db()
    start_scheduler()

@app.get("/api/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

- [ ] **Step 3: 添加数据初始化命令入口**

```python
# 在 scheduler.py 末尾添加
if __name__ == "__main__":
    from models.database import init_db
    init_db()
    init_data()
```

- [ ] **Step 4: 验证调度器可以导入**

```powershell
cd F:\基金\backend; python -c "from scheduler import start_scheduler; print('OK')"
```

---

### Task 4: 技术指标计算引擎

**Files:**
- Create: `F:\基金\backend\engine\indicators.py`

- [ ] **Step 1: 创建 indicators.py — 完整技术指标计算**

```python
import pandas as pd
import numpy as np
from models.database import get_connection

def calc_ma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()

def calc_ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()

def calc_macd(close: pd.Series, fast=12, slow=26, signal=9) -> dict:
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    hist = 2 * (dif - dea)
    return {"macd_dif": dif, "macd_dea": dea, "macd_hist": hist}

def calc_rsi(close: pd.Series, window=14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=window, adjust=False).mean()
    avg_loss = loss.ewm(span=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_bollinger(close: pd.Series, window=20, num_std=2) -> dict:
    mid = calc_ma(close, window)
    std = close.rolling(window=window, min_periods=1).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return {"bb_mid": mid, "bb_upper": upper, "bb_lower": lower}

def calc_drawdown(nav: pd.Series) -> pd.Series:
    """计算滚动回撤序列"""
    cummax = nav.expanding().max()
    return (nav - cummax) / cummax

def calc_max_drawdown(nav: pd.Series, window_days: int = 252) -> float:
    """近一年最大回撤"""
    rolling_max = nav.rolling(window=window_days, min_periods=1).max()
    drawdown = (nav - rolling_max) / rolling_max
    return float(drawdown.min())

def calc_sharpe(returns: pd.Series, risk_free: float = 0.025, window_days: int = 252) -> float:
    """年化夏普比率"""
    excess = returns - risk_free / 252
    if excess.std() == 0 or len(excess) < window_days:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(252))

def calc_volatility(returns: pd.Series, window_days: int = 252) -> float:
    """年化波动率"""
    if len(returns) < window_days:
        return float(returns.std() * np.sqrt(252)) if len(returns) > 1 else 0.0
    return float(returns.tail(window_days).std() * np.sqrt(252))

def calc_calmar(nav: pd.Series, returns: pd.Series) -> float:
    """Calmar比率 = 年化收益 / 最大回撤绝对值"""
    annual_return = calc_annual_return(nav)
    max_dd = abs(calc_max_drawdown(nav))
    if max_dd == 0:
        return 0.0
    return annual_return / max_dd

def calc_annual_return(nav: pd.Series, window_days: int = 252) -> float:
    """滚动年化收益率"""
    if len(nav) < 2:
        return 0.0
    days = min(window_days, len(nav) - 1)
    total_return = (nav.iloc[-1] / nav.iloc[-days-1]) - 1 if days < len(nav) else (nav.iloc[-1] / nav.iloc[0]) - 1
    years = days / 252
    if years == 0:
        return 0.0
    return float((1 + total_return) ** (1 / years) - 1)

def calc_period_return(nav: pd.Series, days: int) -> float:
    """计算指定天数的收益率"""
    if len(nav) < days or days == 0:
        if len(nav) < 2:
            return 0.0
        return float(nav.iloc[-1] / nav.iloc[0] - 1)
    return float(nav.iloc[-1] / nav.iloc[-days] - 1)

def calc_nav_deviation(nav: pd.Series) -> float:
    """净值相对MA120的偏离度"""
    if len(nav) < 120:
        return 0.0
    ma120 = nav.rolling(window=120, min_periods=1).mean().iloc[-1]
    current = nav.iloc[-1]
    if ma120 == 0:
        return 0.0
    return float((current - ma120) / ma120)

def calc_ma_slope(nav: pd.Series, window: int, lookback: int = 20) -> float:
    """计算均线在近lookback天的斜率"""
    ma = nav.rolling(window=window, min_periods=1).mean()
    if len(ma) < lookback + 1:
        return 0.0
    recent = ma.tail(lookback + 1)
    return float((recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0])

def calc_all_signals_for_fund(code: str) -> pd.DataFrame:
    """计算一只基金的全部技术信号并保存"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, unit_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date",
        (code,)
    ).fetchall()
    conn.close()

    if len(rows) < 20:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["date", "unit_nav", "daily_return"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")

    nav = df["unit_nav"]
    returns = df["daily_return"].fillna(0)

    df["ma5"] = calc_ma(nav, 5)
    df["ma20"] = calc_ma(nav, 20)
    df["ma60"] = calc_ma(nav, 60)
    df["ma120"] = calc_ma(nav, 120)

    macd = calc_macd(nav)
    df["macd_dif"] = macd["macd_dif"]
    df["macd_dea"] = macd["macd_dea"]
    df["macd_hist"] = macd["macd_hist"]

    df["rsi14"] = calc_rsi(nav, 14)

    bb = calc_bollinger(nav, 20)
    df["bb_upper"] = bb["bb_upper"]
    df["bb_mid"] = bb["bb_mid"]
    df["bb_lower"] = bb["bb_lower"]

    return df
```

- [ ] **Step 2: 验证指标计算**

```python
# 运行验证
# cd F:\基金\backend
# python -c "
from engine.indicators import calc_ma, calc_macd, calc_rsi, calc_max_drawdown
import pandas as pd
import numpy as np
np.random.seed(42)
nav = pd.Series(100 + np.cumsum(np.random.randn(200) * 0.5))
ma5 = calc_ma(nav, 5)
macd = calc_macd(nav)
rsi = calc_rsi(nav)
mdd = calc_max_drawdown(nav)
print(f'MA5[-1]: {ma5.iloc[-1]:.2f}, MACD_DIF[-1]: {macd["macd_dif"].iloc[-1]:.4f}, RSI[-1]: {rsi.iloc[-1]:.1f}, MaxDD: {mdd:.4f}')
print('指标计算 OK')
"
```

---

### Task 5: 技术信号评分 & 综合评分引擎

**Files:**
- Create: `F:\基金\backend\engine\signals.py`
- Create: `F:\基金\backend\engine\scorer.py`

- [ ] **Step 1: 创建 signals.py — 从指标到信号评分**

```python
import pandas as pd
import numpy as np

def score_ma_trend(row: dict) -> float:
    """均线趋势评分：多头排列满分，空头0分"""
    ma5 = row.get("ma5", 0) or 0
    ma20 = row.get("ma20", 0) or 0
    ma60 = row.get("ma60", 0) or 0
    score = 50
    if ma5 > ma20:
        score += 25
    if ma20 > ma60:
        score += 25
    return min(100, max(0, score))

def score_macd(row: dict) -> float:
    """MACD信号评分"""
    dif = row.get("macd_dif", 0) or 0
    dea = row.get("macd_dea", 0) or 0
    hist = row.get("macd_hist", 0) or 0
    score = 50
    if dif > dea:
        score += 20
    if hist > 0:
        score += 20
    if dif > 0:
        score += 10
    return min(100, max(0, score))

def score_rsi(rsi_val: float) -> float:
    """RSI评分：40~70最佳，>80超买，<30超卖"""
    if rsi_val is None or np.isnan(rsi_val):
        return 50
    if 40 <= rsi_val <= 70:
        return 80 + (rsi_val - 40) * 0.66
    elif rsi_val > 80:
        return max(0, 100 - (rsi_val - 80) * 5)
    elif rsi_val < 30:
        return max(0, rsi_val * 1.66)
    elif rsi_val > 70:
        return max(0, 100 - (rsi_val - 70) * 2)
    else:
        return max(0, 60 - (40 - rsi_val) * 1.5)

def score_bollinger(row: dict) -> float:
    """布林带位置评分：中轨附近偏上最佳"""
    nav = row.get("unit_nav", 0) or 0
    upper = row.get("bb_upper", 0) or 0
    mid = row.get("bb_mid", 0) or 0
    lower = row.get("bb_lower", 0) or 0
    if upper == 0 or lower == 0 or mid == 0:
        return 50
    if lower <= nav <= upper:
        pos = (nav - mid) / (upper - mid) if upper != mid else 0
        if -0.3 <= pos <= 0.5:
            return 80
        elif pos > 0.5:
            return 50 + (1 - pos) * 60
        else:
            return 50 + (pos + 1) * 30
    elif nav > upper:
        return 30
    else:
        return 40
```

- [ ] **Step 2: 创建 scorer.py — 主评分引擎**

```python
import pandas as pd
import numpy as np
from models.database import get_connection
from engine.indicators import (
    calc_period_return, calc_max_drawdown, calc_sharpe,
    calc_volatility, calc_calmar, calc_nav_deviation, calc_ma_slope
)
from engine.signals import score_ma_trend, score_macd, score_rsi, score_bollinger
from config import (
    SCORE_WEIGHTS_BUY, SCORE_WEIGHTS_AIP,
    SUB_WEIGHTS_BUY, SUB_WEIGHTS_AIP
)

def _get_fund_nav_data(code: str):
    """从数据库读取基金净值数据"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, unit_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date",
        (code,)
    ).fetchall()
    conn.close()
    if len(rows) < 60:
        return None
    df = pd.DataFrame(rows, columns=["date", "unit_nav", "daily_return"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce").fillna(0)
    return df

def _get_latest_signal(code: str):
    """获取最新的技术信号数据"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM fund_signal WHERE code=? ORDER BY date DESC LIMIT 1",
        (code,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}

def _percentile_rank(values: pd.Series, ascending: bool = True) -> pd.Series:
    """计算百分位排名 (0~100)"""
    return values.rank(ascending=ascending, pct=True) * 100

def score_one_fund_buy(code: str) -> dict:
    """一笔买入模式：对单只基金打分"""
    df = get_fund_nav_data(code)
    if df is None:
        return _empty_score("buy")

    nav = df["unit_nav"]
    returns = df["daily_return"]
    signal = _get_latest_signal(code)

    # ---- 收益指标 ----
    r1m = calc_period_return(nav, 22)
    r3m = calc_period_return(nav, 66)
    r6m = calc_period_return(nav, 132)
    r1y = calc_period_return(nav, 252)
    r3y = ((1 + calc_period_return(nav, 756)) ** (1/3) - 1) if len(nav) >= 756 else 0

    # ---- 估值指标 ----
    nav_dev = calc_nav_deviation(nav)
    dd_state = (nav.iloc[-1] / nav.rolling(60, min_periods=1).max().iloc[-1] - 1) if len(nav) >= 60 else 0

    # ---- 风控指标 ----
    max_dd = calc_max_drawdown(nav)
    sharpe = calc_sharpe(returns)
    vol = calc_volatility(returns)
    calmar = calc_calmar(nav, returns)

    # ---- 技术信号 ----
    ma_s = score_ma_trend(signal)
    macd_s = score_macd(signal)
    rsi_s = score_rsi(signal.get("rsi14", 50))
    bb_s = score_bollinger({**signal, "unit_nav": nav.iloc[-1] if len(nav) > 0 else 0})

    # 汇总
    raw = {
        "return_1m": r1m, "return_3m": r3m, "return_6m": r6m, "return_1y": r1y, "return_3y": r3y,
        "nav_deviation": nav_dev, "drawdown_state": abs(dd_state),
        "max_drawdown": abs(max_dd), "sharpe": sharpe, "volatility": vol, "calmar": calmar,
        "ma_trend": ma_s, "macd_signal": macd_s, "rsi": rsi_s, "bollinger": bb_s,
    }

    score = _weighted_sum(raw, SUB_WEIGHTS_BUY, SCORE_WEIGHTS_BUY)
    return {**score, "raw": raw}

def score_one_fund_aip(code: str) -> dict:
    """定投模式：对单只基金打分"""
    df = _get_fund_nav_data(code)
    if df is None:
        return _empty_score("aip")

    nav = df["unit_nav"]
    returns = df["daily_return"]

    # 长期趋势
    ma60_slope = calc_ma_slope(nav, 60, 20)
    ma120_slope = calc_ma_slope(nav, 120, 20)

    r1y = calc_period_return(nav, 252)
    r3y = ((1 + calc_period_return(nav, 756)) ** (1/3) - 1) if len(nav) >= 756 else 0
    nav_dev = calc_nav_deviation(nav)
    dd_state = (nav.iloc[-1] / nav.rolling(60, min_periods=1).max().iloc[-1] - 1)
    vol = calc_volatility(returns)
    max_dd = calc_max_drawdown(nav)
    sharpe = calc_sharpe(returns)

    raw = {
        "nav_deviation": nav_dev, "drawdown_state": abs(dd_state),
        "ma60_slope": ma60_slope, "ma120_slope": ma120_slope,
        "return_1y": r1y, "return_3y": r3y,
        "volatility": vol,
        "max_drawdown": abs(max_dd), "sharpe": sharpe,
    }

    score = _weighted_sum(raw, SUB_WEIGHTS_AIP, SCORE_WEIGHTS_AIP)
    return {**score, "raw": raw}

def _weighted_sum(raw: dict, sub_weights: dict, dim_weights: dict) -> dict:
    """加权求和计算总分及各维度分"""
    # 各维度得分
    dims = {}
    for dim, indicators in _dim_indicator_map().items():
        dim_score = 0
        dim_w_sum = 0
        for ind in indicators:
            w = sub_weights.get(ind, 0)
            v = raw.get(ind, 0) or 0
            dim_score += w * _normalize_to_score(ind, v)
            dim_w_sum += w
        dims[dim] = dim_score / dim_w_sum if dim_w_sum > 0 else 50

    total = sum(dims[d] * dim_weights.get(d, 0) for d in dims)
    return {
        "total_score": round(total, 2),
        "return_score": round(dims.get("return_", 50), 2),
        "valuation_score": round(dims.get("valuation", 50), 2),
        "risk_score": round(dims.get("risk", 50), 2),
        "fundamental_score": round(dims.get("fundamental", 50), 2),
        "technical_score": round(dims.get("technical", 50), 2),
    }

def _dim_indicator_map():
    return {
        "return_": ["return_1m", "return_3m", "return_6m", "return_1y", "return_3y"],
        "valuation": ["pe_percentile", "nav_deviation", "pb_percentile", "drawdown_state"],
        "risk": ["max_drawdown", "sharpe", "volatility", "calmar"],
        "fundamental": ["fund_scale", "fund_age", "manager_tenure", "fee_rate", "manager_return"],
        "technical": ["ma_trend", "macd_signal", "rsi", "bollinger"],
    }

def _normalize_to_score(indicator: str, value: float) -> float:
    """将原始指标值映射到0~100分"""
    # 正向指标（越高越好）
    if indicator in ("return_1m", "return_3m", "return_6m", "return_1y", "return_3y",
                     "sharpe", "calmar", "ma_trend", "macd_signal", "manager_return",
                     "ma60_slope", "ma120_slope"):
        return max(0, min(100, 50 + value * 100))
    # 反向指标（越低越好）
    if indicator in ("max_drawdown", "volatility", "fee_rate", "nav_deviation",
                     "drawdown_state"):
        return max(0, min(100, 100 - abs(value) * 200))
    # 已打分指标
    if indicator in ("rsi", "bollinger", "pe_percentile", "pb_percentile"):
        return max(0, min(100, value))
    # 区间最优
    if indicator in ("fund_scale",):
        # 2~50亿 最优
        if 2 <= value <= 50:
            return 100
        elif value < 2:
            return max(0, 100 - (2 - value) * 20)
        else:
            return max(0, 100 - (value - 50) * 2)
    if indicator in ("fund_age", "manager_tenure"):
        # 大于3年满分
        return min(100, value * 100 / 3)
    return 50

def _empty_score(mode: str) -> dict:
    return {
        "total_score": 0, "return_score": 0, "valuation_score": 0,
        "risk_score": 0, "fundamental_score": 0, "technical_score": 0,
        "raw": {}
    }
```

- [ ] **Step 3: 验证评分引擎**

```python
# cd F:\基金\backend
# python -c "
from engine.scorer import score_one_fund_buy, score_one_fund_aip
# 需要有实际数据才能测试，先验证导入无错误
print('评分引擎导入 OK')
"
```

---

### Task 6: 批量评分 & 排名服务

**Files:**
- Create: `F:\基金\backend\engine\rank.py`

- [ ] **Step 1: 创建 rank.py**

```python
import pandas as pd
import numpy as np
from datetime import datetime
from models.database import get_connection
from engine.scorer import score_one_fund_buy, score_one_fund_aip
from engine.indicators import calc_all_signals_for_fund
from config import TOP_N_DEFAULT

def update_signals():
    """批量更新所有基金的技术信号"""
    conn = get_connection()
    codes = [r["code"] for r in conn.execute("SELECT code FROM fund_basic").fetchall()]
    conn.close()

    total = len(codes)
    for i, code in enumerate(codes):
        df = calc_all_signals_for_fund(code)
        if df.empty:
            continue
        conn = get_connection()
        last = df.iloc[-1]
        try:
            conn.execute("""
                INSERT OR REPLACE INTO fund_signal
                (code, date, ma5, ma20, ma60, ma120, macd_dif, macd_dea, macd_hist, rsi14, bb_upper, bb_mid, bb_lower)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code, str(last["date"]),
                float(last.get("ma5", 0) or 0), float(last.get("ma20", 0) or 0),
                float(last.get("ma60", 0) or 0), float(last.get("ma120", 0) or 0),
                float(last.get("macd_dif", 0) or 0), float(last.get("macd_dea", 0) or 0),
                float(last.get("macd_hist", 0) or 0), float(last.get("rsi14", 50) or 50),
                float(last.get("bb_upper", 0) or 0), float(last.get("bb_mid", 0) or 0),
                float(last.get("bb_lower", 0) or 0),
            ))
        except Exception:
            pass
        conn.commit()
        conn.close()
        if (i + 1) % 50 == 0:
            print(f"  信号进度: {i+1}/{total}")
    print(f"信号更新完成: {total} 只")

def rank_all_funds(mode: str = "buy", fund_type_filter: str = None) -> list:
    """对所有基金评分并排名"""
    conn = get_connection()
    query = "SELECT code, fund_type FROM fund_basic WHERE 1=1"
    params = []
    if fund_type_filter:
        query += " AND fund_type=?"
        params.append(fund_type_filter)
    rows = conn.execute(query, params).fetchall()
    conn.close()

    results = []
    scorer = score_one_fund_buy if mode == "buy" else score_one_fund_aip

    for i, row in enumerate(rows):
        code = row["code"]
        fund_type = row["fund_type"]
        s = scorer(code)
        if s["total_score"] > 0:
            results.append({
                "code": code,
                "fund_type": fund_type,
                **{k: v for k, v in s.items() if k != "raw"},
            })
        if (i + 1) % 100 == 0:
            print(f"  评分进度: {i+1}/{len(rows)}")

    df = pd.DataFrame(results)
    if df.empty:
        return []

    # 分类别排名
    df["rank_in_type"] = df.groupby("fund_type")["total_score"].rank(ascending=False, method="min").astype(int)

    # 保存评分
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    for _, r in df.iterrows():
        conn.execute("""
            INSERT OR REPLACE INTO fund_score
            (code, calc_date, mode, total_score, return_score, valuation_score,
             risk_score, fundamental_score, technical_score, rank_in_type, fund_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["code"], today, mode, r["total_score"], r.get("return_score", 0), r.get("valuation_score", 0),
            r.get("risk_score", 0), r.get("fundamental_score", 0), r.get("technical_score", 0),
            r["rank_in_type"], r["fund_type"]
        ))
    conn.commit()
    conn.close()

    # 按总分降序返回
    df = df.sort_values("total_score", ascending=False)
    return df.to_dict(orient="records")

def get_top_funds(mode: str = "buy", fund_type: str = None, top_n: int = TOP_N_DEFAULT) -> list:
    """获取Top-N基金排名"""
    results = rank_all_funds(mode=mode, fund_type_filter=fund_type)
    return results[:top_n]

def get_fund_detail_with_score(code: str) -> dict:
    """获取单只基金的完整数据"""
    conn = get_connection()
    basic = conn.execute("SELECT * FROM fund_basic WHERE code=?", (code,)).fetchone()
    scores = conn.execute(
        "SELECT * FROM fund_score WHERE code=? ORDER BY calc_date DESC LIMIT 2",
        (code,)
    ).fetchall()
    signal = conn.execute(
        "SELECT * FROM fund_signal WHERE code=? ORDER BY date DESC LIMIT 1",
        (code,)
    ).fetchone()
    # 净值历史
    nav_rows = conn.execute(
        "SELECT date, unit_nav, acc_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date",
        (code,)
    ).fetchall()
    conn.close()

    return {
        "basic": dict(basic) if basic else {},
        "scores": [dict(s) for s in scores],
        "signal": dict(signal) if signal else {},
        "nav_history": [{"date": r["date"], "unit_nav": r["unit_nav"],
                         "acc_nav": r["acc_nav"], "daily_return": r["daily_return"]}
                        for r in nav_rows],
    }
```

- [ ] **Step 2: 验证排名模块可导入**

```powershell
cd F:\基金\backend; python -c "from engine.rank import rank_all_funds, get_top_funds; print('rank 模块 OK')"
```

---

### Task 7: 回测引擎

**Files:**
- Create: `F:\基金\backend\engine\backtest.py`

- [ ] **Step 1: 创建 backtest.py**

```python
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from models.database import get_connection
from engine.scorer import score_one_fund_buy, score_one_fund_aip
from engine.indicators import calc_sharpe, calc_max_drawdown
from config import TRAIN_TEST_SPLIT_DATE

def run_backtest(
    start_date: str,
    end_date: str,
    mode: str = "buy",
    rebalance_months: int = 3,
    top_n: int = 10,
    benchmark_code: str = "000300"
) -> dict:
    """执行策略回测"""
    conn = get_connection()
    codes = [r["code"] for r in conn.execute("SELECT code FROM fund_basic").fetchall()]
    conn.close()

    if not codes:
        return {"error": "无基金数据"}

    # 生成调仓日期
    rebalance_dates = _generate_rebalance_dates(start_date, end_date, rebalance_months)

    portfolio_values = []
    holdings = []

    for rb_date in rebalance_dates:
        # 用截止到该日期的数据评分
        ranked = _rank_funds_at_date(codes, rb_date, mode)
        selected = [r["code"] for r in ranked[:top_n]]

        if not selected:
            continue

        next_date = _get_next_rebalance_date(rb_date, rebalance_dates, end_date)
        period_return = _calc_period_portfolio_return(selected, rb_date, next_date)

        holdings.append({
            "date": rb_date,
            "funds": selected,
            "period_return": period_return,
        })

    # 计算组合累计收益曲线
    portfolio_curve = _calc_portfolio_curve(holdings, start_date)
    bench_curve = _get_benchmark_curve(benchmark_code, start_date, end_date)

    # 计算核心指标
    metrics = _calc_backtest_metrics(portfolio_curve, bench_curve, start_date, end_date)

    # 保存记录
    _save_backtest_record(mode, start_date, end_date, rebalance_months, top_n,
                          metrics, benchmark_code)

    return {
        "metrics": metrics,
        "holdings": holdings[-20:],  # 最近20期持仓
        "portfolio_curve": portfolio_curve[-500:],  # 最近500天
        "benchmark_curve": bench_curve[-500:],
    }

def run_aip_backtest(
    start_date: str,
    end_date: str,
    monthly_amount: float = 1000,
    top_n: int = 5,
    benchmark_code: str = "000300"
) -> dict:
    """定投回测：每月固定金额投入"""
    conn = get_connection()
    codes = [r["code"] for r in conn.execute("SELECT code FROM fund_basic").fetchall()]
    conn.close()

    # 生成每月定投日期
    invest_dates = pd.date_range(start=start_date, end=end_date, freq="MS").strftime("%Y-%m-%d").tolist()
    if not invest_dates:
        return {"error": "无有效定投日期"}

    total_invested = 0
    total_shares = 0
    cash_flows = []

    for inv_date in invest_dates:
        # 每次定投前重新筛选Top-N
        ranked = _rank_funds_at_date(codes, inv_date, "aip")
        selected = [r["code"] for r in ranked[:top_n]]
        if not selected:
            continue

        amount_per_fund = monthly_amount / len(selected)
        period_shares = 0
        for code in selected:
            nav = _get_nav_at_date(code, inv_date)
            if nav and nav > 0:
                period_shares += amount_per_fund / nav

        total_invested += monthly_amount
        total_shares += period_shares
        cash_flows.append({
            "date": inv_date,
            "invested": monthly_amount,
            "cumulative_invested": total_invested,
            "shares_bought": period_shares,
            "cumulative_shares": total_shares,
        })

    # 计算最终市值
    final_value = 0
    for code in _get_latest_holdings(codes, top_n, end_date):
        nav = _get_nav_at_date(code, end_date)
        if nav:
            final_value += (total_shares / top_n) * nav

    total_return = (final_value - total_invested) / total_invested if total_invested > 0 else 0
    years = max(1, (pd.Timestamp(end_date) - pd.Timestamp(init_date)).days / 365)

    # 估算IRR
    irr = _calc_irr(invest_dates, [monthly_amount] * len(invest_dates), final_value)

    return {
        "total_invested": round(total_invested, 2),
        "final_value": round(final_value, 2),
        "total_return": round(total_return * 100, 2),
        "annual_return": round(((1 + total_return) ** (1 / years) - 1) * 100, 2) if total_return > -1 else 0,
        "irr": round(irr * 100, 2),
        "cash_flows": cash_flows[-24:],  # 最近24个月
    }

def _generate_rebalance_dates(start: str, end: str, months: int) -> list:
    dates = pd.date_range(start=start, end=end, freq=f"{months}MS")
    return [d.strftime("%Y-%m-%d") for d in dates]

def _get_next_rebalance_date(current: str, all_dates: list, end_date: str) -> str:
    idx = all_dates.index(current) if current in all_dates else -1
    if idx >= 0 and idx + 1 < len(all_dates):
        return all_dates[idx + 1]
    return end_date

def _rank_funds_at_date(codes: list, date: str, mode: str) -> list:
    """用截至某日期的历史数据评分（回测核心——不用未来数据）"""
    conn = get_connection()
    results = []
    for code in codes:
        rows = conn.execute(
            "SELECT unit_nav, daily_return FROM fund_nav WHERE code=? AND date<=? ORDER BY date",
            (code, date)
        ).fetchall()
        if len(rows) < 60:
            continue
        # 简化版评分：仅用收益和风控，避免未来函数
        nav_series = pd.Series([float(r["unit_nav"]) for r in rows])
        ret_series = pd.Series([float(r["daily_return"] or 0) for r in rows])

        r3m = float(nav_series.iloc[-1] / nav_series.iloc[-66] - 1) if len(nav_series) >= 66 else 0
        r1y = float(nav_series.iloc[-1] / nav_series.iloc[-252] - 1) if len(nav_series) >= 252 else 0
        max_dd = float((nav_series / nav_series.expanding().max() - 1).min())

        # 简单加权
        score = r3m * 0.3 + r1y * 0.3 + max_dd * (-0.2) + (ret_series.std() * np.sqrt(252)) * (-0.2)
        score = score * 100 + 50  # 归一化

        results.append({
            "code": code,
            "score": score,
        })

    conn.close()
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

def _calc_period_portfolio_return(codes: list, start: str, end: str) -> float:
    returns = []
    conn = get_connection()
    for code in codes:
        r1 = conn.execute("SELECT unit_nav FROM fund_nav WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
                          (code, start)).fetchone()
        r2 = conn.execute("SELECT unit_nav FROM fund_nav WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
                          (code, end)).fetchone()
        if r1 and r2 and r1["unit_nav"] and r1["unit_nav"] > 0:
            returns.append(float(r2["unit_nav"] / r1["unit_nav"] - 1))
    conn.close()
    return np.mean(returns) if returns else 0

def _calc_portfolio_curve(holdings: list, start_date: str) -> list:
    """从持仓记录构建净值曲线"""
    curve = []
    value = 1.0
    for h in holdings:
        value *= (1 + h["period_return"])
        curve.append({"date": h["date"], "value": round(value, 4)})
    return curve

def _get_benchmark_curve(code: str, start: str, end: str) -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE code=? AND date>=? AND date<=? ORDER BY date",
        (code, start, end)
    ).fetchall()
    conn.close()
    if not rows:
        return []
    base = rows[0]["close"]
    return [{"date": r["date"], "value": round(r["close"] / base, 4)} for r in rows]

def _calc_backtest_metrics(portfolio_curve: list, bench_curve: list,
                           start: str, end: str) -> dict:
    if not portfolio_curve:
        return {}
    p_vals = pd.Series([p["value"] for p in portfolio_curve])
    total_return = float(p_vals.iloc[-1] / p_vals.iloc[0] - 1)
    days = (pd.Timestamp(end) - pd.Timestamp(start)).days
    annual_return = (1 + total_return) ** (365 / max(days, 1)) - 1
    max_dd = float((p_vals / p_vals.expanding().max() - 1).min())

    daily_ret = p_vals.pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0

    # vs 基准
    b_vals = pd.Series([b["value"] for b in bench_curve]) if bench_curve else pd.Series([1])
    bench_return = float(b_vals.iloc[-1] / b_vals.iloc[0] - 1) if len(b_vals) > 1 else 0
    alpha = annual_return - bench_return

    # 胜率
    win_rate = float((daily_ret > 0).mean()) if len(daily_ret) > 0 else 0

    return {
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2),
        "win_rate": round(win_rate * 100, 1),
        "alpha": round(alpha * 100, 1),
        "info_ratio": round((annual_return - bench_return) / (daily_ret.std() * np.sqrt(252)), 2) if daily_ret.std() > 0 else 0,
        "benchmark_return": round(bench_return * 100, 2),
    }

def _get_nav_at_date(code: str, date: str) -> float:
    conn = get_connection()
    row = conn.execute(
        "SELECT unit_nav FROM fund_nav WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
        (code, date)
    ).fetchone()
    conn.close()
    return float(row["unit_nav"]) if row and row["unit_nav"] else 0

def _get_latest_holdings(codes: list, top_n: int, date: str) -> list:
    ranked = _rank_funds_at_date(codes, date, "aip")
    return [r["code"] for r in ranked[:top_n]]

def _calc_irr(dates: list, amounts: list, final_value: float) -> float:
    """简单IRR估算"""
    if sum(amounts) == 0:
        return 0
    total_invested = sum(amounts)
    avg_years = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365
    avg_years = max(0.5, avg_years)
    return (final_value / total_invested) ** (1 / avg_years) - 1

def _save_backtest_record(mode, start, end, rebalance_months, top_n,
                          metrics, benchmark_code):
    conn = get_connection()
    conn.execute("""
        INSERT INTO backtest_record
        (strategy_name, mode, start_date, end_date, rebalance_months, top_n,
         total_return, annual_return, max_drawdown, sharpe, win_rate, alpha, info_ratio,
         benchmark_name, benchmark_return, params_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        f"{mode}_策略", mode, start, end, rebalance_months, top_n,
        metrics.get("total_return", 0), metrics.get("annual_return", 0),
        metrics.get("max_drawdown", 0), metrics.get("sharpe", 0),
        metrics.get("win_rate", 0), metrics.get("alpha", 0),
        metrics.get("info_ratio", 0),
        benchmark_code, metrics.get("benchmark_return", 0),
        str({"rebalance_months": rebalance_months, "top_n": top_n}),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()
```

- [ ] **Step 2: 验证回测模块可导入**

```powershell
cd F:\基金\backend; python -c "from engine.backtest import run_backtest, run_aip_backtest; print('backtest 模块 OK')"
```

---

### Task 8: API 路由

**Files:**
- Create: `F:\基金\backend\api\routes.py`
- Modify: `F:\基金\backend\main.py`

- [ ] **Step 1: 创建 API 路由 routes.py**

```python
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from engine.rank import rank_all_funds, get_top_funds, get_fund_detail_with_score, update_signals
from engine.backtest import run_backtest, run_aip_backtest
from engine.scorer import score_one_fund_buy, score_one_fund_aip
from models.database import get_connection
from config import TOP_N_DEFAULT, SCORE_WEIGHTS_BUY, SCORE_WEIGHTS_AIP

router = APIRouter(prefix="/api")

# ---- 筛选 & 排名 ----

@router.get("/funds/top")
def api_top_funds(
    mode: str = Query("buy", regex="^(buy|aip)$"),
    fund_type: Optional[str] = None,
    top_n: int = TOP_N_DEFAULT,
    refresh: bool = False,
):
    """获取Top-N基金排名"""
    if refresh:
        update_signals()
    results = get_top_funds(mode=mode, fund_type=fund_type, top_n=top_n)
    return {"count": len(results), "mode": mode, "results": results}

@router.get("/funds/rank")
def api_rank_all(
    mode: str = Query("buy", regex="^(buy|aip)$"),
    fund_type: Optional[str] = None,
    refresh: bool = False,
):
    """全量排名"""
    if refresh:
        update_signals()
    results = rank_all_funds(mode=mode, fund_type_filter=fund_type)
    return {"count": len(results), "results": results}

# ---- 基金详情 ----

@router.get("/funds/{code}")
def api_fund_detail(code: str):
    """单只基金详情"""
    data = get_fund_detail_with_score(code)
    if not data.get("basic"):
        raise HTTPException(404, "基金不存在")
    return data

@router.get("/funds/{code}/score")
def api_fund_score(code: str, mode: str = Query("buy", regex="^(buy|aip)$")):
    """实时计算单只基金评分"""
    if mode == "buy":
        score = score_one_fund_buy(code)
    else:
        score = score_one_fund_aip(code)
    return {"code": code, "mode": mode, **score}

# ---- 回测 ----

@router.get("/backtest")
def api_backtest(
    start_date: str = Query("2022-01-01"),
    end_date: str = Query("2025-12-31"),
    mode: str = Query("buy", regex="^(buy|aip)$"),
    rebalance_months: int = Query(3, ge=1, le=12),
    top_n: int = Query(10, ge=1, le=50),
):
    """执行回测"""
    result = run_backtest(
        start_date=start_date,
        end_date=end_date,
        mode=mode,
        rebalance_months=rebalance_months,
        top_n=top_n,
    )
    return result

@router.get("/backtest/aip")
def api_aip_backtest(
    start_date: str = Query("2022-01-01"),
    end_date: str = Query("2025-12-31"),
    monthly_amount: float = Query(1000, ge=100),
    top_n: int = Query(5, ge=1, le=20),
):
    """定投回测"""
    result = run_aip_backtest(
        start_date=start_date,
        end_date=end_date,
        monthly_amount=monthly_amount,
        top_n=top_n,
    )
    return result

# ---- 配置 ----

@router.get("/config/weights")
def api_get_weights():
    """获取当前权重配置"""
    return {
        "buy": SCORE_WEIGHTS_BUY,
        "aip": SCORE_WEIGHTS_AIP,
    }

# ---- 概览统计 ----

@router.get("/stats")
def api_stats():
    """系统概览统计"""
    conn = get_connection()
    fund_count = conn.execute("SELECT COUNT(*) FROM fund_basic").fetchone()[0]
    nav_count = conn.execute("SELECT COUNT(*) FROM fund_nav").fetchone()[0]
    latest_score_date = conn.execute(
        "SELECT MAX(calc_date) FROM fund_score"
    ).fetchone()[0]
    backtest_count = conn.execute("SELECT COUNT(*) FROM backtest_record").fetchone()[0]
    conn.close()
    return {
        "fund_count": fund_count,
        "nav_records": nav_count,
        "latest_score_date": latest_score_date,
        "backtest_count": backtest_count,
    }
```

- [ ] **Step 2: 更新 main.py 注册路由**

```python
# main.py 在 app 定义之后添加:
from api.routes import router
app.include_router(router)
```

完整 main.py：
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.database import init_db
from scheduler import start_scheduler
from api.routes import router

app = FastAPI(title="基金筛选系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.on_event("startup")
def startup():
    init_db()
    start_scheduler()

@app.get("/api/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

- [ ] **Step 3: 验证 API 可启动**

```powershell
cd F:\基金\backend; python -c "from main import app; print('FastAPI 应用创建成功，路由数:', len(app.routes))"
```

---

### Task 9: 前端项目初始化 & 筛选页面

**Files:**
- Create: `F:\基金\frontend\index.html`
- Create: `F:\基金\frontend\app.js`
- Create: `F:\基金\frontend\style.css`

前端采用**极简单文件方案**：一个 HTML + 原生 JS + ECharts CDN，无需 Vue CLI/npm 构建，直接双击打开或 nginx 代理。

- [ ] **Step 1: 创建 index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>基金筛选系统</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div id="app">
        <!-- 导航 -->
        <nav class="nav">
            <h1>📊 基金筛选系统</h1>
            <div class="nav-tabs">
                <button class="tab active" data-page="screening">基金筛选</button>
                <button class="tab" data-page="detail">基金详情</button>
                <button class="tab" data-page="backtest">回测报告</button>
                <button class="tab" data-page="config">策略配置</button>
            </div>
        </nav>

        <!-- 页面内容 -->
        <main id="page-content">
            <!-- 由 JS 动态渲染 -->
        </main>
    </div>
    <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 创建 style.css**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f5f7fa; color: #333; }
.nav { background: #1a1a2e; color: white; padding: 12px 24px; display: flex; align-items: center; gap: 24px; }
.nav h1 { font-size: 18px; }
.nav-tabs { display: flex; gap: 8px; }
.tab { background: transparent; color: #aaa; border: none; padding: 8px 16px; cursor: pointer; border-radius: 6px; font-size: 14px; }
.tab.active { background: #16213e; color: white; }
.tab:hover { color: white; }

main { max-width: 1400px; margin: 16px auto; padding: 0 16px; }

/* 筛选栏 */
.filter-bar { background: white; border-radius: 8px; padding: 16px; margin-bottom: 16px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.filter-bar label { font-size: 13px; color: #666; }
.filter-bar select, .filter-bar input { padding: 6px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; }
.btn { padding: 8px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500; }
.btn-primary { background: #4CAF50; color: white; }
.btn-primary:hover { background: #43A047; }
.btn-warning { background: #FF9800; color: white; }
.btn-sm { padding: 4px 10px; font-size: 12px; }

/* 表格 */
.data-table { width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.data-table th { background: #f5f5f5; padding: 10px 12px; text-align: left; font-size: 12px; font-weight: 600; color: #666; border-bottom: 2px solid #eee; }
.data-table td { padding: 8px 12px; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.data-table tr:hover { background: #fafafa; }
.rank-1 { color: #FF9800; font-weight: bold; }
.score-high { color: #4CAF50; font-weight: bold; }
.score-low { color: #f44336; }

/* 详情页 */
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.card { background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.card h3 { font-size: 15px; margin-bottom: 12px; color: #333; }
.chart-container { width: 100%; height: 350px; }

/* 指标卡片 */
.metrics-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.metric-card { flex: 1; min-width: 120px; background: white; border-radius: 8px; padding: 14px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.metric-card .label { font-size: 11px; color: #888; margin-bottom: 4px; }
.metric-card .value { font-size: 22px; font-weight: bold; }
.value-green { color: #4CAF50; }
.value-red { color: #f44336; }
.value-orange { color: #FF9800; }

/* 加载状态 */
.loading { text-align: center; padding: 40px; color: #999; }
.error { text-align: center; padding: 40px; color: #f44336; }
.empty { text-align: center; padding: 60px; color: #bbb; font-size: 14px; }

/* 配置页 */
.config-section { background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.weight-slider { display: flex; align-items: center; gap: 12px; margin: 8px 0; }
.weight-slider input[type=range] { flex: 1; }
.weight-slider .dim-label { width: 80px; font-size: 13px; }
.weight-slider .dim-value { width: 40px; text-align: center; font-weight: bold; font-size: 14px; }

@media (max-width: 768px) {
    .nav { flex-direction: column; gap: 8px; }
    .detail-grid { grid-template-columns: 1fr; }
    .filter-bar { flex-direction: column; align-items: stretch; }
}
```

- [ ] **Step 3: 创建 app.js**

```javascript
// API 基础地址
const API_BASE = "http://localhost:8000/api";

// ========== 页面路由 ==========
document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        const page = tab.dataset.page;
        if (page === "screening") renderScreening();
        else if (page === "detail") renderDetail();
        else if (page === "backtest") renderBacktest();
        else if (page === "config") renderConfig();
    });
});

// ========== API 工具 ==========
async function api(path) {
    try {
        const res = await fetch(API_BASE + path);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        console.error(e);
        return null;
    }
}

function formatPct(v) {
    if (v === undefined || v === null) return "-";
    return (v > 0 ? "+" : "") + v.toFixed(2) + "%";
}

// ========== 筛选页面 ==========
async function renderScreening() {
    const main = document.getElementById("page-content");
    main.innerHTML = `
        <div class="filter-bar">
            <label>模式：</label>
            <select id="filter-mode">
                <option value="buy">一笔买入</option>
                <option value="aip">定投筛选</option>
            </select>
            <label>类型：</label>
            <select id="filter-type">
                <option value="">全部</option>
                <option value="股票型">股票型</option>
                <option value="混合型">混合型</option>
                <option value="指数型">指数型</option>
                <option value="债券型">债券型</option>
            </select>
            <label>Top-N：</label>
            <input type="number" id="filter-topn" value="20" min="5" max="100" style="width:70px;">
            <button class="btn btn-primary" onclick="doScreening()">🔍 开始筛选</button>
            <span id="filter-status" style="margin-left:8px;font-size:12px;color:#888;"></span>
        </div>
        <div id="screening-results">
            <div class="empty">点击"开始筛选"获取基金排名</div>
        </div>
    `;
}

async function doScreening() {
    const mode = document.getElementById("filter-mode").value;
    const type = document.getElementById("filter-type").value;
    const topn = document.getElementById("filter-topn").value;
    const status = document.getElementById("filter-status");

    status.textContent = "⏳ 正在计算评分...";
    document.getElementById("screening-results").innerHTML = '<div class="loading">正在计算中，请稍候...</div>';

    let url = `/funds/top?mode=${mode}&top_n=${topn}&refresh=true`;
    if (type) url += `&fund_type=${encodeURIComponent(type)}`;

    const data = await api(url);
    status.textContent = data ? `✅ 完成，共 ${data.count} 只` : "❌ 请求失败";
    if (!data || !data.results.length) {
        document.getElementById("screening-results").innerHTML = '<div class="empty">暂无数据，请先运行数据初始化</div>';
        return;
    }

    const headers = ["排名", "代码", "名称", "类型", "总分", "收益", "估值", "风控", "基本面", "技术"];
    const keys = ["rank_in_type", "code", "name", "fund_type", "total_score", "return_score", "valuation_score", "risk_score", "fundamental_score", "technical_score"];

    let html = '<table class="data-table"><thead><tr>' + headers.map(h => `<th>${h}</th>`).join("") + '</tr></thead><tbody>';

    data.results.forEach((r, i) => {
        html += '<tr>';
        html += `<td><span class="${i < 3 ? 'rank-1' : ''}">${i + 1}</span></td>`;
        html += `<td><a href="#" onclick="showFundDetail('${r.code}')" class="btn btn-sm btn-warning">${r.code}</a></td>`;
        html += `<td>${r.name || '-'}</td>`;
        html += `<td>${r.fund_type || '-'}</td>`;
        html += `<td class="score-high">${r.total_score?.toFixed(1) || '-'}</td>`;
        html += `<td>${r.return_score?.toFixed(1) || '-'}</td>`;
        html += `<td>${r.valuation_score?.toFixed(1) || '-'}</td>`;
        html += `<td>${r.risk_score?.toFixed(1) || '-'}</td>`;
        html += `<td>${r.fundamental_score?.toFixed(1) || '-'}</td>`;
        html += `<td>${r.technical_score?.toFixed(1) || '-'}</td>`;
        html += '</tr>';
    });

    html += '</tbody></table>';
    document.getElementById("screening-results").innerHTML = html;
}

// 全局函数暴露
window.doScreening = doScreening;
window.showFundDetail = showFundDetail;

// ========== 详情页 ==========
function showFundDetail(code) {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelector('[data-page="detail"]').classList.add("active");
    renderDetail(code);
}

async function renderDetail(code) {
    const main = document.getElementById("page-content");
    if (!code) {
        main.innerHTML = `
            <div class="filter-bar">
                <label>基金代码：</label>
                <input type="text" id="detail-code" placeholder="输入6位基金代码" maxlength="6" style="width:120px;">
                <button class="btn btn-primary" onclick="showFundDetail(document.getElementById('detail-code').value)">查询</button>
            </div>
            <div class="empty">输入基金代码查看详情</div>
        `;
        return;
    }

    main.innerHTML = '<div class="loading">加载中...</div>';

    const data = await api(`/funds/${code}`);
    if (!data || !data.basic) {
        main.innerHTML = '<div class="error">基金不存在或数据为空</div>';
        return;
    }

    const b = data.basic;
    const scores = data.scores?.[0] || {};
    const signal = data.signal || {};

    main.innerHTML = `
        <div class="filter-bar">
            <span style="font-weight:bold;">${b.code} — ${b.name}</span>
            <span style="color:#888;">${b.fund_type || '-'} | ${b.company || '-'} | 规模 ${(b.scale||0).toFixed(1)}亿</span>
        </div>

        <div class="metrics-row">
            <div class="metric-card"><div class="label">综合评分</div><div class="value value-green">${scores.total_score?.toFixed(1) || '-'}</div></div>
            <div class="metric-card"><div class="label">同类排名</div><div class="value value-orange">#${scores.rank_in_type || '-'}</div></div>
            <div class="metric-card"><div class="label">收益分</div><div class="value">${scores.return_score?.toFixed(1) || '-'}</div></div>
            <div class="metric-card"><div class="label">估值分</div><div class="value">${scores.valuation_score?.toFixed(1) || '-'}</div></div>
            <div class="metric-card"><div class="label">风控分</div><div class="value">${scores.risk_score?.toFixed(1) || '-'}</div></div>
            <div class="metric-card"><div class="label">基本面分</div><div class="value">${scores.fundamental_score?.toFixed(1) || '-'}</div></div>
            <div class="metric-card"><div class="label">技术分</div><div class="value">${scores.technical_score?.toFixed(1) || '-'}</div></div>
        </div>

        <div class="detail-grid">
            <div class="card">
                <h3>基本信息</h3>
                <table style="width:100%;font-size:13px;">
                    <tr><td style="color:#888;padding:4px 0;">基金经理</td><td>${b.manager_name || '-'}</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">任职天数</td><td>${b.manager_tenure_days || 0}天</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">成立日期</td><td>${b.establish_date || '-'}</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">管理费率</td><td>${(b.fee_mgmt||0).toFixed(2)}%</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">托管费率</td><td>${(b.fee_custody||0).toFixed(2)}%</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">业绩基准</td><td>${b.benchmark || '-'}</td></tr>
                </table>
            </div>
            <div class="card">
                <h3>技术信号</h3>
                <table style="width:100%;font-size:13px;">
                    <tr><td style="color:#888;padding:4px 0;">MA5/MA20/MA60</td><td>${signal.ma5?.toFixed(4)||'-'} / ${signal.ma20?.toFixed(4)||'-'} / ${signal.ma60?.toFixed(4)||'-'}</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">MACD DIF/DEA</td><td>${signal.macd_dif?.toFixed(4)||'-'} / ${signal.macd_dea?.toFixed(4)||'-'}</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">RSI(14)</td><td style="color:${(signal.rsi14||50)>70?'#f44336':(signal.rsi14||50)<30?'#4CAF50':'#333'}">${signal.rsi14?.toFixed(1)||'-'}</td></tr>
                    <tr><td style="color:#888;padding:4px 0;">布林上/中/下</td><td>${signal.bb_upper?.toFixed(4)||'-'} / ${signal.bb_mid?.toFixed(4)||'-'} / ${signal.bb_lower?.toFixed(4)||'-'}</td></tr>
                </table>
            </div>
        </div>

        <div class="card" style="margin-bottom:16px;">
            <h3>净值走势</h3>
            <div id="nav-chart" class="chart-container"></div>
        </div>
    `;

    // 画净值走势图
    const navHistory = data.nav_history || [];
    if (navHistory.length > 0) {
        const chart = echarts.init(document.getElementById("nav-chart"));
        chart.setOption({
            tooltip: { trigger: "axis" },
            xAxis: { type: "category", data: navHistory.map(r => r.date), show: false },
            yAxis: { type: "value", name: "净值", scale: true },
            series: [{
                name: b.name || code,
                type: "line",
                data: navHistory.map(r => r.unit_nav),
                smooth: true,
                showSymbol: false,
                lineStyle: { color: "#4CAF50", width: 1.5 },
                areaStyle: { color: "rgba(76,175,80,0.1)" },
            }],
            grid: { left: 60, right: 20, top: 20, bottom: 30 },
        });
        window.addEventListener("resize", () => chart.resize());
    }
}

// ========== 回测页面 ==========
async function renderBacktest() {
    const main = document.getElementById("page-content");
    main.innerHTML = `
        <div class="filter-bar">
            <label>模式：</label><select id="bt-mode"><option value="buy">一笔买入</option><option value="aip">定投</option></select>
            <label>起始：</label><input type="date" id="bt-start" value="2022-01-01">
            <label>结束：</label><input type="date" id="bt-end" value="2025-12-31">
            <label>调仓周期(月)：</label><input type="number" id="bt-rebalance" value="3" min="1" max="12" style="width:60px;">
            <label>Top-N：</label><input type="number" id="bt-topn" value="10" min="1" max="50" style="width:60px;">
            <button class="btn btn-primary" onclick="doBacktest()">▶ 运行回测</button>
            <span id="bt-status" style="font-size:12px;color:#888;"></span>
        </div>
        <div id="backtest-results">
            <div class="empty">设置参数后点击"运行回测"</div>
        </div>
    `;
}

async function doBacktest() {
    const mode = document.getElementById("bt-mode").value;
    const start = document.getElementById("bt-start").value;
    const end = document.getElementById("bt-end").value;
    const reb = document.getElementById("bt-rebalance").value;
    const topn = document.getElementById("bt-topn").value;
    const status = document.getElementById("bt-status");

    status.textContent = "⏳ 回测运行中...";

    let url = `/backtest?mode=${mode}&start_date=${start}&end_date=${end}&rebalance_months=${reb}&top_n=${topn}`;
    const data = await api(url);

    status.textContent = data && !data.error ? "✅ 完成" : "❌ 失败";
    if (!data || data.error) {
        document.getElementById("backtest-results").innerHTML = `<div class="error">${data?.error || '回测失败'}</div>`;
        return;
    }

    const m = data.metrics;
    document.getElementById("backtest-results").innerHTML = `
        <div class="metrics-row">
            <div class="metric-card"><div class="label">累计收益</div><div class="value ${m.total_return>=0?'value-green':'value-red'}">${formatPct(m.total_return)}</div></div>
            <div class="metric-card"><div class="label">年化收益</div><div class="value ${m.annual_return>=0?'value-green':'value-red'}">${formatPct(m.annual_return)}</div></div>
            <div class="metric-card"><div class="label">最大回撤</div><div class="value value-red">${formatPct(m.max_drawdown)}</div></div>
            <div class="metric-card"><div class="label">夏普比率</div><div class="value ${m.sharpe>=1?'value-green':(m.sharpe>=0.5?'value-orange':'value-red')}">${m.sharpe}</div></div>
            <div class="metric-card"><div class="label">胜率</div><div class="value">${m.win_rate}%</div></div>
            <div class="metric-card"><div class="label">超额收益</div><div class="value ${m.alpha>=0?'value-green':'value-red'}">${formatPct(m.alpha)}</div></div>
            <div class="metric-card"><div class="label">信息比率</div><div class="value">${m.info_ratio}</div></div>
            <div class="metric-card"><div class="label">基准收益</div><div class="value">${formatPct(m.benchmark_return)}</div></div>
        </div>
        <div class="card"><h3>收益曲线（策略 vs 基准）</h3><div id="bt-chart" class="chart-container"></div></div>
    `;

    // 收益曲线图
    const pCurve = data.portfolio_curve || [];
    const bCurve = data.benchmark_curve || [];
    if (pCurve.length > 0) {
        const chart = echarts.init(document.getElementById("bt-chart"));
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { data: ["策略", "基准"] },
            xAxis: { type: "category", data: pCurve.map(p => p.date), show: false },
            yAxis: { type: "value", name: "净值" },
            series: [
                { name: "策略", type: "line", data: pCurve.map(p => p.value), smooth: true, showSymbol: false, lineStyle: { color: "#4CAF50", width: 2 } },
                { name: "基准", type: "line", data: bCurve.map(b => b.value), smooth: true, showSymbol: false, lineStyle: { color: "#ddd", width: 1.5 } },
            ],
            grid: { left: 60, right: 20, top: 40, bottom: 30 },
        });
        window.addEventListener("resize", () => chart.resize());
    }
}

window.doBacktest = doBacktest;

// ========== 配置页 ==========
async function renderConfig() {
    const main = document.getElementById("page-content");
    const data = await api("/config/weights");

    const buyW = data?.buy || {};
    const aipW = data?.aip || {};

    main.innerHTML = `
        <div class="config-section">
            <h3>📈 一笔买入模式 权重配置</h3>
            <p style="color:#888;font-size:12px;margin-bottom:12px;">当前值（修改需直接编辑 backend/config.py）</p>
            <div id="buy-weights"></div>
        </div>
        <div class="config-section">
            <h3>💵 定投模式 权重配置</h3>
            <p style="color:#888;font-size:12px;margin-bottom:12px;">当前值</p>
            <div id="aip-weights"></div>
        </div>
        <div class="config-section">
            <h3>⚙️ 其他参数</h3>
            <p style="font-size:13px;">修改参数请编辑 <code>backend/config.py</code> 后重启服务</p>
        </div>
    `;

    document.getElementById("buy-weights").innerHTML = Object.entries(buyW).map(([k, v]) =>
        `<div class="weight-slider"><span class="dim-label">${k}</span><input type="range" min="0" max="100" value="${(v*100).toFixed(0)}" disabled><span class="dim-value">${(v*100).toFixed(0)}%</span></div>`
    ).join("");

    document.getElementById("aip-weights").innerHTML = Object.entries(aipW).map(([k, v]) =>
        `<div class="weight-slider"><span class="dim-label">${k}</span><input type="range" min="0" max="100" value="${(v*100).toFixed(0)}" disabled><span class="dim-value">${(v*100).toFixed(0)}%</span></div>`
    ).join("");
}

// ========== 初始化 ==========
renderScreening();
```

- [ ] **Step 4: 验证前端可以打开**

```powershell
# 在 frontend 目录启动一个简单 HTTP 服务器
cd F:\基金\frontend; python -m http.server 3000
# 浏览器打开 http://localhost:3000
# 确认页面加载正常（API 后端未启动时会显示请求失败，这是预期行为）
```

---

### Task 10: 集成测试 & 端到端验证

- [ ] **Step 1: 启动后端服务**

```powershell
cd F:\基金\backend; python main.py
# 确认 http://localhost:8000/api/health 返回 {"status":"ok"}
```

- [ ] **Step 2: 测试 API 端点**

```powershell
# 测试健康检查
curl http://localhost:8000/api/health

# 测试统计接口
curl http://localhost:8000/api/stats

# 测试配置接口
curl http://localhost:8000/api/config/weights

# 测试筛选接口（需要已有数据）
curl "http://localhost:8000/api/funds/top?mode=buy&top_n=5"
```

- [ ] **Step 3: 运行数据初始化（可选，耗时较长）**

```powershell
cd F:\基金\backend; python -m scheduler
# 这将拉取全量基金列表和净值数据，预计30-60分钟
# 可在另一个终端运行，不影响系统开发
```

- [ ] **Step 4: 前端 + 后端联调**

```powershell
# 终端1: 后端
cd F:\基金\backend; python main.py

# 终端2: 前端
cd F:\基金\frontend; python -m http.server 3000

# 浏览器打开 http://localhost:3000
# 验证四个页面都能正常加载和交互
```

- [ ] **Step 5: 验证前端 CORS**

打开浏览器开发者工具 → Network → 检查 API 请求是否返回 200。如果 CORS 报错，确认后端 `main.py` 已配置 `CORSMiddleware`。

---

## 后续扩展方向（不在本期实施范围）

- PE/PB 历史分位数据自动采集（指数估值表）
- 用户自定义权重持久化到数据库
- 基金对比功能（多只基金并列比较）
- Excel/CSV 导出筛选结果
- 邮件/微信通知（评分变化、调仓提醒）
- Docker 一键部署
