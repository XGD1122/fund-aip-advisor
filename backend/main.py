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
    # 延迟导入避免循环依赖
    from scheduler import start_scheduler
    start_scheduler()

    # 启动时检查数据是否过期，若过期则在后台自动刷新
    import threading
    def _auto_refresh_if_stale():
        from datetime import datetime, timedelta
        from models.database import get_connection
        try:
            conn = get_connection()
            row = conn.execute("SELECT MAX(date) FROM fund_signal").fetchone()
            conn.close()
            latest_signal = row[0] if row and row[0] else None
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            if latest_signal is None or latest_signal < yesterday:
                print(f"[启动检查] 信号数据过期(最新: {latest_signal})，自动刷新...")
                from engine.rank import refresh_all_data
                refresh_all_data()
                print("[启动检查] 数据刷新完成")
            else:
                print(f"[启动检查] 信号数据最新({latest_signal})，跳过刷新")
        except Exception as e:
            print(f"[启动检查] 刷新失败: {e}")
    threading.Thread(target=_auto_refresh_if_stale, daemon=True).start()


@app.get("/api/health")
def health():
    return {"status": "ok"}

# 注册路由（延迟导入）
from api.routes import router
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
