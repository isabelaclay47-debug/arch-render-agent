@echo off
chcp 936 >nul
cd /d "%~dp0"
set "CHROME="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined CHROME (
  echo [ȱ�� Chrome] û�ҵ� Google Chrome�����ڴ�����ҳ...
  start "" https://www.google.com/chrome/
  pause
  exit /b 1
)
echo �������������Զ˿ڵ�ר�� Chrome���״�ʹ�����������¼ chatgpt.com��...
start "" "%CHROME%" --remote-debugging-port=9333 --user-data-dir="%~dp0chrome-profile" --disable-extensions --disable-component-extensions-with-background-pages --no-first-run --no-default-browser-check https://chatgpt.com/
echo ���û�з�Ӧ��˵�� Chrome ����Ĭ�ϰ�װλ�ã���༭���ļ����·����
