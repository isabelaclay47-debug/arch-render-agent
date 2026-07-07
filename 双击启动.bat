@echo off
chcp 65001 >nul
title 建筑渲染智能体
cd /d "%~dp0"

echo ============================================
echo    建筑渲染智能体  一键启动
echo ============================================
echo.

REM ---- 1) 找 Python ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo [缺少 Python] 没检测到 Python。
  echo 正在打开下载页，请安装 Python 3.10 以上版本
  echo 安装时务必勾选 "Add Python to PATH"，装完再双击本文件。
  start "" https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

REM ---- 2) 虚拟环境 + 依赖（首次较慢，1-3 分钟）----
if not exist ".venv-win\Scripts\python.exe" (
  echo 首次运行：正在创建虚拟环境并安装依赖，请耐心等待...
  %PY% -m venv .venv-win || ( echo 创建虚拟环境失败。 & pause & exit /b 1 )
  ".venv-win\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
  ".venv-win\Scripts\python.exe" -m pip install -r requirements.txt || ( echo 依赖安装失败，请检查网络后重试。 & pause & exit /b 1 )
) else (
  ".venv-win\Scripts\python.exe" -m pip install -r requirements.txt >nul 2>nul
)

REM ---- 3) 打开带调试端口的专用 Chrome（首次请登录 chatgpt.com，这个窗口别关）----
set "CHROME="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if defined CHROME (
  echo 正在打开专用 Chrome，首次请在里面登录 chatgpt.com，登录后这个窗口别关。
  start "" "%CHROME%" --remote-debugging-port=9333 --user-data-dir="%~dp0chrome-profile" --no-first-run --no-default-browser-check https://chatgpt.com/
) else (
  echo [提示] 没在默认位置找到 Google Chrome。
  echo 你可以稍后在网页里点“启动 Chrome 去登录”，或先安装 Google Chrome。
)

REM ---- 4) 起"常驻守护服务"（脱离本窗口，崩溃自动重启）----
REM 用 pythonw（无控制台）+ start 分离，关掉这个黑框 / 关掉 Claude 都不会中断服务。
set "PYW=.venv-win\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=.venv-win\Scripts\python.exe"
echo.
echo 启动常驻服务中（已脱离本窗口，关掉这个黑框也不会中断）...
start "" "%PYW%" supervisor.py
echo 稍等几秒会自动打开 http://127.0.0.1:5001
start "" http://127.0.0.1:5001
echo.
echo ============================================
echo  服务已在后台常驻运行：
echo   - 关闭本窗口 / 关掉 Claude 都不会中断它；程序崩溃会自动重启。
echo   - 想彻底停止服务，请双击「停止服务.bat」。
echo   - 出问题想查原因，看 logs\app.log 和 logs\supervisor.log。
echo ============================================
echo.
pause
