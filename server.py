#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TGShare 本地中继服务
X/Twitter 一键分享到 Telegram：
  浏览器用户脚本 → http://127.0.0.1:<port>/send → (Telethon 自己账号 | Bot API) → Telegram

分享形式（config.json 的 share_mode，面板可切；单个目标可覆盖）：
  link   只发链接：x.com → fixupx/fixvx 等镜像域（Telegram 抓预览图）
  photo  发图片：推文首图 + 正文作 caption，链接用**原版** x.com/twitter.com
  album  发相册：多图逐张原图（≤10 张）+ caption，链接用原版
  mosaic 发拼图：多图拼成一张 + caption，链接用原版
  媒体来源：优先用页面 DOM 里的图（浏览器已登录 X，无需外部服务）；
           取不到（视频帖/懒加载失败）时回退 api.fxtwitter.com。

用法：
  python server.py --login    # userbot 模式首次登录（交互式：手机号+验证码+2FA）
  python server.py            # 启动服务（默认 127.0.0.1:8787）
"""
import argparse
import asyncio
import hmac
import json
import logging
import re
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
    "caption_template": "{text}\n\n{link}",
    "share_mode": "link",
    "official_domain": "",
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
        "_comment_share_mode": "share_mode: link=只发链接(镜像域) | photo=发首图+原版链接 | album=发全部原图相册+原版链接 | mosaic=多图拼成一张+原版链接。单个目标可写 share_mode 覆盖；official_domain 非空(如 \"x.com\")时媒体模式强制用该官方域",
        "_comment_caption_template": "caption_template: 媒体模式（图片/相册/拼图）的配文模板，{text}=推文正文, {link}=原版链接；正文缺失时退回 text_template",
        **cfg,
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


_cfg_mtime = {"t": 0.0}


def maybe_reload_config(app):
    """config.json 被手工改过就热重载（浏览器端点「刷新配置」即可生效，无需重启）。"""
    try:
        t = CONFIG_PATH.stat().st_mtime
    except OSError:
        return app["cfg"]
    if t != _cfg_mtime["t"]:
        _cfg_mtime["t"] = t
        try:
            fresh = load_config()
        except Exception as e:                     # 手改坏 JSON 时别把服务打死
            logging.warning("config.json 解析失败（沿用旧配置）: %s", str(e)[:160])
            return app["cfg"]
        app["cfg"].clear()
        app["cfg"].update(fresh)
        logging.info("config.json 有变动，已热重载（share_mode=%s）", fresh.get("share_mode"))
    return app["cfg"]


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
    logging.getLogger("telethon").setLevel(logging.CRITICAL)
    logging.getLogger("aiohttp").setLevel(logging.CRITICAL)


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


# ---------------- 媒体（图片 / 相册模式） ----------------

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130 Safari/537.36")
SHARE_MODES = ("link", "photo", "album", "mosaic")
SHARE_LABELS = {"link": "仅链接", "photo": "图片", "album": "相册", "mosaic": "拼图"}
MAX_CAPTION = 1024              # 媒体消息 caption 上限（正文更长就退化发链接）
PHOTO_MAX = 9_500_000          # 单张图片字节上限（Bot API 10MB，留余量）
VIDEO_MAX = 45 * 1024 * 1024   # 视频上限（Bot API 50MB，留余量）
ALBUM_MAX = 10                 # Telegram 相册上限
MOSAIC_HOST = "https://mosaic.fxtwitter.com/jpeg"

SERVICE_MAP = {
    "fixupx":    {"x.com": "fixupx.com", "twitter.com": "fxtwitter.com"},
    "fixvx":     {"x.com": "fixvx.com", "twitter.com": "vxtwitter.com"},
    "fxtwitter": {"x.com": "fixupx.com", "twitter.com": "fxtwitter.com"},
    "vxtwitter": {"x.com": "fixvx.com", "twitter.com": "vxtwitter.com"},
}
# fx 镜像域 ↔ 官方域成对关系（媒体模式一律用官方域；也是补图工具的同一套映射）
OFFICIAL_MAP = {
    "fixupx.com": "x.com", "fxupx.com": "x.com", "fixvx.com": "x.com", "fxvx.com": "x.com",
    "fxtwitter.com": "twitter.com", "vxtwitter.com": "twitter.com",
}
FX_HOST_RE = re.compile(r"(?i)\b(?:www\.)?(fixupx|fxupx|fixvx|fxvx|fxtwitter|vxtwitter)\.com\b")
TWEET_RE = re.compile(
    r"https?://(?:www\.)?(?:x|twitter|fixupx|fixvx|fxupx|fxvx|fxtwitter|vxtwitter)\.com"
    r"/([A-Za-z0-9_]{1,20})/status/(\d+)")


class Media:
    __slots__ = ("kind", "url", "name", "thumb")

    def __init__(self, kind, url, name="media", thumb=None):
        self.kind = kind          # photo | video
        self.url = url
        self.name = name
        self.thumb = thumb        # 视频封面（视频下载失败时退回封面图）

    def __repr__(self):
        return f"<{self.kind} {self.name} {self.url[:60]}>"


def resolve_share_mode(cfg, target=None):
    """目标级 share_mode 覆盖全局；未知值一律当 link（保持旧行为）。"""
    raw = (target or {}).get("share_mode") or cfg.get("share_mode") or "link"
    m = str(raw).strip().lower()
    if m in ("media", "image", "images", "gallery"):     # 别名，宽容处理
        m = "album"
    return m if m in SHARE_MODES else "link"


def convert_link(service, link):
    """x.com/twitter.com → fixupx/fixvx 等镜像域（Telegram 抓预览用）。"""
    m = re.match(r"^https?://(?:www\.)?([^/]+)/(.*)$", link or "")
    if not m:
        return link
    dom = (SERVICE_MAP.get(service) or SERVICE_MAP["fixupx"]).get(m.group(1).lower())
    return f"https://{dom}/{m.group(2)}" if dom else link


def official_link(link, force=""):
    """镜像域 → 官方域（fixupx/fixvx→x.com，fxtwitter/vxtwitter→twitter.com）。

    force 非空（config 的 official_domain，如 "x.com"）时统一改成它；
    本来就是官方域的链接原样保留 —— 媒体模式的链接要求「原版」。
    """
    def _sub(m):
        host = (m.group(1) or "").lower() + ".com"
        return force or OFFICIAL_MAP.get(host, m.group(0))

    return FX_HOST_RE.sub(_sub, link or "")


def build_text(cfg, link, target=None):
    tpl = (target or {}).get("text_template") or cfg.get("text_template") or "{link}"
    return tpl.replace("{link}", link)


def media_key(url):
    """pbs.twimg.com/media/HR2rD3eagAAukv1?format=jpg&name=small -> HR2rD3eagAAukv1"""
    return re.sub(r"\?.*$", "", url).split("/")[-1].rsplit(".", 1)[0]


def photo_orig(url):
    """把页面里的缩略图 URL 改成原图（name=orig）——只是候选链的第一站。"""
    if re.search(r"[?&]name=", url or ""):
        return re.sub(r"name=\w+", "name=orig", url)
    if url and "?" in url:
        return url + "&name=orig"
    return url


def photo_large(url):
    """原图过大时的次选（2048px）。"""
    if re.search(r"[?&]name=", url or ""):
        return re.sub(r"name=\w+", "name=large", url)
    return url


def _split_query(url):
    if "?" not in (url or ""):
        return url, ""
    base, q = url.split("?", 1)
    return base, q


def photo_candidates(url):
    """图片候选 URL 链（原图优先）：
      ① 去掉页面上的 name/format 后按原图请求（页面常见 ?format=webp&name=large 会被换成 jpg 原图）
      ② 原图但保留 png/gif 原始格式
      ③ 页面里原样的 URL（体积/格式兜底，保证总有东西能发出去）
    """
    base, q = _split_query(url or "")
    keep = (re.search(r"[?&]format=(\w+)", url or "") or [None, "jpg"])[1].lower()
    keep = keep if keep in ("png", "gif") else "jpg"
    rest = "&".join(kv for kv in q.split("&") if kv and kv.split("=", 1)[0] not in ("name", "format"))
    out = []
    for fmt in dict.fromkeys([keep, "jpg"]):
        out.append(f"{base}?" + "&".join(x for x in (rest, f"format={fmt}", "name=orig") if x))
    out.append(url)
    return list(dict.fromkeys([u for u in out if u]))


def sniff_image(blob):
    """按幻数判断真实图片格式（页面 URL 的 format 参数不可全信）。"""
    if blob[:3] == b"\xff\xd8\xff":
        return ".jpg", "image/jpeg"
    if blob[:1] == b"\x89" and blob[1:4] == b"PNG":
        return ".png", "image/png"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if blob[:3] == b"GIF":
        return ".gif", "image/gif"
    return ".jpg", "image/jpeg"


async def fetch_bytes(app, url, timeout=120):
    headers = {"User-Agent": UA, "Referer": "https://x.com/"}
    async with app["http"].get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=timeout)) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status} {url[:60]}")
        return await r.read()


async def fetch_photo(app, url):
    """按候选链下载图片：返回 (字节, 扩展名, MIME)。"""
    errs = []
    cands = photo_candidates(url)
    for i, cand in enumerate(cands):
        try:
            blob = await fetch_bytes(app, cand)
        except Exception as e:                       # noqa: BLE001
            errs.append(f"{type(e).__name__}@{cand[-36:]}")
            continue
        if len(blob) < 2048:
            errs.append("too_small")
            continue
        if len(blob) > PHOTO_MAX:
            errs.append(f"too_big({len(blob) / 1048576:.1f}MB)")
            continue
        ext, mime = sniff_image(blob)
        logging.info("photo: 候选%d/%d %s (%.0fKB %s)", i + 1, len(cands), cand[:100], len(blob) / 1024, ext)
        return blob, ext, mime
    raise RuntimeError(f"图片下载失败 {errs[:3]}")


def dom_media(payload, cfg=None):
    """把浏览器脚本发来的媒体信息转成 Media 列表（图片一律取原图）。"""
    out = []
    if not isinstance(payload, dict):
        return out
    for u in (payload.get("photos") or [])[:ALBUM_MAX]:
        if isinstance(u, str) and u.startswith("http"):
            out.append(Media("photo", photo_orig(u), "photo.jpg"))
    v = payload.get("video")
    if isinstance(v, str) and "video.twimg.com" in v:
        out.append(Media("video", v, "video.mp4", thumb=payload.get("poster")))
    return out


async def api_media(app, link):
    """回退路线：api.fxtwitter.com 解析推文媒体（DOM 拿不到时用，如视频帖）。

    返回 (media, 正文文本)。
    """
    m = TWEET_RE.search(link or "")
    if not m:
        return [], ""
    user, sid = m.group(1), m.group(2)
    raw = await fetch_bytes(app, f"https://api.fxtwitter.com/{user}/status/{sid}", timeout=45)
    tweet = (json.loads(raw.decode("utf-8", "ignore")) or {}).get("tweet") or {}
    media = tweet.get("media") or {}
    out = []
    for ph in (media.get("photos") or [])[:ALBUM_MAX]:
        u = ph.get("url") or ""
        if u:
            out.append(Media("photo", photo_orig(u), "photo.jpg"))
    for v in media.get("videos") or []:
        best = max((x for x in (v.get("variants") or []) if ".mp4" in (x.get("url") or "")),
                   key=lambda x: x.get("bitrate", 0), default=None)
        if best:
            out.append(Media("video", best["url"], f"{sid}.mp4", thumb=v.get("thumbnail_url")))
    return out, (tweet.get("text") or "")


def plan_media(items, mode, link=""):
    """决定发什么：返回 (kind, [Media...])，kind ∈ photo | album | video。"""
    photos = [m for m in items if m.kind == "photo"]
    videos = [m for m in items if m.kind == "video"]
    if videos:                       # 含视频的推文不走相册（与补图工具同策略）
        return "video", videos[:1]
    if not photos:
        return "", []
    if mode == "mosaic" and len(photos) > 1:
        sid = (TWEET_RE.search(link).group(2) if TWEET_RE.search(link) else "")
        keys = "/".join(media_key(p.url) for p in photos[:ALBUM_MAX])
        if sid and keys:
            return "photo", [Media("photo", f"{MOSAIC_HOST}/{sid}/{keys}", "mosaic.jpg")]
    if mode == "photo" or len(photos) == 1:
        return "photo", photos[:1]
    return "album", photos[:ALBUM_MAX]


async def send_media_userbot(app, chat, kind, items, caption):
    """userbot：Telethon 直接发图/相册（消息来自你自己，任何聊天都能发）。"""
    client = await _ensure_client(app)
    if not await client.is_user_authorized():
        raise RuntimeError("userbot 未登录，请先运行 python server.py --login")
    tmpdir = BASE / "tmp_media"
    tmpdir.mkdir(exist_ok=True)
    paths, total = [], 0
    try:
        for m in items:
            if m.kind == "video":
                blob = await fetch_bytes(app, m.url)
                if len(blob) > VIDEO_MAX:
                    raise RuntimeError(f"视频过大 {len(blob) / 1048576:.1f}MB")
                ext = ".mp4"
            else:
                blob, ext, _ = await fetch_photo(app, m.url)
            p = tmpdir / f"tg_{secrets.token_hex(4)}{ext}"
            p.write_bytes(blob)
            paths.append(p)
            total += len(blob)
        if len(paths) == 1:
            msg = await client.send_file(normalize_chat(chat), str(paths[0]), caption=caption or None)
            ids = [getattr(msg, "id", None)]
        else:
            msgs = await client.send_file(normalize_chat(chat), [str(p) for p in paths],
                                          caption=caption or None)
            ids = [getattr(x, "id", None) for x in (msgs if isinstance(msgs, list) else [msgs])]
    finally:
        for p in paths:
            try:
                p.unlink()
            except OSError:
                pass
    return {"kind": kind, "count": len(ids), "ids": ids, "bytes": total}


async def bot_api(app, token, method, data=None, files=None, timeout=420):
    """Bot API 调用；files=[(字段名, 文件名, 字节, MIME)] 时走 multipart 上传字节。"""
    def _field(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return v
        if isinstance(v, (int, float)):
            return str(v)
        return json.dumps(v, ensure_ascii=False)

    url = f"https://api.telegram.org/bot{token}/{method}"
    http = app["http"]
    if files:
        form = aiohttp.FormData()
        for k, v in (data or {}).items():
            form.add_field(k, _field(v))
        for field, fname, blob, ctype in files:
            form.add_field(field, blob, filename=fname, content_type=ctype)
        kwargs = {"data": form}
    else:
        kwargs = {"json": data or {}}
    async with http.post(url, timeout=aiohttp.ClientTimeout(total=timeout), **kwargs) as r:
        out = await r.json(content_type=None)
    if not out.get("ok"):
        raise RuntimeError(out.get("description") or f"HTTP {r.status}")
    return out["result"]


async def send_media_bot(app, chat, token, kind, items, caption):
    """bot 模式：Bot API 上传字节发图/相册/视频。"""
    if not token:
        token = app["cfg"].get("bot_token") or ""
    if not token:
        raise RuntimeError("bot_token 未配置（mode=bot 需要）")
    if chat == "me":
        chat = await resolve_bot_owner(app, token)
    blobs = []
    for m in items:
        if m.kind == "video":
            blob = await fetch_bytes(app, m.url)
            if len(blob) > VIDEO_MAX:
                raise RuntimeError(f"视频过大 {len(blob) / 1048576:.1f}MB")
            blobs.append((m.name or "video.mp4", blob, "video/mp4"))
        else:
            blob, ext, mime = await fetch_photo(app, m.url)
            blobs.append((f"photo{ext}", blob, mime))
    total = sum(len(b) for _, b, _ in blobs)
    if kind == "album" and len(blobs) > 1:
        media = []
        for i in range(len(blobs)):
            item = {"type": "photo", "media": f"attach://up{i}"}
            if i == 0 and caption:
                item["caption"] = caption          # 相册只有第一条挂 caption
            media.append(item)
        files = [(f"up{i}", n, b, c) for i, (n, b, c) in enumerate(blobs)]
        res = await bot_api(app, token, "sendMediaGroup",
                            {"chat_id": chat, "media": media}, files)
        ids = [m.get("message_id") for m in res if isinstance(m, dict)]
        kind = "album"
    elif blobs[0][2].startswith("video"):
        res = await bot_api(app, token, "sendVideo",
                            {"chat_id": chat, "caption": caption or "", "supports_streaming": True},
                            [("video", blobs[0][0], blobs[0][1], blobs[0][2])])
        ids = [res.get("message_id")]
        kind = "video"
    else:
        res = await bot_api(app, token, "sendPhoto",
                            {"chat_id": chat, "caption": caption or ""},
                            [("photo", blobs[0][0], blobs[0][1], blobs[0][2])])
        ids = [res.get("message_id")]
        kind = "photo"
    return {"kind": kind, "count": len(ids), "ids": ids, "bytes": total}


def build_caption(cfg, target, official, tweet_text=""):
    """媒体模式的配文：默认「原文 + 原版链接」；没有原文时退回 text_template。"""
    tt = (tweet_text or "").strip()
    if not tt:
        return build_text(cfg, official, target)
    tpl = (target or {}).get("caption_template") or cfg.get("caption_template") or "{text}\n\n{link}"
    return tpl.replace("{text}", tt).replace("{link}", official).strip()


async def send_media(app, cfg, target, sender, token, chat, link, payload_media, tweet_text=""):
    """媒体模式总入口：解析媒体 → 发送。返回 {kind, count, link, caption, source}。

    任何一步失败都抛异常，由 handle_send 退化为「发链接」，绝不静默丢消息。
    """
    mode = resolve_share_mode(cfg, target)
    force = (target.get("official_domain") or cfg.get("official_domain") or "").strip()
    official = official_link(link, force)

    items = dom_media(payload_media)
    source = "dom"
    if not items or not [m for m in items if m.kind == "photo"]:
        try:
            api, api_text = await api_media(app, link)
        except Exception as e:                         # noqa: BLE001
            api, api_text = [], ""
            logging.warning("api.fxtwitter.com 解析失败（%s），继续用页面里的媒体", str(e)[:120])
        if api:
            items = api
            source = "api"
        if not tweet_text:
            tweet_text = api_text
    if not items and isinstance(payload_media, dict) and payload_media.get("poster"):
        # 页面只给得出视频封面时，至少把封面图配上原文发出去
        items = [Media("photo", photo_orig(payload_media["poster"]), "poster.jpg")]
        source = "dom"
    if not items:
        raise RuntimeError("推文没有可用的媒体（可能是纯文字/转推/已删除）")

    caption = build_caption(cfg, target, official, tweet_text)
    if len(caption) > MAX_CAPTION:
        raise RuntimeError(f"caption 超长（{len(caption)}>{MAX_CAPTION}），按链接发送")

    kind, picked = plan_media(items, mode, link)
    if not picked:
        raise RuntimeError("没有可发送的媒体")
    logging.info("media: mode=%s source=%s kind=%s n=%d link=%s", mode, source, kind, len(picked), official)
    try:
        if sender == "bot":
            r = await send_media_bot(app, chat, token, kind, picked, caption)
        else:
            r = await send_media_userbot(app, chat, kind, picked, caption)
    except Exception as e:
        # 视频帖：mp4 拉不下来就退回它的封面图，别白丢一次分享
        if kind == "video" and picked[0].thumb:
            logging.warning("视频发送失败(%s)，改发封面图", e)
            poster = [Media("photo", picked[0].thumb, "poster.jpg")]
            if sender == "bot":
                r = await send_media_bot(app, chat, token, "photo", poster, caption)
            else:
                r = await send_media_userbot(app, chat, "photo", poster, caption)
        else:
            raise
    r.update({"link": official, "caption": caption, "source": source})
    return r


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
    link = (data.get("link") or "").strip()
    text = (data.get("text") or "").strip()
    if not chat or not (link or text):
        return web.json_response({"ok": False, "error": "chat 必填，且 link/text 至少给一个"}, status=400)
    target = find_target(cfg, chat)
    if target is None:
        return web.json_response({"ok": False, "error": "该目标不在白名单，请先加入 config.json 的 targets"}, status=403)
    try:
        sender, token = resolve_sender(cfg, target)
        mode = resolve_share_mode(cfg, target)
        media_error = None
        # ① 媒体模式：发图/相册（链接用原版 x.com / twitter.com）
        if link and mode != "link":
            try:
                r = await send_media(request.app, cfg, target, sender, token, chat, link,
                                     data.get("media"), data.get("tweet_text") or "")
            except Exception as e:                     # noqa: BLE001
                media_error = str(e)[:200]
                logging.warning("媒体模式未成功（%s），退化为链接消息", media_error)
            else:
                logging.info("sent %s x%s to %s [%s]: %s", r["kind"], r["count"], chat, sender, r["link"])
                return web.json_response({
                    "ok": True, "message_id": (r.get("ids") or [None])[0],
                    "kind": r["kind"], "count": r["count"], "link": r["link"], "source": r.get("source"),
                })
        # ② 链接模式（或媒体模式退化）：正文链接用镜像域，Telegram 才能抓到预览图
        if link:
            conv = convert_link(cfg.get("service"), link) if TWEET_RE.search(link) else link
            body = build_text(cfg, conv, target)
        else:
            body = text
        if len(body) > 4096:
            return web.json_response({"ok": False, "error": "text 过长"}, status=400)
        if sender == "bot":
            mid = await send_bot(request.app, chat, body, token)
        else:
            mid = await send_userbot(request.app, chat, body)
    except Exception as e:
        logging.exception("send failed")
        return web.json_response({"ok": False, "error": str(e)[:300]}, status=500)
    logging.info("sent to %s [%s]: %.80s", chat, sender, body)
    return web.json_response({"ok": True, "message_id": mid, "kind": "link", "link": body,
                              "media_error": media_error})


async def handle_config_js(request):
    cfg = request.app["cfg"]
    pub = {
        "relay": f"http://127.0.0.1:{cfg['port']}",
        "service": cfg.get("service", "fixupx"),
        "fallback": cfg.get("fallback", "copy"),
        "textTemplate": cfg.get("text_template", "{link}"),
        "shareMode": resolve_share_mode(cfg),
        "officialDomain": cfg.get("official_domain") or "",
        "targets": cfg.get("targets", []),
        "authToken": cfg["auth_token"],
        "version": 2,
    }
    body = "window.TGShareConfig = " + json.dumps(pub, ensure_ascii=False) + ";"
    return web.Response(text=body, content_type="application/javascript")


SERVICES = {"fixupx", "fixvx", "fxtwitter", "vxtwitter"}
OFFICIAL_DOMAINS = {"", "x.com", "twitter.com"}


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
    if "share_mode" in data:
        sm = str(data.get("share_mode", "")).strip().lower()
        if sm in ("media", "image", "images", "gallery"):
            sm = "album"
        if sm not in SHARE_MODES:
            return web.json_response({"ok": False, "error": "share_mode 可选: link/photo/album/mosaic"}, status=400)
        cfg["share_mode"] = sm
    if "official_domain" in data:
        od = str(data.get("official_domain", "")).strip().lower()
        if od not in OFFICIAL_DOMAINS:
            return web.json_response({"ok": False, "error": "official_domain 可选: 空/x.com/twitter.com"}, status=400)
        cfg["official_domain"] = od
    save_config(cfg)
    logging.info("config updated: service=%s share_mode=%s", cfg["service"], resolve_share_mode(cfg))
    return web.json_response({"ok": True, "service": cfg["service"],
                              "share_mode": resolve_share_mode(cfg),
                              "official_domain": cfg.get("official_domain") or ""})


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
            "share_mode": resolve_share_mode(cfg),
            "official_domain": cfg.get("official_domain") or "",
            "targets": [t.get("label") for t in cfg.get("targets", [])],
            "version": 2,
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
    share_label = SHARE_LABELS.get(resolve_share_mode(cfg), resolve_share_mode(cfg))
    target_html = "".join(
        f'<li><code>{t.get("label")}</code> → <code>{t.get("chat")}</code>'
        + (f' · 形式 <code>{SHARE_LABELS.get(resolve_share_mode(cfg, t), "")}</code>'
           if t.get("share_mode") else "")
        + "</li>" for t in targets
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
<p class="badge">状态：mode=<b>{cfg['mode']}</b> · service=<b>{cfg['service']}</b> · 分享形式=<b>{share_label}</b> · 端口 <b>{cfg['port']}</b> · 目标 {len(targets)} 个 · 脚本版本 2</p>

<div class="step"><h2 style="margin-top:0">① 安装用户脚本（推荐，Brave 已装 Tampermonkey）</h2>
<p>点击 <a class="btn" href="/tgshare.user.js">安装 TGShare 用户脚本</a>，Tampermonkey 会弹出安装确认。<br>
<span class="badge">备选：无扩展方案 → 把下面这个书签小工具拖到书签栏，进 X 页面点一次即可注入按钮：</span><br>
<a class="mono" href="{bookmarklet}">📮 TGShare 注入</a> <span class="badge">（受 X 的 CSP 限制，书签方式可能被拦，优先用油猴）</span></p></div>

<div class="step"><h2 style="margin-top:0">② 配置目标聊天</h2>
<p>编辑 <code>{cfg_path}</code> 的 <code>targets</code> 数组（改完保存，X 页面点悬浮面板的「刷新配置」即可生效）。<br>
或打开 <a href="/pick">聊天选择器 /pick</a>，搜索并复制目标聊天。</p>
<p class="badge">当前目标：</p><ul>{target_html}</ul></div>

<div class="step"><h2 style="margin-top:0">③ 使用</h2>
<p>刷新 X 页面 → 每条推文操作栏最右侧出现 <b>✈ 分享按钮</b>，点击弹出目标列表，一键发送；页面右下角有 <b>TGShare 悬浮按钮</b>（含全部目标、切换分享形式/链接域名、复制链接、t.me 分享、刷新配置）。</p>
<p class="badge">分享形式（current: <b>{share_label}</b>）：<br>
· <b>仅链接</b>：只发一条链接，链接自动转为 <b>{cfg['service']}</b> 域名（x.com→fixupx.com / fixvx.com；twitter.com→fxtwitter.com / vxtwitter.com），Telegram 自己抓预览图；<br>
· <b>图片 / 相册 / 拼图</b>：中继把推文图片下载后<b>直接发给你</b>（首图 / 全部原图相册 / 多图拼一张），配文=推文正文 + <b>原版 x.com / twitter.com</b> 链接（模板 <code>caption_template</code>）；正文超长或无图时自动退回「仅链接」。<br>
悬浮面板点「分享形式」循环切换并写入 config.json；也可给单个目标写 <code>share_mode</code> 覆盖。<br>
中继不可用时按 config 的 fallback 复制链接或打开 t.me 分享。</p></div>

<p class="badge">服务由 <code>server.py</code> 提供（开机自启）。日志：<code>{LOG_PATH}</code>。改端口/模式后重启服务。</p>
</body></html>"""


async def handle_index(request):
    return web.Response(text=index_page(request.app["cfg"]), content_type="text/html", charset="utf-8")


async def handle_pick(request):
    return web.Response(text=PICK_PAGE, content_type="text/html", charset="utf-8")


# ---------------- app ----------------

@web.middleware
async def cors_mw(request, handler):
    maybe_reload_config(request.app)      # 手改 config.json 后无需重启
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
