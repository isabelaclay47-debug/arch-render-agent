#!/bin/bash
PLIST="$HOME/Library/LaunchAgents/com.archrender.agent.plist"
launchctl unload "$PLIST" 2>/dev/null
rm -f "$PLIST" && echo "已取消开机自启。" || echo "本来就没开启。"
read -n 1
