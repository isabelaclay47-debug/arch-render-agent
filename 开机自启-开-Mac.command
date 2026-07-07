#!/bin/bash
cd "$(dirname "$0")" || exit 1
PLIST="$HOME/Library/LaunchAgents/com.archrender.agent.plist"
PY="$PWD/.venv/bin/python"
if [ ! -x "$PY" ]; then echo "请先双击「双击启动-Mac.command」装好环境再来。"; read -n 1; exit 1; fi
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.archrender.agent</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$PWD/supervisor.py</string></array>
  <key>RunAtLoad</key><true/>
  <key>WorkingDirectory</key><string>$PWD</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null
launchctl load "$PLIST" && echo "已开启开机自启。要关闭请双击「开机自启-关-Mac.command」。"
read -n 1
