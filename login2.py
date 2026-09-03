#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TGShare 显式登录：手动发送验证码 → sign_in，正确处理 2FA 与错误码重试。"""
import asyncio
import json
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

BASE = Path(__file__).resolve().parent
PHONE = ""   # 留空则在运行时输入；或通过命令行参数传入


async def main():
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    client = TelegramClient(str(BASE / cfg["session_name"]), int(cfg["api_id"]), cfg["api_hash"])
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"ALREADY_LOGGED_IN: {me.first_name} @{me.username} (id={me.id})")
        return
    phone = sys.argv[1] if len(sys.argv) > 1 else (PHONE or input("手机号(带国家码): ").strip())
    print(f"发送验证码到 {phone} ...", flush=True)
    try:
        sent = await client.send_code_request(phone)
    except Exception as e:
        print(f"发送失败: {type(e).__name__}: {e}", flush=True)
        print("提示：验证码发送通道可能被限流（同一号码多次请求）。请等 1-3 分钟后重跑本脚本。", flush=True)
        return
    print(f"CODE_SENT (超时 {sent.timeout}s，请查看 Telegram/短信)", flush=True)
    for attempt in range(1, 4):
        code = input(f"验证码(第{attempt}次): ").strip()
        try:
            me = await client.sign_in(phone, code=code)
            print(f"LOGIN_OK: {me.first_name} @{me.username} (id={me.id})")
            return
        except SessionPasswordNeededError:
            pw = input("两步验证密码: ")
            me = await client.sign_in(phone, password=pw)
            print(f"LOGIN_OK: {me.first_name} @{me.username} (id={me.id})")
            return
        except PhoneCodeInvalidError:
            print("验证码错误，请重新输入", flush=True)
        except PhoneCodeExpiredError:
            print("验证码过期，重新发送...", flush=True)
            sent = await client.send_code_request(phone)
            print(f"新 CODE_SENT (超时 {sent.timeout}s)", flush=True)
    print("LOGIN_FAILED: 三次机会用尽")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
