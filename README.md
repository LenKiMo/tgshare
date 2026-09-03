# TGShare ✈

> X/Twitter 一键分享到 Telegram —— 推文旁加分享按钮，一条链接直接发到指定频道/群组/机器人

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Tampermonkey](https://img.shields.io/badge/Tampermonkey-%E2%9C%93-black.svg)](tgshare.user.js)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/LenKiMo/tgshare)

在 X（原 Twitter）每条推文的操作栏注入一个纸飞机分享按钮（克隆原生按钮、样式零违和），点击后把推文链接转换成 Telegram 可解析预览的 **fixupx / fixvx / fxtwitter / vxtwitter** 域名，一键发送到你预设的频道、群组或机器人。

```
浏览器（Tampermonkey 油猴脚本）→ 本地中继(127.0.0.1:8787) → Telethon / Bot API → Telegram
```

## 📑 目录

- [✨ 功能特性](#-功能特性)
- [🧱 架构](#-架构)
- [🚀 快速开始](#-快速开始)
- [⚙️ 配置](#️-配置)
- [🎯 使用](#-使用)
- [🔒 安全设计](#-安全设计)
- [❓ 常见问题](#-常见问题)
- [📁 项目结构](#-项目结构)
- [🤖 AIGC 声明](#-aigc-声明)
- [📄 许可证](#-许可证)

## ✨ 功能特性

- **一键直达**：推文操作栏新增分享按钮（克隆原生按钮实现，尺寸/间距/悬停与 X 完全一致），点击弹出目标列表，再点即发送
- **多种链接修复域名**：发送前自动转换 `x.com → fixupx.com`、`twitter.com → fxtwitter.com`（可切 fixvx / vxtwitter），Telegram 内显示完整媒体预览
- **两种发送通道**：
  - `userbot`（默认）：Telethon 以自己的 Telegram 账号发送，消息与你手动发的一模一样，可发给**任何**聊天（含机器人）
  - `bot`：Bot API token，免登录，消息来自机器人
- **按目标选身份**：每个目标可单独指定发送者——有的目标用自己账号、有的用某个机器人；支持**多机器人注册表**（`bots`），互不干扰
- **目标随时改**：`config.json` 里维护按钮与目标聊天，浏览器端点「刷新配置」即时生效；也可用内置的 `/pick` 页面从聊天列表挑选
- **本地化域名面板**：悬浮面板内一键切换 fixupx/fixvx/fxtwitter/vxtwitter（持久化）
- **原生外观**：悬浮按钮实时克隆 X 原生按钮的绘制参数（背景/边框/尺寸/图标），带 2 秒自愈防漂移；大图/弹窗查看时自动隐藏
- **低干扰**：观察器仅在新增推文时扫描；请求经 `GM_xmlhttpRequest`（扩展上下文），绕开浏览器对页面访问本机服务的限制
- **安全默认**：仅监听 127.0.0.1、CORS 仅放行 x.com/twitter.com、`/send` 需令牌 + 目标白名单

## 🧱 架构

```
┌─────────────┐   GM_xmlhttpRequest    ┌──────────────────┐   MTProto / HTTP   ┌──────────┐
│  X / Twitter │ ────────────────────▶ │ 本地中继 server.py │ ─────────────────▶ │ Telegram │
│  (油猴脚本)  │    http://127.0.0.1   │  aiohttp+Telethon │                    │ (你的账号)│
└─────────────┘      :8787             └──────────────────┘                    └──────────┘
```

- **浏览器端**（`tgshare.user.js`）：注入推文按钮 + 悬浮面板；链接域名转换；配置拉取（`/config.js`）
- **中继**（`server.py`）：令牌鉴权、目标白名单、Telethon/Bot 发送、`/pick` 聊天选择器、安装页
- 中继不可达时自动降级：复制转换后链接 或 打开 t.me 分享对话框（可配置）

## 🚀 快速开始

### 0. 前置

- Python 3.11+（建议 [uv](https://github.com/astral-sh/uv) 管理虚拟环境）
- 装有 Tampermonkey（或 Violentmonkey）的 Chromium 系浏览器（Chrome / Edge / Brave）
- 一个 Telegram 账号（userbot 模式）或一个 Bot token（bot 模式）

### 1. 启动中继服务

```bash
git clone https://github.com/LenKiMo/tgshare.git
cd tgshare

# 依赖（uv 或 pip 均可）
uv venv .venv --python 3.11
uv pip install -p .venv/Scripts/python.exe -r requirements.txt
# 或：python -m venv .venv && .venv/Scripts/pip install -r requirements.txt

# 配置
cp config.example.json config.json   # Windows: copy config.example.json config.json
#   编辑 config.json：填入 api_id / api_hash（my.telegram.org 申请）与 targets
```

**userbot 模式需要登录一次**（交互式，验证码与两步验证密码在你自己的终端输入）：

```bash
.venv/Scripts/python.exe server.py --login
# 若未预填手机号：.venv/Scripts/python.exe login2.py <带国家码手机号>
```

启动服务：

```bash
.venv/Scripts/python.exe server.py
# 验证：curl http://127.0.0.1:8787/status  → {"ok":true,"mode":"userbot","authed":true,...}
```

### 2. 安装浏览器脚本

浏览器打开 `http://127.0.0.1:8787/`（安装页）→ 点击「安装用户脚本」→ Tampermonkey 确认。

刷新 X 页面即生效：每条推文操作栏末尾出现纸飞机按钮；右下角有悬浮面板。

## ⚙️ 配置

编辑 `config.json`（改完在 X 页面悬浮面板点「刷新配置」，或重载页面）：

```jsonc
{
  "mode": "userbot",            // 全局默认身份：userbot（自己账号）| bot（Bot API）
  "api_id": 12345678,           // my.telegram.org 申请
  "api_hash": "…",
  "bot_token": "",              // mode=bot（未指定别名时）使用的 token，@BotFather 创建
  "port": 8787,                 // 中继端口（浏览器脚本默认匹配，改后需同步改 tgshare.user.js 顶部 EMBED.relay）
  "service": "fixupx",          // fixupx | fixvx | fxtwitter | vxtwitter（面板可切换）
  "fallback": "copy",           // 中继不可达时：copy=复制链接 | share=打开 t.me 分享
  "text_template": "{link}",    // 发送模板，可加前缀如 "📌 {link}"
  "bots": {                     // 多机器人注册表（token 只存本机，不下发浏览器）
    "botA": "123456:AA…",       //   别名 → token
    "botB": "654321:BB…"
  },
  "targets": [
    { "label": "我的收藏", "chat": "me" },                       // me = 我的收藏/保存的消息
    { "label": "自己的群", "chat": "@mygroup" },                 // 普通群组：userbot 或机器人成员均可发
    { "label": "个人频道", "chat": "@mychannel" },               // 默认身份（全局 mode）发送
    { "label": "机器人代发", "chat": -1001234567890,             // 数字 ID（群/频道为负数）
      "mode": "bot", "bot": "botA" }                             //   该目标用 botA 身份发送
  ]
}
```

**身份规则**：目标的 `mode` / `bot` 字段覆盖全局 `mode`（写了 `bot` 别名即隐含 bot 模式）。发送权限提醒：**频道**里机器人必须是**管理员**才能发消息；**普通群组**机器人作为普通成员即可发言（除非群开启"仅管理员可发言"）；`chat: "me"` 需要你先给该机器人发一条消息（用于解析你的私聊 id）。

> `auth_token` 留空会自动生成（浏览器脚本通过 `/config.js` 获取，用于 `/send` 鉴权）。
> userbot 模式下可用 `http://127.0.0.1:8787/pick` 可视化挑选目标聊天。

## 🎯 使用

| 动作 | 方式 |
|---|---|
| 分享当前推文到某个目标 | 点推文下方 ✈ → 选目标 |
| 分享视口中央的推文 | 点右下角悬浮 ✈ → 选目标（或「发送到全部」） |
| 切换链接域名 | 悬浮面板 →「链接域名：fixupx」循环切换 |
| 复制转换后链接 | 任一菜单的「复制转换后链接」 |
| 手动分享 | 菜单「t.me 分享对话框」 |

链接转换规则：`x.com → fixupx.com`（或 fixvx.com），`twitter.com → fxtwitter.com`（或 vxtwitter.com）。

## 🔒 安全设计

- 中继只监听 `127.0.0.1`，不暴露到局域网/公网
- CORS 仅放行 `https://x.com` 与 `https://twitter.com`
- `/send` 与 `/dialogs` 需要 `X-Auth-Token` 头（令牌在 config.json，首次启动自动生成）
- `/send` 的目标必须是 `targets` 白名单内 —— 即使令牌泄露，也只能发到你自己的预设聊天
- 多机器人 token 只存在本机 `config.json` 的 `bots` 注册表，`/config.js` 不下发给浏览器（浏览器只拿到目标别名）
- `tgshare.session`（Telethon 会话）等于账号钥匙：勿提交、勿外传、勿放云盘
- 浏览器端必须用 `GM_xmlhttpRequest` 而非页面 `fetch`：新版 Chromium 的 Local Network Access 限制会拦截页面访问本机服务（详见 FAQ）

## ❓ 常见问题

**Q：面板显示「离线」？**
中继没起来：`curl http://127.0.0.1:8787/status`。若服务正常仍离线，检查 `config.json` 的 `port` 与脚本内 `EMBED.relay` 是否一致。

**Q：为什么用 GM_xmlhttpRequest？**
Chrome 142+ 启用了 Local Network Access（LNA）权限模型：https 页面直接 `fetch` 本机 `http://127.0.0.1` 会被以 `LocalNetworkAccessPermissionDenied` 拒绝，且**服务端响应头无法放行**。`GM_xmlhttpRequest` 由扩展上下文发起，天然豁免。

**Q：X 页面变卡？**
观察器只在新增推文时扫描，负载可忽略。若仍有大量 `ERR_BLOCKED_BY_CLIENT` 报错，通常是广告拦截器拦了 X 的 `viewer_context.json` 接口，与本项目无关。

**Q：userbot 登录时提示风控/验证码？**
建议使用自己的 `api_id/api_hash`（公用凭据容易触发风控）；`RECAPTCHA` 类拦截可稍后或换网络环境重试。

**Q：可以换端口吗？**
可以，改 `config.json` 的 `port`，同时把 `tgshare.user.js` 顶部 `EMBED.relay` 与安装页地址同步修改。

## 📁 项目结构

```
tgshare/
├── server.py            # 本地中继：aiohttp + Telethon / Bot API，/send /config.js /pick 等
├── tgshare.user.js      # 油猴用户脚本（浏览器端全部逻辑）
├── login2.py            # 显式登录脚本（验证码 + 2FA 在本地终端输入）
├── config.example.json  # 配置模板（config.json 不入库）
├── requirements.txt
├── LICENSE
└── README.md
```

## 🤖 AIGC 声明

本仓库代码与文档由 AI 辅助生成（Hermes Agent，基于 DeepSeek 系列模型），并经过人工审查与实测验证。链接修复域名规则、X 页面 DOM 适配等技术细节会随平台变动更新。

## 📄 许可证

[MIT License](LICENSE)

---

**免责声明**：本项目仅供个人自动化与效率提升使用。请遵守 X / Twitter 与 Telegram 的平台条款，自行承担使用风险。本项目与 X（Twitter）及 Telegram 官方无任何关联。
