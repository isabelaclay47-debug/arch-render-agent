@echo off
chcp 936 >nul
cd /d "%~dp0"
set "CHROME="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined CHROME (
  echo [缺少 Chrome] 没找到 Google Chrome，正在打开下载页...
  start "" https://www.google.com/chrome/
  pause
  exit /b 1
)
echo 正在启动带调试端口的专用 Chrome（首次使用请在里面登录 chatgpt.com）...
start "" "%CHROME%" --remote-debugging-port=9333 --user-data-dir="%~dp0chrome-profile" --no-first-run --no-default-browser-check https://chatgpt.com/
echo 如果没有反应，说明 Chrome 不在默认安装位置，请编辑本文件里的路径。
