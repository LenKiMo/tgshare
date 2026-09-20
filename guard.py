#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TGShare 探活守护：/status 无响应则拉起 server（幂等，配合任务计划多触发器）。

设计（部署层守护，替代"AtLogOn + RestartOnFailure"）：
  - 任务计划触发器：开机(AtStartup) + 登录(AtLogOn) + 睡眠唤醒(WakeToRun)
    + 每 30 分钟重复(兜底任何死法)
  - 本脚本每次触发都检查 /status：中继健康则立即退出(exit 0)，
    无响应则用 pythonw 分离拉起 server 后退出。
  - 健康检查本身就是幂等，多触发器/错过计划都不会重复拉起。

用法（任务计划 Action）：
  pythonw.exe guard.py
退出码：0 = 健康或已拉起；1 = 拉起失败。
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent


def is_alive(port: int, timeout: float = 4.0) -> bool:
    """/status 返回 HTTP 200 视为健康。"""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/status", timeout=timeout
        ) as r:
            return r.status == 200
    except Exception:
        return False


def start_server() -> bool:
    """分离拉起 server.py（无窗口，脱离调用者进程树）。"""
    pyw = BASE / ".venv" / "Scripts" / "pythonw.exe"
    exe = str(pyw) if pyw.exists() else sys.executable
    try:
        subprocess.Popen(
            [exe, str(BASE / "server.py")],
            cwd=str(BASE),
            creationflags=(
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as e:
        print(f"guard: 拉起失败 {e}", flush=True)
        return False


def main() -> int:
    try:
        cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    port = int(cfg.get("port", 8787))

    if is_alive(port):
        return 0  # 健康，无事发生

    # 二次确认防竞态（两个触发几乎同时到达时不重复拉起）
    time.sleep(1)
    if is_alive(port):
        return 0

    print(f"guard: 中继 127.0.0.1:{port} 无响应，拉起 server", flush=True)
    return 0 if start_server() else 1


if __name__ == "__main__":
    sys.exit(main())