import sqlite3
from config import DB_PATH, DATA_DIR
import os


def get_connection():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
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
            tracking_score REAL DEFAULT 50,
            tracking_error REAL DEFAULT 0,
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT,
            buy_date TEXT NOT NULL,
            buy_nav REAL NOT NULL,
            shares REAL DEFAULT 0,
            buy_amount REAL DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            total_value REAL,
            total_invested REAL,
            holdings_json TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_nav_code_date ON fund_nav(code, date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_score_date ON fund_score(calc_date, mode)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_signal_code_date ON fund_signal(code, date)")

    # 迁移：为已有数据库添加新列
    _migrate_columns(cur)

    conn.commit()
    conn.close()


def _migrate_columns(cur):
    """为已有数据库添加新增列（如果不存在）"""
    migrations = [
        ("fund_score", "tracking_score", "REAL DEFAULT 50"),
        ("fund_score", "tracking_error", "REAL DEFAULT 0"),
        # 新增技术指标字段
        ("fund_signal", "kdj_k", "REAL"),
        ("fund_signal", "kdj_d", "REAL"),
        ("fund_signal", "kdj_j", "REAL"),
        ("fund_signal", "bb_width", "REAL"),
        ("fund_signal", "atr14", "REAL"),
        ("fund_signal", "ma60_slope", "REAL"),
        # 持仓卖出功能
        ("portfolio", "status", "TEXT DEFAULT 'active'"),
        ("portfolio", "sell_date", "TEXT"),
        ("portfolio", "sell_nav", "REAL"),
    ]
    for table, column, col_def in migrations:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        except Exception:
            pass  # 列已存在则跳过


if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化: {DB_PATH}")
