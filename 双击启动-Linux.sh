#!/bin/bash
# 建筑渲染智能体 — Linux 一键启动
# 用法：终端里 ./双击启动-Linux.sh   （或在文件管理器里右键→运行；首次可能要 chmod +x）
cd "$(dirname "$0")" || exit 1

echo "============================================"
echo "   建筑渲染智能体  一键启动 (Linux)"
echo "============================================"
echo

# ---- 1) 找 Python ----
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "[缺少 Python] 没检测到 Python，请先安装 Python 3.10 以上（如 sudo apt install python3 python3-venv）。"
  read -rp "装完再运行本脚本。按回车退出..."; exit 1
fi

# ---- 2) 虚拟环境 + 依赖（首次较慢；含首次一次的可选组件询问）----
if [ ! -x ".venv/bin/python" ]; then
  echo "首次运行：正在创建虚拟环境并安装依赖，请耐心等待（1-3 分钟）..."
  "$PY" -m venv .venv || { echo "创建虚拟环境失败（可能缺 python3-venv）。"; read -rp "按回车退出..."; exit 1; }
fi
.venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1
# 安装向导：核心依赖必装；可选组件（超分/去水印）首次问一次、之后不再问
.venv/bin/python scripts/setup_wizard.py || { echo "环境准备失败，请检查网络后重试。"; read -rp "按回车退出..."; exit 1; }

# ---- 3) 打开带调试端口的专用 Chrome（首次登录 chatgpt.com，别关那个窗口）----
CHROME="$(command -v google-chrome-stable || command -v google-chrome || command -v chromium-browser || command -v chromium)"
if [ -n "$CHROME" ]; then
  echo "正在打开专用 Chrome，首次请登录 chatgpt.com（或 gemini.google.com），登录后别关那个窗口。"
  "$CHROME" --remote-debugging-port=9333 --user-data-dir="$PWD/chrome-profile" \
    --no-first-run --no-default-browser-check "https://chatgpt.com/" >/dev/null 2>&1 &
else
  echo "[提示] 没找到 Chrome/Chromium。可先安装，或稍后在网页里点“启动 Chrome 去登录”。"
fi

# ---- 3.5) 检查助手页本地模型资产（首次较慢，缺失不影响主功能）----
echo "检查助手页本地模型资产（首次较慢，缺失不影响主功能）..."
.venv/bin/python scripts/fetch_assets.py || true

# ---- 4) 起"常驻守护服务"（脱离本终端，崩溃自动重启）----
echo
echo "启动常驻服务中（已脱离本终端，关掉终端也不会中断）..."
nohup .venv/bin/python supervisor.py >/dev/null 2>&1 &
disown
( sleep 4; xdg-open "http://127.0.0.1:5001" >/dev/null 2>&1 ) &
echo "============================================"
echo " 服务已在后台常驻运行："
echo "  - 关闭本终端不会中断它；程序崩溃会自动重启。"
echo "  - 想彻底停止服务，运行「停止服务-Linux.sh」。"
echo "  - 出问题看 logs/app.log 和 logs/supervisor.log。"
echo "============================================"
echo "浏览器会自动打开 http://127.0.0.1:5001 。本终端可以关闭了。"
