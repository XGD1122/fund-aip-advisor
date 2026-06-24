"""指数基金定投决策系统 — 一键启动"""
import subprocess
import webbrowser
import time
import urllib.request
import os
import sys
import signal

BASE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE, "backend")
FRONTEND_DIR = os.path.join(BASE, "frontend")

print("=" * 50)
print("   📊 指数基金定投决策系统 启动中...")
print("=" * 50)

# 杀掉旧端口进程
print("\n[0/3] 清理旧进程...")
for port in [8000, 3000]:
    try:
        result = subprocess.run(
            f'netstat -ano | findstr ":{port}" | findstr "LISTENING"',
            shell=True, capture_output=True, text=True
        )
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 5:
                pid = parts[-1]
                subprocess.run(f"taskkill /f /pid {pid}", shell=True,
                               capture_output=True)
    except Exception:
        pass

# 1. 启动后端
print("\n[1/3] 启动后端服务 (端口 8000)...")
backend = subprocess.Popen(
    [sys.executable, "main.py"],
    cwd=BACKEND_DIR,
    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
)

# 2. 等待后端就绪
print("[2/3] 等待后端就绪...", end="", flush=True)
for i in range(30):
    try:
        urllib.request.urlopen("http://localhost:8000/api/health", timeout=2)
        print(" ✅")
        break
    except Exception:
        print(".", end="", flush=True)
        time.sleep(1)
else:
    print(" ⚠️ 超时，请手动检查")

# 3. 启动前端
print("[3/3] 启动前端服务 (端口 3000)...")
frontend = subprocess.Popen(
    [sys.executable, "-m", "http.server", "3000"],
    cwd=FRONTEND_DIR,
    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
)

time.sleep(0.5)

# 4. 打开浏览器
webbrowser.open("http://localhost:3000")

print("\n" + "=" * 50)
print("   ✅ 系统启动完成!")
print("   前端: http://localhost:3000")
print("   后端: http://localhost:8000")
print("   API文档: http://localhost:8000/docs")
print("=" * 50)
print("\n   按 Ctrl+C 停止所有服务")
print("   或直接关闭此窗口\n")

# 等待退出
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n正在停止服务...")
    backend.terminate()
    frontend.terminate()
    print("已停止")
