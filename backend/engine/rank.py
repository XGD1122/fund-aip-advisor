import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from models.database import get_connection
from engine.scorer import score_one_fund_buy, score_one_fund_aip
from engine.indicators import calc_all_signals_for_fund
from data.fetcher import fetch_fund_nav
from data.cleaner import clean_nav_data, save_nav_data
from config import TOP_N_DEFAULT, FUND_TYPE_FILTER, NAV_MAX_STALE_DAYS, NAV_MIN_RECORDS


def refresh_all_data():
    """增量刷新：多线程并发拉取过期基金的净值"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 1. 找出最新净值日期 < 昨天的基金（数据过期的）
    conn = get_connection()
    stale = conn.execute("""
        SELECT b.code FROM fund_basic b
        WHERE b.fund_type LIKE ?
        AND (SELECT MAX(date) FROM fund_nav WHERE code=b.code) < ?
        OR NOT EXISTS (SELECT 1 FROM fund_nav WHERE code=b.code)
    """, (FUND_TYPE_FILTER + "%", yesterday)).fetchall()
    conn.close()

    stale_codes = [r[0] for r in stale]
    total_funds = len(stale_codes)

    if total_funds == 0:
        print(f"[{datetime.now()}] 所有基金净值已是最新", flush=True)
        update_signals()
        return

    print(f"[{datetime.now()}] {total_funds} 只基金数据过期，{5}线程并发拉取...", flush=True)

    # 2. 多线程并发拉取
    fetched = [0]
    done = [0]
    lock = threading.Lock()

    def _fetch_one(code):
        df = fetch_fund_nav(code)
        if not df.empty:
            df = clean_nav_data(df)
            save_nav_data(df)
            with lock:
                fetched[0] += 1
        with lock:
            done[0] += 1
            if done[0] % 500 == 0:
                print(f"  进度: {done[0]}/{total_funds}", flush=True)
        return True

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_fetch_one, code) for code in stale_codes]
        for f in as_completed(futures):
            pass  # 所有结果在 _fetch_one 内部处理

    print(f"  净值更新完成: {fetched[0]}/{total_funds}", flush=True)

    # 3. 更新技术信号
    update_signals()
    print(f"[{datetime.now()}] 数据刷新完成", flush=True)


def update_signals():
    """批量更新指数型基金的技术信号"""
    conn = get_connection()
    codes = [r["code"] for r in conn.execute(
        "SELECT code FROM fund_basic WHERE fund_type LIKE ?", (FUND_TYPE_FILTER + "%",)
    ).fetchall()]
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
    """对指数型基金评分并排名（默认仅指数型，自动排除已停售/无净值基金）"""
    conn = get_connection()
    if fund_type_filter:
        query = "SELECT code, name, fund_type FROM fund_basic WHERE fund_type LIKE ?"
        params = [fund_type_filter + "%"]
    else:
        query = "SELECT code, name, fund_type FROM fund_basic WHERE fund_type LIKE ?"
        params = [FUND_TYPE_FILTER + "%"]

    all_rows = conn.execute(query, params).fetchall()
    all_codes = [r["code"] for r in all_rows]

    # 批量查询：只保留近期有净值更新的基金（排除已停售）
    from datetime import datetime, timedelta
    stale_date = (datetime.now() - timedelta(days=NAV_MAX_STALE_DAYS)).strftime("%Y-%m-%d")
    active_codes = set()
    for batch_start in range(0, len(all_codes), 500):
        batch = all_codes[batch_start:batch_start+500]
        placeholders = ",".join(["?"] * len(batch))
        active_rows = conn.execute(
            f"SELECT code FROM fund_nav WHERE code IN ({placeholders}) GROUP BY code HAVING MAX(date) >= ? AND COUNT(*) >= ?",
            (*batch, stale_date, NAV_MIN_RECORDS)
        ).fetchall()
        active_codes.update(r["code"] for r in active_rows)
    conn.close()

    # 过滤：只保留活跃基金
    rows = [r for r in all_rows if r["code"] in active_codes]
    excluded_count = len(all_rows) - len(rows)
    if excluded_count > 0:
        product_name = "定投" if mode == "aip" else "一笔买入"
        print(f"  已排除 {excluded_count} 只停售/无净值基金，剩余 {len(rows)} 只参与{product_name}排名")

    results = []
    scorer = score_one_fund_buy if mode == "buy" else score_one_fund_aip

    for i, row in enumerate(rows):
        code = row["code"]
        fund_type = row["fund_type"]
        name = row["name"]
        s = scorer(code)
        if s["total_score"] > 0:
            entry = {
                "code": code,
                "name": name,
                "fund_type": fund_type,
                "total_score": s["total_score"],
                "return_score": s["return_score"],
                "valuation_score": s["valuation_score"],
                "risk_score": s["risk_score"],
                "fundamental_score": s["fundamental_score"],
                "technical_score": s["technical_score"],
                "tracking_score": s.get("tracking_score", 50),
                "nav_percentile_2y": s.get("nav_percentile_2y", 50),
                "tracking_error": s.get("tracking_error", 0),
            }
            if mode == "buy":
                entry["position_risk"] = s.get("position_risk", "")
                entry["high_warning"] = s.get("high_warning", False)
            else:
                entry["aip_rating"] = s.get("aip_rating", "")
                entry["trend_up"] = s.get("trend_up", False)
                entry["trend_warning"] = s.get("trend_warning", False)
                entry["trend_score"] = s.get("trend_score", 50)
                entry["volatility_score"] = s.get("volatility_score", 50)
            results.append(entry)

        if (i + 1) % 100 == 0:
            print(f"  评分进度: {i+1}/{len(rows)}")

    df = pd.DataFrame(results)
    if df.empty:
        return []

    # 分类别排名
    df["rank_in_type"] = df.groupby("fund_type")["total_score"].rank(ascending=False, method="min").astype(int)

    # 保存评分到数据库
    _save_scores_to_db(df, mode)

    # 按总分降序返回
    df = df.sort_values("total_score", ascending=False)
    return df.to_dict(orient="records")


def _save_scores_to_db(df: pd.DataFrame, mode: str):
    """保存评分结果到 fund_score 表"""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    # 确保 tracking_score 列存在
    try:
        conn.execute("ALTER TABLE fund_score ADD COLUMN tracking_score REAL DEFAULT 50")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE fund_score ADD COLUMN tracking_error REAL DEFAULT 0")
    except Exception:
        pass

    for _, r in df.iterrows():
        conn.execute("""
            INSERT OR REPLACE INTO fund_score
            (code, calc_date, mode, total_score, return_score, valuation_score,
             risk_score, fundamental_score, technical_score, tracking_score,
             tracking_error, rank_in_type, fund_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["code"], today, mode,
            float(r["total_score"]), float(r.get("return_score", 0)), float(r.get("valuation_score", 0)),
            float(r.get("risk_score", 0)), float(r.get("fundamental_score", 0)), float(r.get("technical_score", 0)),
            float(r.get("tracking_score", 50)), float(r.get("tracking_error", 0)),
            int(r["rank_in_type"]), r["fund_type"]
        ))
    conn.commit()
    conn.close()


def get_top_funds(mode: str = "buy", fund_type: str = None, top_n: int = TOP_N_DEFAULT) -> list:
    """获取Top-N指数基金排名"""
    results = rank_all_funds(mode=mode, fund_type_filter=fund_type)
    return results[:top_n]


def get_fund_detail_with_score(code: str) -> dict:
    """获取单只指数基金的完整数据（含复权净值）"""
    import numpy as np
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
    nav_rows = conn.execute(
        "SELECT date, unit_nav, acc_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date",
        (code,)
    ).fetchall()
    conn.close()

    # 计算复权净值：消除分红跳空
    nav_data = []
    adj_nav = None
    if nav_rows:
        first_nav = nav_rows[0]["unit_nav"] or 1.0
        cum_ret = 1.0
        for r in nav_rows:
            ret = r["daily_return"] or 0
            cum_ret *= (1 + ret)
            adj_nav = first_nav * cum_ret
            nav_data.append({
                "date": r["date"],
                "unit_nav": r["unit_nav"],
                "adj_nav": round(adj_nav, 4),  # 复权净值（不含分红跳空）
                "daily_return": r["daily_return"],
            })

    return {
        "basic": dict(basic) if basic else {},
        "scores": [dict(s) for s in scores],
        "signal": dict(signal) if signal else {},
        "nav_history": nav_data,
    }
