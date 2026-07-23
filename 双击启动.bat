@echo off
chcp 936 >nul
title ������Ⱦ������
cd /d "%~dp0"

echo ============================================
echo    ������Ⱦ������  һ������
echo ============================================
echo.

REM ---- 1) �� Python ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo [ȱ�� Python] û��⵽ Python��
  echo ���ڴ�����ҳ���밲װ Python 3.10 ���ϰ汾��
  echo ��װʱ��ع�ѡ "Add Python to PATH"��װ����˫�����ļ���
  start "" https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

REM ---- 2) ���⻷�� + �������״ν�����1-3 ���ӣ�֮���뿪��----
if not exist ".venv-win\Scripts\python.exe" (
  echo �״����У����ڴ������⻷������װ�����������ĵȴ�...
  %PY% -m venv .venv-win || ( echo �������⻷��ʧ�ܡ� & pause & exit /b 1 )
  ".venv-win\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
  ".venv-win\Scripts\python.exe" scripts\setup_wizard.py || ( echo ������װʧ�ܣ�������������ԡ� & pause & exit /b 1 )
) else (
  echo ��������Ƿ���ȫ...
  ".venv-win\Scripts\python.exe" scripts\setup_wizard.py >nul 2>nul
)

REM ---- 3) ��� Google Chrome�������߿��ӹ����Լ��� Chrome��������װ��----
set "CHROME="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined CHROME (
  echo [ȱ�� Chrome] û�ҵ� Google Chrome����������Ҫ������¼������ ChatGPT��
  echo ���ڴ� Chrome ����ҳ��װ�ú���˫�����ļ���
  start "" https://www.google.com/chrome/
  echo.
  pause
  exit /b 1
)

REM ---- 3.5) ��ר�� Chrome���˿� 9333 �����ܾͲ��ظ������״����¼ chatgpt.com�������� Chrome��----
netstat -ano | findstr ":9333" >nul 2>nul
if not errorlevel 1 (
  echo ר�� Chrome �ƺ��������У��˿� 9333���������ظ�������
) else (
  echo ���ڴ�ר�� Chrome���״����������¼ chatgpt.com����¼��������ڱ�ء�
  start "" "%CHROME%" --remote-debugging-port=9333 --user-data-dir="%~dp0chrome-profile" --disable-extensions --disable-component-extensions-with-background-pages --no-first-run --no-default-browser-check https://chatgpt.com/
)

REM ---- 4) ��"��פ�ػ�����"�����뱾���ڣ������Զ�������----
set "PYW=.venv-win\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=.venv-win\Scripts\python.exe"
echo.
echo ������פ�����У������뱾���ڣ��ص�����ڿ�Ҳ�����жϣ�...
start "" "%PYW%" supervisor.py
echo �Եȼ�����Զ��� http://127.0.0.1:5001
start "" http://127.0.0.1:5001
echo.
echo ============================================
echo  �������ں�̨��פ���У�
echo   - �رձ����� / �ص� Claude �������ж���������������Զ�������
echo   - �������� ChatGPT������ר�� Chrome ���¼һ�Σ���
echo   - �����߱���ʶͼ������ҳ����ʾ�����֡��С����ش�ģ�͡�����ʾһ����װ����ѡ����
echo   - �볹��ֹͣ������˫����ֹͣ����.bat����
echo   - ���������ԭ�򣬿� logs\app.log �� logs\supervisor.log��
echo ============================================
echo.
pause
