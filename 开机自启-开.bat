@echo off
chcp 936 >nul
cd /d "%~dp0"
title 开机自启 - 开
set "PYW=%~dp0.venv-win\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%~dp0.venv-win\Scripts\python.exe"
if not exist "%PYW%" (
  echo 还没安装环境，请先双击「双击启动.bat」跑一次，再来开启自启。
  pause & exit /b 1
)
echo 正在注册「登录时自动在后台启动建筑渲染智能体」...
schtasks /Create /TN "ArchRenderAgent" /TR "\"%PYW%\" \"%~dp0supervisor.py\"" /SC ONLOGON /RL LIMITED /F
if errorlevel 1 ( echo 注册失败（可能需要允许权限）。 & pause & exit /b 1 )
echo 完成：下次登录 Windows 就会自动在后台待命。要关闭请双击「开机自启-关.bat」。
pause
