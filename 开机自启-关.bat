@echo off
chcp 65001 >nul
title 开机自启 - 关
echo 正在取消开机自启...
schtasks /Delete /TN "ArchRenderAgent" /F
if errorlevel 1 ( echo 未找到自启任务，或已经关闭。 ) else ( echo 已取消开机自启。 )
pause
