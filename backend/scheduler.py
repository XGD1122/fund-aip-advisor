from datetime import datetime
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from data.fetcher import fetch_all_fund_list, fetch_fund_nav, fetch_fund_detail, fetch_benchmark_index
from data.cleaner import clean_nav_data, save_fund_list, save_nav_data
from models.database import get_connection

scheduler = BackgroundScheduler()


def job_fetch_fund_list():
    """每周拉取指数型基金列表"""
    print(f"[{datetime.now()}] 拉取指数型基金列表...")
    df = fetch_all_fund_list()
    if not df.empty:
        save_fund_list(df)
        print(f"  指数型基金列表更新: {len(df)} 只")


def job_fetch_nav_daily():
    """每日拉取指数型基金净值数据"""
    print(f"[{datetime.now()}] 拉取净值数据...")
    conn = get_connection()
    codes = [r["code"] for r in conn.execute(
        "SELECT code FROM fund_basic WHERE fund_type LIKE '指数型%'"
    ).fetchall()]
    conn.close()

    count = 0
    total = len(codes)
    for code in codes:
        df = fetch_fund_nav(code)
        if not df.empty:
            df = clean_nav_data(df)
            save_nav_data(df)
            count += 1
            if count % 50 == 0:
                print(f"  已拉取 {count}/{total} 只基金净值")
    print(f"  净值更新完成: {count}/{total}")


def job_fetch_benchmark():
    """每日拉取基准指数（用于回测对比）"""
    print(f"[{datetime.now()}] 拉取基准指数数据...")
    benchmarks = [
        ("000300", "沪深300"),
        ("000905", "中证500"),
    ]
    for idx_code, name in benchmarks:
        df = fetch_benchmark_index(idx_code, name)
        if not df.empty:
            conn = get_connection()
            for _, row in df.iterrows():
                conn.execute("""
                    INSERT OR IGNORE INTO index_daily (code, date, close)
                    VALUES (?, ?, ?)
                """, (idx_code, str(row["date"]), float(row["close"])))
            conn.commit()
            conn.close()
    print("  基准指数数据更新完成")


def init_data():
    """首次运行：拉取指数型基金（排除联接），不逐只拉详情，由评分体系自然淘汰"""
    from datetime import datetime as dt
    print(f"[{datetime.now()}] 首次数据初始化（指数型基金，排除联接，其余由评分淘汰）...", flush=True)

    # 确保 index_daily 表存在
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

    # 1. 拉取指数型基金列表
    df_list = fetch_all_fund_list()
    if df_list.empty:
        print("  ⚠️ 未获取到指数型基金列表", flush=True)
        return
    print(f"  指数型基金总数: {len(df_list)} 只", flush=True)

    # 2. 名称过滤：排除联接基金
    before = len(df_list)
    df_list = df_list[~df_list["name"].str.contains("联接", na=False)]
    print(f"  排除联接: {before - len(df_list)} 只 → 剩余 {len(df_list)} 只", flush=True)

    # 3. 保存到数据库（基本面字段用默认值，后续可增量更新）
    conn = get_connection()
    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    for _, row in df_list.iterrows():
        conn.execute("""
            INSERT OR REPLACE INTO fund_basic
            (code, name, fund_type, establish_date, company, manager_name,
             manager_tenure_days, scale, fee_mgmt, fee_custody, benchmark, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["code"], row["name"], row["fund_type"],
            "", "", "", 0, 0, 0, 0, "", today_str,
        ))
    conn.commit()
    conn.close()
    print(f"  基金列表已保存: {len(df_list)} 只", flush=True)

    # 4. 拉取净值
    codes = df_list["code"].tolist()
    total = len(codes)
    print(f"  正在拉取净值数据...", flush=True)
    for i, code in enumerate(codes):
        df = fetch_fund_nav(code)
        if not df.empty:
            df = clean_nav_data(df)
            save_nav_data(df)
        if (i + 1) % 100 == 0:
            print(f"  净值进度: {i+1}/{total}", flush=True)

    # 5. 拉取基准指数
    job_fetch_benchmark()

    print(f"[{datetime.now()}] 数据初始化完成！基金: {len(df_list)} 只", flush=True)


def start_scheduler():
    scheduler.add_job(job_fetch_nav_daily, "cron", hour=18, minute=30, id="nav_daily")
    scheduler.add_job(job_fetch_fund_list, "cron", day_of_week="sat", hour=8, minute=0, id="fund_list_weekly")
    scheduler.add_job(job_fetch_benchmark, "cron", hour=18, minute=0, id="benchmark_daily")
    scheduler.start()
    print("定时任务已启动")


if __name__ == "__main__":
    from models.database import init_db
    init_db()
    init_data()
