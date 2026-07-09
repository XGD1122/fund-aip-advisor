from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.database import init_db, get_connection
from datetime import datetime, timedelta
import time

app = FastAPI(title="指数基金买入推荐", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 简易缓存
_cache = {"data": None, "time": 0, "date": ""}
CACHE_TTL = 300  # 5分钟


@app.on_event("startup")
def startup():
    init_db()
    # 启动时检查数据是否过期，若过期后台自动刷新
    import threading

    def _auto_refresh_if_stale():
        try:
            conn = get_connection()
            row = conn.execute("SELECT MAX(date) FROM fund_signal").fetchone()
            latest = row[0] if row and row[0] else None
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

            need_refresh = False
            if latest is None or latest < yesterday:
                need_refresh = True
                reason = f"信号日期过期(最新: {latest})"
            else:
                # 只统计A类基金，因为Top20只用A类
                fund_count = conn.execute(
                    "SELECT COUNT(*) FROM fund_basic WHERE fund_type LIKE '指数型%' AND (name LIKE '%A' OR name LIKE '%A类')"
                ).fetchone()[0]
                signal_count = conn.execute(
                    "SELECT COUNT(*) FROM fund_signal WHERE date=?", (latest,)
                ).fetchone()[0]
                conn.close()
                coverage = signal_count / fund_count if fund_count > 0 else 0
                if coverage < 0.8:
                    need_refresh = True
                    reason = f"信号覆盖率仅 {coverage:.0%} ({signal_count}/{fund_count})"
                else:
                    print(f"[启动检查] 数据完整 ({latest}, 覆盖率 {coverage:.0%})，跳过刷新")
                    return

            print(f"[启动检查] {reason}，自动刷新...")
            from engine.top20 import refresh_daily
            refresh_daily()
            print("[启动检查] 刷新完成")
        except Exception as e:
            print(f"[启动检查] 刷新失败: {e}")

    threading.Thread(target=_auto_refresh_if_stale, daemon=True).start()


@app.get("/api/top20")
def api_top20(refresh: bool = False):
    """返回今日最值得买入的Top20基金（缓存5分钟）"""
    global _cache
    today = datetime.now().strftime("%Y-%m-%d")

    # 检查缓存：同一天、未过期、未强制刷新
    if not refresh and _cache["data"] is not None and _cache["date"] == today:
        if time.time() - _cache["time"] < CACHE_TTL:
            return _cache["data"]

    from engine.top20 import compute_top20

    results = compute_top20()

    conn = get_connection()
    row = conn.execute("SELECT MAX(date) FROM fund_nav").fetchone()
    conn.close()
    updated_at = row[0] if row else "未知"

    data = {
        "count": len(results),
        "updated_at": updated_at,
        "results": results,
    }

    # 存入缓存
    _cache = {"data": data, "time": time.time(), "date": today}
    return data


@app.get("/api/admin/refresh")
def api_admin_refresh():
    """手动触发完整数据刷新"""
    from engine.top20 import refresh_all_data
    refresh_all_data()
    return {"status": "ok", "message": "数据刷新完成"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
