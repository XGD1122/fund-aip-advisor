@echo off
chcp 65001 >nul
cd /d "F:\基金"

:: 使用 Anaconda Python
set PYTHON=F:\Anaconda\python.exe
set PIP=F:\Anaconda\Scripts\pip.exe

echo ========================================
echo    📊 指数基金定投决策系统 启动中...
echo    Python: %PYTHON%
echo ========================================
echo.

:: 检查 Python
if not exist "%PYTHON%" (
    echo ❌ 未找到 Python: %PYTHON%
    pause
    exit /b 1
)

:: 检查依赖
%PYTHON% -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo ⏳ 正在安装依赖...
    %PIP% install -r backend\requirements.txt -q
)

:: 杀掉旧端口进程
echo [1/3] 清理旧进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

:: 启动后端
echo [2/3] 启动后端 (端口 8000)...
start "基金系统-后端" /min %PYTHON% backend\main.py
timeout /t 2 /nobreak >nul

:: 等待后端就绪
echo        等待后端就绪...
set RETRY=0
:wait_backend
timeout /t 1 /nobreak >nul
set /a RETRY+=1
%PYTHON% -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=2)" >nul 2>&1
if errorlevel 1 (
    if %RETRY% LSS 30 goto wait_backend
    echo        ⚠️ 后端启动超时
) else (
    echo        ✅ 后端就绪
)

:: 启动前端
echo [3/3] 启动前端 (端口 3000)...
start "基金系统-前端" /min %PYTHON% -m http.server 3000 --directory frontend

:: 打开浏览器
timeout /t 1 /nobreak >nul
start http://localhost:3000

echo.
echo ========================================
echo    ✅ 系统启动完成！
echo    前端: http://localhost:3000
echo    后端: http://localhost:8000
echo    API文档: http://localhost:8000/docs
echo ========================================
echo.
echo    关闭"基金系统-后端"和"基金系统-前端"窗口即可停止
echo.
pause
