#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TGShare 本地中继服务
X/Twitter 一键分享到 Telegram：
  浏览器用户脚本 → http://127.0.0.1:<port>/send → (Telethon 自己账号 | Bot API) → Telegram

用法：
  python server.py --login    # userbot 模式首次登录（交互式：手机号+验证码+2FA）
  python server.py            # 启动服务（默认 127.0.0.1:8787）
"""
import argparse
import asyncio
import hmac
import json
import logging
import secrets
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
LOG_PATH = BASE / "tgshare.log"

ALLOWED_ORIGINS = {"https://x.com", "https://twitter.com"}

DEFAULTS = {
    "mode": "userbot",
    "api_id": 6,
    "api_hash": "eb06d4abfb49dc3eeb1aeb98ae0f581e",
    "bot_token": "",
    "session_name": "tgshare",
    "port": 8787,
    "auth_token": "",
    "service": "fixupx",
    "fallback": "copy",
    "text_template": "{link}",
    "bots": {},
    "targets": [{"label": "保存的消息", "chat": "me"}],
}

# ---------------- config ----------------

def load_config():
    if not CONFIG_PATH.exists():
        save_config(DEFAULTS)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    changed = False
    for k, v in DEFAULTS.items():
        if k not in cfg:
            cfg[k] = v
            changed = True
    if not cfg.get("auth_token"):
        cfg["auth_token"] = secrets.token_hex(16)
        changed = True
    if changed:
        save_config(cfg)
    return cfg


def save_config(cfg):
    doc = {
        "_comment": "TGShare 中继配置。改完保存即可，浏览器端下次加载自动生效。",
        "_comment_mode": "mode: userbot(自己账号, 需 --login) | bot(Bot API token, 免登录)；单个目标可用 mode/bot 覆盖身份",
        "_comment_targets": "targets: label=按钮文字, chat=@用户名/数字ID(群/频道为负数)/me(保存的消息)。可加 mode(可选 userbot/bot) 与 bot(注册表别名) 覆盖发送身份。用 http://127.0.0.1:8787/pick 挑选",
        "_comment_bots": "bots: 多机器人注册表，如 {\"botA\": \"123:token\", \"botB\": \"456:token\"}；targets 里 \"bot\": \"botA\" 即用该机器人发送",
        **cfg,
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


# ---------------- telegram ----------------

def normalize_chat(chat):
    if isinstance(chat, int):
        return chat
    s = str(chat).strip()
    if s == "me":
        return "me"
    if s.startswith("@"):
        return s
    try:
        return int(s)
    except ValueError:
        return s


async def setup_telethon(app, cfg):
    """建立 Telethon 会话（后台任务运行，带长重试以覆盖开机时网络未就绪）。"""
    from telethon import TelegramClient

    client = TelegramClient(str(BASE / cfg["session_name"]), int(cfg["api_id"]), cfg["api_hash"])
    app["client"] = client
    # 最长重试 ~2 分钟（6s × 20 次）：开机自启时网络/代理可能还没就绪
    for i in range(20):
        try:
            await client.connect()
            break
        except Exception as e:
            logging.warning("Telethon 连接失败(第 %d/20 次): %s", i + 1, e)
            await asyncio.sleep(6)
    if not client.is_connected():
        app["authed"] = False
        logging.error("Telethon 始终无法连接（网络/代理未就绪？）——将保持未登录，稍后重启或发送时自动重连")
        return
    if await client.is_user_authorized():
        me = await client.get_me()
        app["authed"] = True
        logging.info("已登录为 %s @%s (id=%s)", me.first_name, me.username, me.id)
    else:
        app["authed"] = False
        logging.error("userbot 未登录！请运行: python server.py --login")


async def _ensure_client(app):
    """确保 Telethon 客户端已连接；断线时尝试重连一次。返回 (client) 或抛错。"""
    client = app.get("client")
    if client is None:
        raise RuntimeError("userbot 未初始化（当前配置可能不需要 Telethon）")
    if not client.is_connected():
        logging.info("Telethon 断线，尝试重连…")
        try:
            await client.connect()
        except Exception as e:
            logging.warning("重连失败: %s", e)
    if not client.is_connected():
        raise RuntimeError("userbot 未连接（网络/代理问题），请稍后重试")
    return client


async def send_userbot(app, chat, text):
    client = await _ensure_client(app)
    if not await client.is_user_authorized():
        raise RuntimeError("userbot 未登录，请先运行 python server.py --login")
    msg = await client.send_message(normalize_chat(chat), text)
    return msg.id


_owner_cache = {}


async def resolve_bot_owner(app, token):
    if token in _owner_cache:
        return _owner_cache[token]
    http = app["http"]
    async with http.get(f"https://api.telegram.org/bot{token}/getUpdates") as r:
        data = await r.json(content_type=None)
    if data.get("ok") and data.get("result"):
        cid = data["result"][0]["message"]["chat"]["id"]
        _owner_cache[token] = cid
        return cid
    raise RuntimeError("bot 模式找不到你的 chat id：先给机器人发一条消息，或直接用数字 chat id")


async def send_bot(app, chat, text, token=None):
    if not token:
        token = app["cfg"].get("bot_token") or ""
    if not token:
        raise RuntimeError("bot_token 未配置（mode=bot 需要）")
    if chat == "me":
        chat = await resolve_bot_owner(app, token)
    http = app["http"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with http.post(url, json={"chat_id": chat, "text": text, "disable_web_page_preview": False}) as r:
        data = await r.json(content_type=None)
        if not data.get("ok"):
            raise RuntimeError(data.get("description") or f"HTTP {r.status}")
        return data["result"]["message_id"]


# ---------------- helpers ----------------

def check_auth(request, cfg):
    tok = request.headers.get("X-Auth-Token") or request.query.get("token") or ""
    return hmac.compare_digest(tok, cfg["auth_token"])


def find_target(cfg, chat):
    """按 chat 值找白名单目标（目标可携带身份覆盖字段）。"""
    for t in cfg.get("targets", []):
        if str(t.get("chat", "")) == str(chat):
            return t
    return None


def resolve_sender(cfg, target):
    """目标级身份覆盖：target.mode / target.bot 别名；缺省回退全局 mode。返回 (sender, bot_token|None)。"""
    # 目标写了 bot 别名即隐含 bot 模式；否则 mode 字段覆盖，再回退全局 mode
    if target.get("bot"):
        mode = "bot"
    else:
        mode = (target.get("mode") or cfg.get("mode") or "userbot").lower()
    if mode == "bot":
        alias = target.get("bot")
        if alias:
            token = (cfg.get("bots") or {}).get(alias)
            if not token:
                raise RuntimeError(f'bots 注册表中不存在别名 "{alias}"，请检查 config.json 的 bots')
            return "bot", token
        return "bot", None
    if mode not in ("userbot", "bot"):
        raise RuntimeError(f'未知发送模式 "{mode}"（可选 userbot / bot）')
    return mode, None


# ---------------- handlers ----------------

async def handle_send(request):
    cfg = request.app["cfg"]
    if not check_auth(request, cfg):
        return web.json_response({"ok": False, "error": "auth failed"}, status=403)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad json"}, status=400)
    chat = data.get("chat")
    text = (data.get("text") or "").strip()
    if not chat or not text:
        return web.json_response({"ok": False, "error": "chat/text 必填"}, status=400)
    if find_target(cfg, chat) is None:
        return web.json_response({"ok": False, "error": "该目标不在白名单，请先加入 config.json 的 targets"}, status=403)
    if len(text) > 4096:
        return web.json_response({"ok": False, "error": "text 过长"}, status=400)
    try:
        target = find_target(cfg, chat)
        sender, token = resolve_sender(cfg, target)
        if sender == "bot":
            mid = await send_bot(request.app, chat, text, token)
        else:
            mid = await send_userbot(request.app, chat, text)
    except Exception as e:
        logging.exception("send failed")
        return web.json_response({"ok": False, "error": str(e)[:300]}, status=500)
    logging.info("sent to %s [%s]: %.80s", chat, sender, text)
    return web.json_response({"ok": True, "message_id": mid})


async def handle_config_js(request):
    cfg = request.app["cfg"]
    pub = {
        "relay": f"http://127.0.0.1:{cfg['port']}",
        "service": cfg.get("service", "fixupx"),
        "fallback": cfg.get("fallback", "copy"),
        "textTemplate": cfg.get("text_template", "{link}"),
        "targets": cfg.get("targets", []),
        "authToken": cfg["auth_token"],
        "version": 1,
    }
    body = "window.TGShareConfig = " + json.dumps(pub, ensure_ascii=False) + ";"
    return web.Response(text=body, content_type="application/javascript")


SERVICES = {"fixupx", "fixvx", "fxtwitter", "vxtwitter"}


async def handle_config_update(request):
    cfg = request.app["cfg"]
    if not check_auth(request, cfg):
        return web.json_response({"ok": False, "error": "auth failed"}, status=403)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad json"}, status=400)
    if not isinstance(data, dict):
        return web.json_response({"ok": False, "error": "bad json"}, status=400)
    if "service" in data:
        svc = str(data.get("service", "")).lower()
        if svc not in SERVICES:
            return web.json_response({"ok": False, "error": "service 可选: fixupx/fixvx/fxtwitter/vxtwitter"}, status=400)
        cfg["service"] = svc
    save_config(cfg)
    logging.info("config updated: service=%s", cfg["service"])
    return web.json_response({"ok": True, "service": cfg["service"]})


async def handle_status(request):
    cfg = request.app["cfg"]
    client = request.app.get("client")
    authed = bool(request.app.get("authed")) and client is not None and client.is_connected()
    return web.json_response(
        {
            "ok": True,
            "mode": cfg["mode"],
            "authed": authed,
            "service": cfg.get("service"),
            "targets": [t.get("label") for t in cfg.get("targets", [])],
            "version": 1,
        }
    )


async def handle_dialogs(request):
    cfg = request.app["cfg"]
    if not check_auth(request, cfg):
        return web.json_response({"ok": False, "error": "auth failed"}, status=403)
    client = request.app.get("client")
    if client is None or not await client.is_user_authorized():
        return web.json_response({"ok": False, "error": "聊天列表仅 userbot 模式可用（当前 mode=%s）" % request.app["cfg"]["mode"]}, status=400)
    out = []
    async for d in client.iter_dialogs(limit=300):
        if d.is_user:
            t = "用户"
        elif d.is_group:
            t = "群组"
        elif d.is_channel:
            t = "频道"
        else:
            t = "其他"
        uname = getattr(d.entity, "username", None) if d.entity else None
        out.append({"id": d.id, "username": uname, "title": d.name, "type": t})
    out.sort(key=lambda x: (x["title"] or "").lower())
    return web.json_response({"ok": True, "items": out})


async def handle_script(request, name):
    p = BASE / name
    if not p.exists():
        return web.Response(text="// 文件缺失", content_type="application/javascript")
    return web.Response(
        body=p.read_bytes(),
        content_type="text/javascript" if name.endswith(".user.js") else "application/javascript",
    )


PICK_PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>TGShare · 选择目标聊天</title>
<style>
body{font-family:system-ui,'Segoe UI',sans-serif;max-width:780px;margin:24px auto;padding:0 16px;background:#0f1419;color:#e7e9ea}
h2{font-size:18px} .badge{color:#8b98a5;font-size:12px}
input{width:100%;padding:9px 12px;margin:10px 0;box-sizing:border-box;background:#16181c;color:#e7e9ea;border:1px solid #333;border-radius:8px;font-size:14px}
table{width:100%;border-collapse:collapse} td,th{text-align:left;padding:8px 6px;border-bottom:1px solid #2f3336;font-size:13px}
button{background:#1d9bf0;border:0;color:#fff;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:12px}
button:hover{background:#1a8cd8} .tag{color:#8b98a5;font-size:11px}
</style></head><body>
<h2>TGShare · 选择目标聊天</h2>
<p class="badge">点击「复制」得到 JSON 片段，粘贴进 config.json 的 targets 数组（label=按钮文字, chat=目标）。</p>
<input id="q" placeholder="搜索标题 / 用户名…" oninput="render()">
<table><thead><tr><th>标题</th><th>类型</th><th>标识</th><th></th></tr></thead><tbody id="rows"></tbody></table>
<script>
let items=[], tok='';
async function init(){ try{ const c=await (await fetch('/config.js')).text(); const m=c.match(/window\\.TGShareConfig = (\\{[\\s\\S]*?\\});/); tok=(m?JSON.parse(m[1]):{}).authToken||''; }catch(e){} await load(); }
async function load(){ items=(await (await fetch('/dialogs?token='+encodeURIComponent(tok))).json()).items||[]; render(); }
function esc(s){ return (s||'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function render(){ const q=(document.getElementById('q').value||'').toLowerCase();
 const list=items.filter(i=>!q||(i.title||'').toLowerCase().includes(q)||(i.username||'').toLowerCase().includes(q));
 document.getElementById('rows').innerHTML=list.map(i=>{ const cid=i.username?('@'+i.username):String(i.id);
 return `<tr><td>${esc(i.title)}${i.username?` <span class="tag">@${esc(i.username)}</span>`:''}</td><td class="tag">${i.type}</td><td class="tag">${esc(cid)}</td><td><button data-label="${esc(i.title)}" data-chat="${esc(cid)}">复制</button></td></tr>`;}).join('')||'<tr><td colspan=4 class="badge">无结果（若列表为空请确认已登录）</td></tr>'; }
document.getElementById('rows').addEventListener('click', e=>{ const b=e.target.closest('button[data-label]'); if(!b) return;
 const item=JSON.stringify({label:b.dataset.label, chat:b.dataset.chat});
 navigator.clipboard.writeText(item).then(()=>{ const o=b.textContent; b.textContent='✓ 已复制'; setTimeout(()=>b.textContent=o,1200); }); });
init();
</script></body></html>"""


def index_page(cfg):
    bookmarklet = (
        "javascript:(function(){if(document.documentElement.getAttribute('data-tgshare-loaded'))return;"
        f"var s=document.createElement('script');s.src='http://127.0.0.1:{cfg['port']}/inject.js?'+Date.now();"
        "document.head.appendChild(s);})();"
    )
    cfg_path = str(CONFIG_PATH)
    targets = cfg.get("targets", [])
    target_html = "".join(
        f'<li><code>{t.get("label")}</code> → <code>{t.get("chat")}</code></li>' for t in targets
    ) or "<li>（暂无，打开 config.json 添加）</li>"
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>TGShare · 安装与配置</title>
<style>
body{{font-family:system-ui,'Segoe UI',sans-serif;max-width:720px;margin:32px auto;padding:0 20px;background:#0f1419;color:#e7e9ea;line-height:1.7}}
h1{{font-size:22px}} h2{{font-size:16px;margin-top:26px}} code{{background:#16181c;border:1px solid #2f3336;border-radius:6px;padding:1px 7px;font-size:13px}}
.step{{background:#16181c;border:1px solid #2f3336;border-radius:12px;padding:14px 16px;margin:10px 0}}
a{{color:#1d9bf0;text-decoration:none}} a:hover{{text-decoration:underline}}
.badge{{color:#8b98a5;font-size:13px}} .ok{{color:#00ba7c}} .warn{{color:#f4212e}}
.btn{{display:inline-block;background:#1d9bf0;color:#fff;padding:7px 16px;border-radius:8px;font-size:14px}}
.mono{{font-family:Consolas,monospace;font-size:12px;word-break:break-all}}
</style></head><body>
<h1>TGShare · 本地中继</h1>
<p class="badge">状态：mode=<b>{cfg['mode']}</b> · service=<b>{cfg['service']}</b> · 端口 <b>{cfg['port']}</b> · 目标 {len(targets)} 个 · 脚本版本 1</p>

<div class="step"><h2 style="margin-top:0">① 安装用户脚本（推荐，Brave 已装 Tampermonkey）</h2>
<p>点击 <a class="btn" href="/tgshare.user.js">安装 TGShare 用户脚本</a>，Tampermonkey 会弹出安装确认。<br>
<span class="badge">备选：无扩展方案 → 把下面这个书签小工具拖到书签栏，进 X 页面点一次即可注入按钮：</span><br>
<a class="mono" href="{bookmarklet}">📮 TGShare 注入</a> <span class="badge">（受 X 的 CSP 限制，书签方式可能被拦，优先用油猴）</span></p></div>

<div class="step"><h2 style="margin-top:0">② 配置目标聊天</h2>
<p>编辑 <code>{cfg_path}</code> 的 <code>targets</code> 数组（改完保存，X 页面点悬浮面板的「刷新配置」即可生效）。<br>
或打开 <a href="/pick">聊天选择器 /pick</a>，搜索并复制目标聊天。</p>
<p class="badge">当前目标：</p><ul>{target_html}</ul></div>

<div class="step"><h2 style="margin-top:0">③ 使用</h2>
<p>刷新 X 页面 → 每条推文操作栏最右侧出现 <b>✈ 分享按钮</b>，点击弹出目标列表，一键发送；页面右下角有 <b>TGShare 悬浮按钮</b>（含全部目标、复制链接、t.me 分享、刷新配置）。</p>
<p class="badge">链接会自动转换为 <b>{cfg['service']}</b> 域名（x.com→fixupx.com / fixvx.com；twitter.com→fxtwitter.com / vxtwitter.com）。中继不可用时按 config 的 fallback 复制链接或打开 t.me 分享。</p></div>

<p class="badge">服务由 <code>server.py</code> 提供（开机自启）。日志：<code>{LOG_PATH}</code>。改端口/模式后重启服务。</p>
</body></html>"""


async def handle_index(request):
    return web.Response(text=index_page(request.app["cfg"]), content_type="text/html", charset="utf-8")


async def handle_pick(request):
    return web.Response(text=PICK_PAGE, content_type="text/html", charset="utf-8")


# ---------------- app ----------------

@web.middleware
async def cors_mw(request, handler):
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Auth-Token"
    resp.headers["Access-Control-Allow-Private-Network"] = "true"
    return resp


async def on_startup(app):
    app["http"] = aiohttp.ClientSession()
    cfg = app["cfg"]
    # 全局或任一目标需要 userbot 身份时，都建立 Telethon 会话
    modes = {str(cfg.get("mode") or "userbot").lower()}
    for t in cfg.get("targets", []):
        if t.get("mode"):
            modes.add(str(t["mode"]).lower())
    if "userbot" in modes:
        # 后台任务：HTTP 服务立即就绪，Telethon 在后台连接（含网络未就绪时的长重试）
        asyncio.create_task(setup_telethon(app, cfg))
    logging.info("TGShare 中继已启动: http://127.0.0.1:%s  mode=%s", cfg["port"], cfg.get("mode"))


async def on_cleanup(app):
    http = app.get("http")
    if http:
        await http.close()
    client = app.get("client")
    if client:
        await client.disconnect()


def build_app(cfg):
    app = web.Application(middlewares=[cors_mw])
    app["cfg"] = cfg
    app.router.add_get("/", handle_index)
    app.router.add_get("/tgshare.user.js", lambda r: handle_script(r, "tgshare.user.js"))
    app.router.add_get("/inject.js", lambda r: handle_script(r, "inject.js"))
    app.router.add_get("/config.js", handle_config_js)
    app.router.add_post("/config", handle_config_update)
    app.router.add_get("/status", handle_status)
    app.router.add_post("/send", handle_send)
    app.router.add_get("/dialogs", handle_dialogs)
    app.router.add_get("/pick", handle_pick)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


# ---------------- login ----------------

async def do_login(cfg):
    from telethon import TelegramClient

    client = TelegramClient(str(BASE / cfg["session_name"]), int(cfg["api_id"]), cfg["api_hash"])
    await client.connect()
    print("== TGShare 登录（Telethon）==")
    await client.start()
    me = await client.get_me()
    print(f"\n登录成功: {me.first_name} @{me.username} (id={me.id})")
    await client.disconnect()


def main():
    ap = argparse.ArgumentParser(description="TGShare 本地中继")
    ap.add_argument("--login", action="store_true", help="userbot 模式交互式登录")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config()
    if args.port:
        cfg["port"] = args.port
        save_config(cfg)

    setup_logging()

    if args.login:
        try:
            asyncio.run(do_login(cfg))
        except KeyboardInterrupt:
            print("\n已取消")
        return

    web.run_app(build_app(cfg), host="127.0.0.1", port=cfg["port"], print=None)


if __name__ == "__main__":
    main()
