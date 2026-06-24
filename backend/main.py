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


@app.get("/api/health")
def health():
    return {"status": "ok"}

# 注册路由（延迟导入）
from api.routes import router
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
