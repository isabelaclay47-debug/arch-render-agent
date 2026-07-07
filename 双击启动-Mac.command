#!/bin/bash
# 建筑渲染智能体 — macOS 一键启动（双击运行）
cd "$(dirname "$0")" || exit 1

echo "============================================"
echo "   建筑渲染智能体  一键启动"
echo "============================================"
echo

# ---- 1) 找 Python ----
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "[缺少 Python] 没检测到 Python，请先安装 Python 3.10 以上版本。"
  open "https://www.python.org/downloads/" 2>/dev/null
  echo "装完再双击本文件。按任意键退出..."; read -n 1; exit 1
fi

# ---- 2) 虚拟环境 + 依赖（首次较慢）----
if [ ! -x ".venv/bin/python" ]; then
  echo "首次运行：正在创建虚拟环境并安装依赖，请耐心等待（1-3 分钟）..."
  "$PY" -m venv .venv || { echo "创建虚拟环境失败。"; read -n 1; exit 1; }
fi
.venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1
.venv/bin/python -m pip install -q -r requirements.txt || { echo "依赖安装失败，请检查网络后重试。"; read -n 1; exit 1; }

# ---- 3) 打开带调试端口的专用 Chrome（首次登录 chatgpt.com，别关那个窗口）----
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ -x "$CHROME" ]; then
  echo "正在打开专用 Chrome，首次请登录 chatgpt.com，登录后别关那个窗口。"
  "$CHROME" --remote-debugging-port=9333 --user-data-dir="$PWD/chrome-profile" \
    --no-first-run --no-default-browser-check "https://chatgpt.com/" >/dev/null 2>&1 &
else
  echo "[提示] 没找到 Google Chrome。可稍后在网页里点“启动 Chrome 去登录”，或先安装 Chrome。"
fi

# ---- 3.5) 检查助手页本地模型资产（首次较慢，缺失不影响主功能）----
echo "检查助手页本地模型资产（首次较慢，缺失不影响主功能）..."
.venv/bin/python scripts/fetch_assets.py || true

# ---- 4) 起"常驻守护服务"（脱离本窗口，崩溃自动重启）----
# nohup + disown：关掉终端 / 关掉 Claude 都不会中断服务。
echo
echo "启动常驻服务中（已脱离本窗口，关掉终端也不会中断）..."
nohup .venv/bin/python supervisor.py >/dev/null 2>&1 &
disown
( sleep 4; open "http://127.0.0.1:5001" ) &
echo "============================================"
echo " 服务已在后台常驻运行："
echo "  - 关闭本窗口 / 关掉 Claude 都不会中断它；程序崩溃会自动重启。"
echo "  - 想彻底停止服务，请双击「停止服务-Mac.command」。"
echo "  - 出问题想查原因，看 logs/app.log 和 logs/supervisor.log。"
echo "============================================"
echo "本窗口可以关闭了。按任意键关闭..."; read -n 1
