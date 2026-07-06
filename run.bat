@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv-win\Scripts\python.exe" (
  echo 首次运行：正在创建项目虚拟环境...
  python -m venv .venv-win
  if errorlevel 1 (
    echo 创建虚拟环境失败，请确认已安装 Python。
    pause
    exit /b 1
  )
)

echo 检查依赖...
".venv-win\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo 依赖安装失败，请检查网络或 Python 环境。
  pause
  exit /b 1
)

echo 启动建筑渲染智能体... 浏览器打开 http://127.0.0.1:5001
start "" http://127.0.0.1:5001
".venv-win\Scripts\python.exe" app.py
pause
