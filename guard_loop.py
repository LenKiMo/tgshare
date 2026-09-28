#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TGShare 中继常驻探活循环（guard.py 的「不需要管理员」版）。

guard.py 面向任务计划的多触发器（开机 / 登录 / 唤醒 / 每 N 分钟），但 Windows 上
非提权会话连 `schtasks /Create` 都会被「拒绝访问」；本脚本改成一个常驻进程，
每 TICK 秒调用一次 guard.main()（查 /status，健康即退出；无响应就用 pythonw 静默拉起 server.py）。

- 探活幂等：guard 内部先查 /status，多实例/多触发器都不会拉起第二个中继。
- 睡眠唤醒：time.sleep 在系统挂起期间停摆，而这里每 60 秒就探一次，
  醒来后第一个节拍即命中（顺带把检测到的墙钟跳变写进日志）。
- 单实例：占 127.0.0.1:GUARD_LOCK_PORT 当锁，抢不到说明已有循环在跑，直接退出。
- 日志 guard_loop.log 只在「有动作」和每小时心跳时写，平时零增长。

用法：pythonw.exe guard_loop.py        # 建议配启动文件夹 / 开机自启（Windows）
"""
import contextlib
import io
import logging
import socket
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
TICK = 60                # 探活节拍（秒）：中继挂掉后最多 60 秒被拉回
HEARTBEAT = 60           # 每 N 次正常探活写一条心跳日志（约 1 小时）
GUARD_LOCK_PORT = 8791   # 单实例锁（仅本机）

logging.basicConfig(
    filename=str(BASE / "guard_loop.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)

sys.path.insert(0, str(BASE))
import guard  # noqa: E402  探活脚本（/status 无响应则用 pythonw 拉起 server）


def acquire_lock():
    """抢本机端口当单实例锁；抢不到返回 None。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", GUARD_LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def main() -> int:
    lock = acquire_lock()
    if lock is None:
        logging.info("已有 guard_loop 在运行，本次退出")
        return 0
    logging.info("guard_loop 启动（节拍 %ss）", TICK)
    ok = 0
    last = time.time()
    while True:
        now = time.time()
        gap = now - last                     # 远大于 TICK = 刚经历休眠/挂起
        last = now
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):        # guard 只在「有动作」时打印
            rc = guard.main()
        msg = buf.getvalue().strip()
        if msg or rc != 0:
            logging.info("探活触发 rc=%s 休眠间隔=%.0fs %s", rc, gap, msg)
            ok = 0
        else:
            ok += 1
            if ok >= HEARTBEAT:
                logging.info("探活正常（累计 %d 次）", ok)
                ok = 0
        time.sleep(TICK)


if __name__ == "__main__":
    sys.exit(main())
