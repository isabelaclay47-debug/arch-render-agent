@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 停止建筑渲染智能体
echo ============================================
echo    停止建筑渲染智能体常驻服务
echo ============================================
echo.
REM 写入停止标志：守护进程每秒巡检一次，会在 1-2 秒内优雅关闭 app.py 并退出。
type nul > ".supervisor_stop"
echo 已发送停止指令，服务将在几秒内停止...
timeout /t 4 >nul

REM 兜底：若守护进程没在跑（比如是直接启动的 app.py），标志文件不会被消费，这里清掉它，
REM 避免下次启动时被误判为"要求停止"。守护进程自身退出时也会清理它，二者不冲突。
if exist ".supervisor_stop" del ".supervisor_stop" >nul 2>nul

echo 完成。若网页仍能打开，请等 10 秒后再刷新确认。
echo.
pause
