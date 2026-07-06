@echo off
chcp 65001 >nul
echo 正在启动带调试端口的专用 Chrome（首次使用请在里面登录 chatgpt.com）...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9333 ^
  --user-data-dir="%~dp0chrome-profile" ^
  --no-first-run --no-default-browser-check ^
  https://chatgpt.com/
echo 如果没有反应，说明 Chrome 不在默认安装位置，请编辑本文件里的路径。
