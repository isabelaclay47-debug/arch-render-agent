# -*- coding: utf-8 -*-
"""
常驻守护进程：让"建筑渲染智能体"完全脱离启动它的终端（包括 Claude），
崩溃后自动重启，除非收到明确的停止指令。

对应痛点一 / 二（崩溃 / 断连）：
  1. 完全脱离 Claude：由 pythonw / nohup 以"无控制台"方式拉起本进程后，
     关掉 Claude 的终端、甚至 Claude 本身崩溃，都不会带走这个服务。
  2. 崩溃自动重启：app.py 意外退出就重新拉起，带指数退避与"崩溃风暴"保护，
     避免一个必崩的错误把机器 CPU 打满。
  3. 单实例：已在运行（端口被占）则不重复启动，避免两个服务抢 5001 端口。
  4. 可控停止：只有写入停止标志（由「停止服务」脚本创建）才优雅退出——
     目标是"不被意外带走"，不是"自己也停不掉"。
  5. 全程留痕：logs/ 下记录每次启动 / 退出 / 重启，事后能查"到底为啥卡死"。

用法：
    pythonw supervisor.py        # Windows：无窗口常驻（推荐，由 双击启动.bat 调用）
    python  supervisor.py        # 前台运行，Ctrl-C 停止（调试用）
"""
import os
import socket
import subprocess
import sys
import time
from collections import deque
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(APP_DIR, "logs")
STOP_FLAG = os.path.join(APP_DIR, ".supervisor_stop")   # 存在即请求停止
PID_FILE = os.path.join(APP_DIR, ".supervisor_pid")     # 记录守护进程 PID
SUPERVISOR_LOG = os.path.join(LOG_DIR, "supervisor.log")
APP_LOG = os.path.join(LOG_DIR, "app.log")

# 被守护的目标脚本（默认 app.py；留个环境变量口子便于自测）
TARGET = os.environ.get("ARA_SUPERVISOR_TARGET", "app.py")
APP_PORT = 5001

# 崩溃重启策略
BACKOFF_BASE = 2          # 退避基数（秒）：1 次崩溃后等 2s，2 次等 4s …
BACKOFF_MAX = 30          # 单次重启最长等待（秒）
STORM_WINDOW = 60         # "崩溃风暴"观察窗口（秒）
STORM_LIMIT = 5           # 窗口内崩溃达到此数 → 判定必崩，进入长冷却
STORM_COOLDOWN = 60       # 崩溃风暴时的冷却时长（秒）
POLL_INTERVAL = 1.0       # 轮询子进程 / 停止标志的间隔（秒）


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str):
    """写守护日志，同时尽量打到 stdout（前台调试时可见）。"""
    line = f"[{_ts()}] {msg}"
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(SUPERVISOR_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass  # pythonw 无 stdout 时忽略


def stop_requested() -> bool:
    return os.path.exists(STOP_FLAG)


def port_in_use(port: int) -> bool:
    """5001 端口是否已被占用（用于单实例判断）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def write_pid():
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def clear_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def spawn_app():
    """以子进程方式拉起 app.py，stdout/stderr 一起追加到 app.log。
    Windows 下用 CREATE_NO_WINDOW，避免在 pythonw 常驻时弹出黑框。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    app_log = open(APP_LOG, "a", encoding="utf-8", buffering=1)
    app_log.write(f"\n[{_ts()}] ==== 启动 {TARGET}（解释器 {sys.executable}）====\n")
    app_log.flush()
    # 强制子进程用 UTF-8：否则在 chcp 936(GBK) 的 Windows 上，app.py 里 print 含
    # ⚠🔍 的日志会抛 UnicodeEncodeError，把整轮生图拖成「未预期的错误」。这里从
    # 进程启动的第一字节就锁定 UTF-8，覆盖 app.py 自身 reconfigure 之前的窗口期。
    child_env = dict(os.environ)
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    kwargs = {"cwd": APP_DIR, "stdout": app_log, "stderr": subprocess.STDOUT,
              "env": child_env}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.Popen([sys.executable, os.path.join(APP_DIR, TARGET)], **kwargs)
    return proc, app_log


def terminate(proc):
    """优雅关闭子进程：先 terminate，10 秒不退再 kill。"""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        log("子进程 10s 未响应 terminate，强制 kill。")
        try:
            proc.kill()
        except Exception:
            pass
    except Exception:
        pass


def main():
    # 启动时清掉上一次遗留的停止标志，否则会立刻自我了断
    if stop_requested():
        try:
            os.remove(STOP_FLAG)
        except OSError:
            pass

    # 单实例：端口已被占，说明服务已在运行，直接退出
    if port_in_use(APP_PORT):
        log(f"端口 {APP_PORT} 已被占用，判定服务已在运行，本次守护进程退出（避免重复启动）。")
        return

    write_pid()
    log(f"守护进程启动（PID {os.getpid()}），开始守护 {TARGET}，端口 {APP_PORT}。")
    crashes = deque()  # 最近若干次崩溃的时间戳，用于崩溃风暴判断
    restart_count = 0

    try:
        while not stop_requested():
            proc, app_log = spawn_app()
            log(f"已拉起 {TARGET}（子进程 PID {proc.pid}）。")

            # 守着它：正常运行时每秒查一次停止标志，实现"健康服务也能被主动停掉"
            while proc.poll() is None:
                if stop_requested():
                    log("收到停止标志，正在关闭服务…")
                    terminate(proc)
                    break
                time.sleep(POLL_INTERVAL)

            app_log.close()

            if stop_requested():
                break

            code = proc.returncode
            log(f"{TARGET} 退出（返回码 {code}）。判断是否需要重启…")

            # 崩溃风暴保护：短时间内反复崩溃 → 长冷却，别把 CPU 打满
            now = time.time()
            crashes.append(now)
            while crashes and now - crashes[0] > STORM_WINDOW:
                crashes.popleft()
            if len(crashes) >= STORM_LIMIT:
                log(f"{STORM_WINDOW}s 内已崩溃 {len(crashes)} 次，疑似必崩错误，"
                    f"冷却 {STORM_COOLDOWN}s 后再试。请到 logs/app.log 查原因。")
                slept = 0
                while slept < STORM_COOLDOWN and not stop_requested():
                    time.sleep(POLL_INTERVAL)
                    slept += POLL_INTERVAL
                crashes.clear()
                continue

            restart_count += 1
            backoff = min(BACKOFF_MAX, BACKOFF_BASE ** min(restart_count, 5))
            log(f"第 {restart_count} 次自动重启，{backoff}s 后重新拉起。")
            slept = 0
            while slept < backoff and not stop_requested():
                time.sleep(POLL_INTERVAL)
                slept += POLL_INTERVAL
    except KeyboardInterrupt:
        log("收到 Ctrl-C，停止守护。")
    finally:
        clear_pid()
        # 消费掉停止标志，避免影响下次启动
        if stop_requested():
            try:
                os.remove(STOP_FLAG)
            except OSError:
                pass
        log("守护进程结束。")


if __name__ == "__main__":
    main()
