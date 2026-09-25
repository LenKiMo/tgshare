// ==UserScript==
// @name         TGShare – X 一键分享到 Telegram
// @namespace    local.tgshare
// @version      1.2.0
// @description  X 推文一键分享到 Telegram：仅链接 / 图片 / 原图相册（配文用原版链接）；悬浮按钮可拖动并记住位置
// @match        https://x.com/*
// @match        https://twitter.com/*
// @run-at       document-idle
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

(function () {
  'use strict';

  // ---------- 兜底配置（会被本机中继 /config.js 覆盖） ----------
  var EMBED = {
    relay: 'http://127.0.0.1:17887',
    service: 'fixupx',        // fixupx | fixvx | fxtwitter | vxtwitter
    fallback: 'copy',         // 中继不可用时: copy=复制链接 share=打开 t.me 分享 none=不处理
    textTemplate: '{link}',
    shareMode: 'link',        // link=只发链接 | photo=发首图 | album=发原图相册 | mosaic=多图拼一张
    officialDomain: '',       // 媒体模式强制官方域（空=保留原链接）
    targets: [{ label: '我的收藏', chat: 'me' }],
    authToken: ''
  };
  var CFG = { relay: EMBED.relay, service: EMBED.service, fallback: EMBED.fallback, textTemplate: EMBED.textTemplate, shareMode: EMBED.shareMode, officialDomain: EMBED.officialDomain, targets: EMBED.targets.slice(), authToken: EMBED.authToken };
  var SHARE_MODES = ['link', 'photo', 'album', 'mosaic'];
  var SHARE_LABELS = { link: '仅链接', photo: '图片', album: '相册', mosaic: '拼图' };

  // 幂等：油猴(隔离世界) 与 书签(页面世界) 共享 DOM，用根元素标记防止重复注入
  if (document.documentElement && document.documentElement.getAttribute('data-tgshare-loaded')) return;
  document.documentElement.setAttribute('data-tgshare-loaded', '1');

  function $(s, el) { return (el || document).querySelector(s); }
  function $$(s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); }

  var ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>';

  // ---------- HTTP：优先 GM_xmlhttpRequest（扩展上下文，绕过页面 CORS/LNA），书签场景降级 fetch ----------
  function httpReq(method, url, payload, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var done = false;
      var timer = setTimeout(function () { if (!done) { done = true; reject(new Error('timeout')); } }, timeoutMs || 7000);
      function finish(err, resp) { if (!done) { done = true; clearTimeout(timer); err ? reject(err) : resolve(resp); } }
      if (typeof GM_xmlhttpRequest === 'function') {
        var opt = {
          method: method,
          url: url,
          timeout: timeoutMs || 7000,
          onload: function (r) { finish(null, { status: r.status, text: r.responseText }); },
          onerror: function () { finish(new Error('gm_xhr error')); },
          ontimeout: function () { finish(new Error('gm_xhr timeout')); }
        };
        if (payload) {
          opt.headers = { 'Content-Type': 'application/json', 'X-Auth-Token': CFG.authToken || '' };
          opt.data = JSON.stringify(payload);
        }
        GM_xmlhttpRequest(opt);
      } else {
        var headers = payload ? { 'Content-Type': 'application/json', 'X-Auth-Token': CFG.authToken || '' } : {};
        fetch(url, { method: method, headers: headers, body: payload ? JSON.stringify(payload) : undefined, cache: 'no-store' })
          .then(function (r) { return r.text().then(function (t) { finish(null, { status: r.status, text: t }); }); })
          .catch(function (e) { finish(e); });
      }
    });
  }

  // ---------- 样式 ----------
  var CSS = '#tgshare-css{}' +
    '.tgshare-menu{position:fixed;z-index:999999;min-width:236px;background:#000;border:1px solid rgb(47,51,54);border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.55);padding:6px;font-family:-apple-system,"Segoe UI",system-ui,sans-serif;pointer-events:auto}' +
    '.tgshare-menu button{display:flex;width:100%;align-items:center;gap:9px;background:none;border:0;color:#e7e9ea;padding:9px 10px;border-radius:10px;font-size:14px;cursor:pointer;text-align:left;font-family:inherit}' +
    '.tgshare-menu button:hover{background:rgba(239,243,244,.08)}' +
    '.tgshare-menu .sep{height:1px;background:rgb(47,51,54);margin:5px 8px}' +
    '.tgshare-menu .lbl{color:#8b98a5;font-size:11px;padding:6px 10px 2px}' +
    '.tgshare-fab{position:fixed;right:16px;bottom:96px;z-index:999998;width:40px;height:40px;border-radius:9999px;background:rgba(0,0,0,0.92);border:1px solid rgba(255,255,255,0.45);color:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,0.35);user-select:none;pointer-events:auto}' +
    '.tgshare-fab:hover{background:rgba(22,24,28,0.96);border-color:rgba(255,255,255,0.7)}' +
    '.tgshare-menu{position:fixed;z-index:999999;min-width:236px;background:#000;border:1px solid rgb(47,51,54);border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.55);padding:6px;font-family:-apple-system,"Segoe UI",system-ui,sans-serif;pointer-events:auto}' +
    '.tgshare-card{position:fixed;right:18px;bottom:74px;z-index:999999;width:276px;background:#000;border:1px solid rgb(47,51,54);border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.6);padding:10px;font-family:-apple-system,"Segoe UI",system-ui,sans-serif;pointer-events:auto}' +
    '.tgshare-card .h{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;color:#e7e9ea;padding:4px 8px 8px}' +
    '.tgshare-card .dot{width:9px;height:9px;border-radius:50%;display:inline-block}' +
    '.tgshare-card .row{display:flex;width:100%;align-items:center;gap:9px;background:none;border:0;color:#e7e9ea;padding:9px 10px;border-radius:10px;font-size:14px;cursor:pointer;text-align:left;font-family:inherit}' +
    '.tgshare-card .row:hover{background:rgba(239,243,244,.08)}' +
    '.tgshare-card .foot{color:#8b98a5;font-size:11px;padding:8px 8px 2px}' +
    '.tgshare-toast{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:9999999;background:rgba(0,0,0,.88);color:#fff;padding:8px 16px;border-radius:9999px;font-size:13px;font-family:-apple-system,"Segoe UI",system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.4);transition:opacity .3s;pointer-events:none}';

  function injectCss() {
    if ($('#tgshare-css')) return;
    var st = document.createElement('style');
    st.id = 'tgshare-css';
    st.textContent = CSS;
    document.head.appendChild(st);
  }

  // ---------- 工具 ----------
  function toast(msg, ms) {
    var old = $('#tgshare-toast');
    if (old) old.remove();
    var t = document.createElement('div');
    t.id = 'tgshare-toast';
    t.className = 'tgshare-toast';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { t.style.opacity = '0'; setTimeout(function () { t.remove(); }, 350); }, ms || 2400);
  }

  function copyText(s) {
    var ta = document.createElement('textarea');
    ta.value = s;
    ta.style.cssText = 'position:fixed;top:-999px;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    ta.remove();
  }

  function convert(url) {
    var map = {
      fixupx:    { 'x.com': 'fixupx.com', 'twitter.com': 'fxtwitter.com' },
      fixvx:     { 'x.com': 'fixvx.com', 'twitter.com': 'vxtwitter.com' },
      fxtwitter: { 'x.com': 'fixupx.com', 'twitter.com': 'fxtwitter.com' },
      vxtwitter: { 'x.com': 'fixvx.com', 'twitter.com': 'vxtwitter.com' }
    };
    var m = url.match(/^https?:\/\/(?:www\.)?([^\/]+)\/(.*)$/);
    if (!m) return url;
    var host = m[1].toLowerCase();
    var dom = (map[CFG.service] || map.fixupx)[host];
    if (!dom) return url;
    return 'https://' + dom + '/' + m[2];
  }

  // 推文链接：文章内带 <time> 的 /status/ 链接（时间戳=permalink），去掉 query
  function tweetLink(article) {
    var a = $$('a[href*="/status/"]', article).filter(function (x) { return x.querySelector('time'); })[0];
    if (a) return a.href.split('?')[0];
    return null;
  }

  function currentLink() {
    var m = location.pathname.match(/\/status\/(\d+)/);
    if (m) return location.origin + location.pathname.split('?')[0];
    var a = currentArticle();
    if (a) return tweetLink(a);
    return null;
  }

  function currentArticle() {
    var mid = innerHeight / 2;
    var arts = $$('article[data-testid="tweet"]').filter(function (a) {
      var r = a.getBoundingClientRect();
      return r.top < mid && r.bottom > mid;
    });
    for (var i = 0; i < arts.length; i++) if (tweetLink(arts[i])) return arts[i];
    return null;
  }

  // ---------- 媒体提取（浏览器已登录 X，直接从页面 DOM 取图，不依赖外部服务） ----------
  // 原图：页面里的缩略图 URL 把 name=small 改成 name=orig
  function origUrl(u) {
    if (/[?&]name=/.test(u)) return u.replace(/([?&]name=)\w+/, '$1orig');
    return u;
  }

  // 引用推文（quote）内部有自己的时间戳链接 —— 用它把嵌套推文里的图排除掉
  function nestedIn(node, root) {
    var p = node.parentElement;
    while (p && p !== root) {
      if (p.querySelector('a[href*="/status/"] time')) return true;
      p = p.parentElement;
    }
    return false;
  }

  function mediaOf(article) {
    var out = { photos: [], video: null, poster: null };
    if (!article) return out;
    var link = tweetLink(article) || '';
    var sid = (String(link).match(/\/status\/(\d+)/) || [])[1] || '';
    var seen = {};

    // ① 权威来源：媒体链接自带 /status/<主推文id>/photo/N —— 引用推文（别的 id）自动被排除
    var byIdx = {};
    $$('a[href*="/photo/"]', article).forEach(function (a) {
      var mm = (a.getAttribute('href') || '').match(/\/status\/(\d+)\/photo\/(\d+)/);
      if (!mm) return;
      if (sid && mm[1] !== sid) return;                  // 属于别的推文（引用/转推）→ 跳过
      var img = a.querySelector('img[src*="pbs.twimg.com/"]');
      var src = img && (img.currentSrc || img.getAttribute('src'));
      if (!src) return;
      var key = src.replace(/\?.*$/, '');
      if (seen[key]) return;
      seen[key] = 1;
      byIdx[Number(mm[2])] = origUrl(src);               // 原图交给中继重整（会把 webp 换成 jpg 原图）
    });
    Object.keys(byIdx).sort(function (x, y) { return x - y; }).forEach(function (k) {
      out.photos.push(byIdx[k]);
    });

    // ② 兜底（没有 photo 链接的渲染变体）：扫 pbs 图，靠「嵌套推文自带时间戳链接」排除引用
    var havePhotos = out.photos.length > 0;
    $$('img[src*="pbs.twimg.com/"]', article).forEach(function (img) {
      var src = img.currentSrc || img.getAttribute('src') || '';
      if (!/pbs\.twimg\.com\/(media|amplify_video_thumb|ext_tw_video_thumb|tweet_video_thumb)\//.test(src)) return;
      if (nestedIn(img, article)) return;
      var key = src.replace(/\?.*$/, '');
      if (/\/media\//.test(src)) {
        if (!havePhotos && !seen[key]) { seen[key] = 1; out.photos.push(origUrl(src)); }
      } else if (!out.poster) {
        out.poster = origUrl(src);                       // 视频封面（兜底用）
      }
    });

    // ③ 视频直链（X 多为 blob:，拿不到就让中继走 fxtwitter API）
    $$('video', article).forEach(function (v) {
      if (out.video || nestedIn(v, article)) return;
      var s = v.currentSrc || v.getAttribute('src') || '';
      if (!s) { var sc = v.querySelector('source'); s = (sc && sc.getAttribute('src')) || ''; }
      if (/^https?:\/\/\S+\.mp4/.test(s) || /^https?:\/\/video\.twimg\.com\//.test(s)) out.video = s;
    });

    if (out.photos.length > 10) out.photos = out.photos.slice(0, 10);
    return out;
  }

  // 推文正文（媒体模式当配文用）；引用推文自己的正文要排除
  function tweetTextOf(article) {
    if (!article) return '';
    var els = $$('div[data-testid="tweetText"]', article).filter(function (e) {
      return !nestedIn(e, article);
    });
    return els.length ? (els[0].innerText || '').trim() : '';
  }

  // 分享用的链接：仅链接模式转镜像域；媒体模式保留原版（可选强制官方域）
  function linkForShare(link) {
    if (CFG.shareMode === 'link') return convert(link);
    var m = (link || '').match(/^https?:\/\/(?:www\.)?([^\/]+)\/(.*)$/);
    if (m && CFG.officialDomain) return 'https://' + CFG.officialDomain + '/' + m[2];
    return link;
  }

  // ---------- 配置 ----------
  function loadConfig(cb) {
    httpReq('GET', CFG.relay + '/config.js')
      .then(function (r) {
        var m = (r.text || '').match(/window\.TGShareConfig = (\{[\s\S]*?\});/);
        if (!m) throw new Error('config.js 解析失败');
        var c = JSON.parse(m[1]);
        if (c.targets && c.targets.length) CFG.targets = c.targets;
        if (c.service) CFG.service = c.service;
        if (c.fallback) CFG.fallback = c.fallback;
        if (c.textTemplate) CFG.textTemplate = c.textTemplate;
        if (c.shareMode) CFG.shareMode = c.shareMode;
        if (typeof c.officialDomain === 'string') CFG.officialDomain = c.officialDomain;
        if (c.authToken) CFG.authToken = c.authToken;
        if (c.relay) CFG.relay = c.relay;
        if (cb) cb(true);
      })
      .catch(function () { if (cb) cb(false); });
  }

  // ---------- 发送 ----------
  function buildText(link) {
    return (CFG.textTemplate || '{link}').replace('{link}', link);
  }

  function doFallback(link) {
    var f = CFG.fallback || 'copy';
    var shown = linkForShare(link);
    if (f === 'copy') { copyText(shown); toast('⚠ 中继不可达，已复制链接'); }
    else if (f === 'share') { window.open('https://t.me/share/url?url=' + encodeURIComponent(shown), '_blank'); toast('已打开分享窗口'); }
  }

  // 发送：link=原版链接（服务端按 share_mode 决定发链接还是发图），media/tweet_text=页面里抓到的图与正文
  function sendTo(chat, label, link, media, tweetText) {
    var payload = { chat: chat, link: link };
    if (media) payload.media = media;
    if (CFG.shareMode !== 'link' && tweetText) payload.tweet_text = tweetText;
    // 兼容旧中继：仅链接模式同时带上拼好的文本（新中继会忽略它自行按 share_mode 处理）
    if (CFG.shareMode === 'link') payload.text = buildText(convert(link));
    var modeName = SHARE_LABELS[CFG.shareMode] || CFG.shareMode;
    toast('发送中 → ' + label + (CFG.shareMode === 'link' ? '' : '·' + modeName));
    httpReq('POST', CFG.relay + '/send', payload, 180000)
      .then(function (r) {
        var j = {};
        try { j = JSON.parse(r.text || ''); } catch (e) {}
        if (r.status >= 200 && r.status < 300 && j.ok) {
          var what = j.kind === 'album' ? ('相册 ' + j.count + ' 张') :
                     j.kind === 'photo' ? '图片' : j.kind === 'video' ? '视频' : '链接';
          var note = (j.kind === 'link' && j.media_error && CFG.shareMode !== 'link') ? '（媒体失败，已发链接）' : '';
          toast('✓ 已发送' + what + '到 ' + label + note);
        } else toast('✗ 发送失败：' + (j.error || r.status));
      })
      .catch(function () { doFallback(link); });
  }

  function shareArticle(article) {
    var l = tweetLink(article) || currentLink();
    if (!l) { toast('✗ 未找到推文链接'); return null; }
    if (CFG.shareMode === 'link') return { link: l, media: null, text: '' };
    return { link: l, media: mediaOf(article), text: tweetTextOf(article) };
  }

  // 悬浮面板用：视口中央那条推文的链接 + 媒体
  function currentShare() {
    var l = currentLink();
    if (!l) { toast('✗ 找不到当前推文'); return null; }
    var a = currentArticle();
    if (CFG.shareMode === 'link' || !a) return { link: l, media: null, text: '' };
    return { link: l, media: mediaOf(a), text: tweetTextOf(a) };
  }

  // ---------- 菜单 ----------
  var activeMenu = null;

  function closeMenu() {
    if (activeMenu) { activeMenu.remove(); activeMenu = null; }
    document.removeEventListener('click', closeMenu, true);
    document.removeEventListener('scroll', closeMenu, true);
    document.removeEventListener('keydown', escKey, true);
  }
  function escKey(e) { if (e.key === 'Escape') closeMenu(); }

  function menuItem(label, icon, fn) {
    var b = document.createElement('button');
    b.innerHTML = '<span>' + icon + '</span><span>' + label.replace(/[<>&]/g, '') + '</span>';
    b.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); closeMenu(); fn(); });
    return b;
  }

  function openMenu(anchor, article) {
    closeMenu();
    var menu = document.createElement('div');
    menu.className = 'tgshare-menu';
    var lbl = document.createElement('div');
    lbl.className = 'lbl';
    lbl.textContent = '分享到 Telegram';
    menu.appendChild(lbl);
    CFG.targets.forEach(function (t) {
      menu.appendChild(menuItem(t.label || t.chat, '📮', function () {
        var s = shareArticle(article);
        if (s) sendTo(t.chat, t.label || t.chat, s.link, s.media, s.text);
      }));
    });
    if (CFG.targets.length > 1) {
      menu.appendChild(document.createElement('div')).className = 'sep';
      menu.appendChild(menuItem('发送到全部 (' + CFG.targets.length + ')', '📤', function () {
        var s = shareArticle(article);
        if (!s) return;
        CFG.targets.forEach(function (t, i) {
          setTimeout(function () { sendTo(t.chat, t.label || t.chat, s.link, s.media, s.text); },
                     i * (CFG.shareMode === 'link' ? 900 : 1500));
        });
      }));
    }
    var sep = document.createElement('div'); sep.className = 'sep'; menu.appendChild(sep);
    menu.appendChild(menuItem('复制分享链接', '🔗', function () {
      var l = shareArticle(article);
      if (l) { copyText(linkForShare(l.link)); toast('✓ 已复制 ' + (CFG.shareMode === 'link' ? CFG.service : '原版') + ' 链接'); }
    }));
    menu.appendChild(menuItem('t.me 分享对话框', '🌐', function () {
      var l = shareArticle(article);
      if (l) window.open('https://t.me/share/url?url=' + encodeURIComponent(linkForShare(l.link)), '_blank');
    }));
    menu.appendChild(menuItem('刷新配置', '🔄', function () {
      toast('配置刷新中…');
      loadConfig(function (ok) { toast(ok ? '✓ 配置已更新（' + CFG.targets.length + ' 个目标）' : '✗ 中继不可达'); });
    }));
    document.body.appendChild(menu);
    activeMenu = menu;
    var r = anchor.getBoundingClientRect();
    var w = menu.offsetWidth || 240;
    var left = Math.max(8, Math.min(r.right - w, innerWidth - w - 8));
    var top = r.bottom + 6;
    if (top + menu.offsetHeight + 8 > innerHeight) top = Math.max(8, r.top - menu.offsetHeight - 6);
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
    setTimeout(function () {
      document.addEventListener('click', closeMenu, true);
      document.addEventListener('scroll', closeMenu, true);
      document.addEventListener('keydown', escKey, true);
    }, 0);
  }

  // ---------- 推文内按钮 ----------
  var TWEET_SEL = 'article[data-testid="tweet"]';
  var DIALOG_SEL = '[role="dialog"],[data-testid="photo-viewer"]';

  function hasDialog() {
    var ds = $$(DIALOG_SEL);
    for (var i = 0; i < ds.length; i++) {
      var r = ds[i].getBoundingClientRect();
      // 仅当弹窗真实可见且「够大」时才视为打开（大图/视频查看器等全屏模态框）。
      // 曾经只判 width>0：X 上任何常驻可见的小 dialog 都会让悬浮按钮被永久 display:none。
      if (r.width > 0 && r.height > 0 &&
          r.width >= Math.min(600, innerWidth * 0.5) && r.height >= innerHeight * 0.5) {
        hasDialog.last = ds[i];
        return true;
      }
    }
    return false;
  }

  // 弹窗隐藏/显示由 buildPanel 赋值实现（供 init 的观察器调用）
  var fabEl = null;
  var cardEl = null;
  var checkModal = function () {};

  function processArticles() {
    // 克隆原生动作项（参考 twitter-media-downloader 思路）：尺寸/间距/悬停全部原生
    $$(TWEET_SEL).forEach(function (article) {
      try {
        if (article.querySelector('[data-tgshare]')) return;
        // 必须是「真推文」：有状态永久链接（带时间戳）或推文正文 testid。
        // 否则 X 的「推荐关注」等用户卡片容器也会被注入一个裸飞机图标 —— 错位来源之一。
        if (!$('a[href*="/status/"] time', article) && !$('div[data-testid="tweetText"]', article)) return;
        var groups = $$('div[role="group"]', article);
        // 只认真正的操作栏（含 回复/转推/点赞/收藏 任一）；找不到就不注入——宁缺，不错位
        var group = groups.filter(function (g) {
          return $('[data-testid="reply"],[data-testid="retweet"],[data-testid="like"],[data-testid="bookmark"]', g);
        })[0];
        if (!group) return;
        // 取最后一个含 role=button 的可见动作 wrapper（分享/收藏等，随 X 版本自适应）
        var share = null;
        var kids = Array.prototype.slice.call(group.children);
        for (var i = kids.length - 1; i >= 0; i--) {
          var c = kids[i];
          if (c.nodeType === 1 && c.querySelector('[role="button"]') && c.getBoundingClientRect().width > 0) { share = c; break; }
        }
        if (!share) return;
        var btn = share.cloneNode(true);
        btn.setAttribute('data-tgshare', '1');
        btn.setAttribute('aria-label', 'TGShare 分享');
        var rb = btn.querySelector('[role="button"]');
        if (rb) rb.setAttribute('aria-label', 'TGShare 分享');
        // 仅替换 svg 内部路径：保留克隆的尺寸/描边/颜色，实现原生观感
        var svg = btn.querySelector('svg');
        if (svg) svg.innerHTML = '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>';
        ['click', 'mousedown', 'pointerdown'].forEach(function (ev) {
          btn.addEventListener(ev, function (e) { e.preventDefault(); e.stopPropagation(); });
        });
        btn.addEventListener('click', function () { openMenu(btn, article); });
        group.insertBefore(btn, share.nextSibling);
      } catch (e) {}
    });
  }

  // ---------- 悬浮面板 ----------
  var panelOpen = false;

  function buildPanel() {
    var fab = document.createElement('div');
    fab.className = 'tgshare-fab';
    fab.innerHTML = ICON;
    fab.title = 'TGShare';
    fab.style.visibility = 'hidden';   // 首次对齐前不显示，避免小图标闪烁
    fabEl = fab;
    fab.addEventListener('click', function (e) {
      e.stopPropagation();
      if (fab.dataset.dragged === '1') return;   // 刚拖动过：不当作点击
      togglePanel();
    });
    // 拖动微调 + localStorage 记忆：启发式万一还是不合意，用户拖一下就永久生效（面板里可重置）
    var drag = null;
    fab.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      drag = { x: e.clientX, y: e.clientY,
               right: parseFloat(fab.style.right) || 16, bottom: parseFloat(fab.style.bottom) || 96,
               moved: false };
      try { fab.setPointerCapture(e.pointerId); } catch (e2) {}
    });
    fab.addEventListener('pointermove', function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moved && (Math.abs(dx) + Math.abs(dy)) < 5) return;   // 5px 死区，避免误拖
      drag.moved = true;
      fab.style.right = Math.max(0, Math.min(innerWidth - 40, drag.right - dx)) + 'px';
      fab.style.bottom = Math.max(0, Math.min(innerHeight - 40, drag.bottom - dy)) + 'px';
      e.preventDefault();
    });
    function endDrag() {
      if (!drag) return;
      var moved = drag.moved;
      drag = null;
      if (!moved) return;
      savePos(parseFloat(fab.style.right), parseFloat(fab.style.bottom));
      fab.dataset.dragged = '1';
      setTimeout(function () { fab.dataset.dragged = ''; }, 400);
      toast('✓ 位置已记住（面板里可「重置悬浮按钮位置」）');
    }
    fab.addEventListener('pointerup', endDrag);
    fab.addEventListener('pointercancel', endDrag);
    document.body.appendChild(fab);

    // 定位：注入 X 原生悬浮按钮容器，让 X 的布局引擎接管间距/对齐；样式实时克隆原生按钮
    // 悬浮判定：自身或任一祖先为 fixed/sticky。X 的悬浮按钮自身常是 static，
    // 真正的悬浮来自外层容器——只看自身 position:fixed 会漏掉它（结果悬浮按钮退到兜底位、看着像没对齐）。
    function isFloating(el) {
      var p = el;
      while (p && p !== document.body && p !== document.documentElement) {
        var ps;
        try { ps = getComputedStyle(p).position; } catch (e) { break; }
        if (ps === 'fixed' || ps === 'sticky') return true;
        p = p.parentElement;
      }
      return false;
    }
    function isControl(el) {
      if (!el || el.nodeType !== 1) return false;
      if (!(el.matches('button,[role="button"],a[href],[tabindex]') || el.querySelector('svg, img'))) return false;
      return isFloating(el);   // 必须真的悬浮（自身或祖先 fixed/sticky），排除正文里的按钮
    }
    // 右下角「看得见的悬浮控件」——用命中测试（elementsFromPoint）取，天然排除透明空壳/被遮挡的东西。
    // 教训：X 的 DOM 里有大量透明占位容器（如 400×55 的 GrokDrawer，DOM 在、视觉不在），
    // 拿它们当锚点会把悬浮按钮放到看不见的容器上方，与用户看得见的按钮隔开一大截 = 错位。
    function hitControl(x, y) {
      var els = document.elementsFromPoint(x, y) || [];
      for (var j = 0; j < els.length; j++) {
        var e = els[j];
        if (e.closest && e.closest('.tgshare-fab,.tgshare-card,[data-tgshare]')) continue;   // 别认自己
        if (!isControl(e)) continue;
        var r = e.getBoundingClientRect();
        if (r.width < 20 || r.height < 20 || r.width > 120 || r.height > 120) continue;
        if (r.left <= innerWidth * 0.6 || r.top <= innerHeight * 0.45) continue;
        return { el: e, r: r };
      }
      return null;
    }
    // 右下角「看得见的悬浮控件」——用命中测试（elementsFromPoint）在右下角区块里扫描取，
    // 天然排除透明空壳/被遮挡的东西。
    // 教训：X 的 DOM 里有大量透明占位容器（如 400×55 的 GrokDrawer，DOM 在、视觉不在），拿它们当锚点会把
    // 悬浮按钮放到看不见的容器上方，与用户看得见的按钮隔开一大截 = 错位；
    // 另外**不要写死采样位置**——X 的悬浮列在「距右边约 35px」处，写 W-20/W-34 会正好擦着它的右边缘过去，一个都采不到。
    var stackCache = null, stackCacheAt = 0;
    function visibleStack() {
      var now = Date.now();
      if (stackCache && now - stackCacheAt < 900) return stackCache;   // 节流：滚动时最多 ~1 次/秒
      var hits = [], seen = [];
      var yStop = Math.max(innerHeight - 280, innerHeight * 0.45);
      for (var y = innerHeight - 6; y > yStop; y -= 12) {
        for (var x = innerWidth - 6; x > innerWidth - 140 && x > innerWidth * 0.6; x -= 8) {
          var h = hitControl(x, y);
          if (!h || seen.indexOf(h.el) >= 0) continue;
          seen.push(h.el);
          hits.push(h);
        }
      }
      hits.sort(function (a, b) { return a.r.top - b.r.top; });   // 最靠上的排前面（悬浮列顶部）
      stackCache = hits;
      stackCacheAt = now;
      return hits;
    }
    function cloneBtnStyle(ref) {
      try {
        var rr = ref.getBoundingClientRect();
        // 参照物若是「宽容器」（如 Grok 抽屉 400×55）：只当锚点，不抄它的尺寸/底色
        if (rr.width > 160 || rr.height > 160) return;
        var cs = getComputedStyle(ref);
        var bg = cs.getPropertyValue('background-color');
        var transparent = !bg || bg === 'transparent' || /rgba\(0,\s*0,\s*0,\s*0\)/.test(bg);
        // 参照物若是「透明裸图标」（X 的静态按钮），别把透明背景/无边框抄过来——
        // 否则悬浮按钮会变成没有底衬的裸图标，看着就像错位
        var props = transparent
          ? ['border-radius', 'width', 'height', 'color', 'box-sizing']
          : ['background-color', 'border', 'border-radius', 'box-shadow', 'width', 'height', 'color', 'box-sizing'];
        props.forEach(function (p) {
          var v = cs.getPropertyValue(p);
          if (v && v !== 'none') fab.style[p] = v;
        });
        // 图标：克隆原生按钮内部图标的真实尺寸（X 用 SVG，不跟 font-size）
        var refIcon = ref.querySelector('svg, img');
        var ico = fab.querySelector('svg');
        if (ico && refIcon) {
          var rs = getComputedStyle(refIcon);
          var iw = rs.getPropertyValue('width');
          var ih = rs.getPropertyValue('height');
          if (iw && parseFloat(iw) > 0) ico.style.width = iw;
          if (ih && parseFloat(ih) > 0) ico.style.height = ih;
        }
      } catch (e) {}
    }
    var lastGoodPos = null;   // 最近一次成功对齐的位置
    var lastRefEl = null;     // 上一次的对齐参照（仅用于换参照时打一条日志）
    function posSane(p) {     // 旧位置只有在「右下角区域」内才允许复用，避免页面中间的错位卡死
      if (!p) return false;
      var b = parseFloat(p.bottom), r = parseFloat(p.right);
      return b >= 0 && b <= 400 && r >= 0 && r <= 240;
    }
    // 用户手动拖过的位置优先（localStorage 记忆）——启发式万一还是不合意，拖一下即可，彻底摆脱 DOM 猜测
    function savedPos() {
      try {
        var j = JSON.parse(localStorage.getItem('tgshare.fabPos') || 'null');
        return (j && typeof j.right === 'number' && typeof j.bottom === 'number') ? j : null;
      } catch (e) { return null; }
    }
    function savePos(right, bottom) {
      try { localStorage.setItem('tgshare.fabPos', JSON.stringify({ right: right, bottom: bottom })); } catch (e) {}
    }
    function clearSavedPos() { try { localStorage.removeItem('tgshare.fabPos'); } catch (e) {} }

    function placeFab(force) {
      var sp = savedPos();
      if (sp && !force) {                       // 用户定过位置：不动
        fab.style.right = sp.right + 'px';
        fab.style.bottom = sp.bottom + 'px';
        if (fab.style.visibility === 'hidden') fab.style.visibility = 'visible';
        return;
      }
      var hits = visibleStack();
      if (hits.length) {
        var anchor = hits[0], r = anchor.r;     // 悬浮列最靠上的可见控件 → 站在它上方
        var rightEdge = Math.max.apply(null, hits.map(function (h) { return h.r.right; }));   // 列的右边缘
        var gap = 12;
        if (hits.length > 1) { var g = hits[1].r.top - hits[0].r.bottom; if (g >= 4 && g <= 40) gap = g; }
        if (anchor.el !== lastRefEl) {
          lastRefEl = anchor.el;
          try {
            console.log('[TGShare] 对齐参照(可见控件): ' +
              (anchor.el.getAttribute('aria-label') || anchor.el.getAttribute('data-testid') || anchor.el.tagName) +
              ' ' + JSON.stringify({ l: Math.round(r.left), t: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }) +
              ' 同列可见项=' + hits.length);
          } catch (e1) {}
        }
        if (r.width <= 160 && r.height <= 160) cloneBtnStyle(anchor.el);   // 只从按钮大小的可见控件抄样式
        fab.style.bottom = Math.max(14, innerHeight - r.top + gap) + 'px';
        fab.style.right = Math.max(14, innerWidth - rightEdge) + 'px';
        // 收敛校验：右边缘对齐 + 底边 = 参照顶边 - 间距
        for (var k = 0; k < 3; k++) {
          var fr = fab.getBoundingClientRect();
          var dx = rightEdge - fr.right;
          var dy = (r.top - gap) - fr.bottom;
          if (Math.abs(dx) <= 0.5 && Math.abs(dy) <= 0.5) break;
          fab.style.right = (parseFloat(fab.style.right) - dx) + 'px';
          fab.style.bottom = (parseFloat(fab.style.bottom) - dy) + 'px';
        }
        fab.style.visibility = 'visible';
        lastGoodPos = { bottom: fab.style.bottom, right: fab.style.right };
        try {
          console.log('[TGShare] 可见悬浮列 ' + hits.length + ' 项 [' + hits.map(function (h) {
            return (h.el.getAttribute('aria-label') || h.el.getAttribute('data-testid') || h.el.tagName) + '@' + Math.round(h.r.top);
          }).join(' ') + '] gap=' + gap + ' → bottom=' + fab.style.bottom + ' right=' + fab.style.right);
        } catch (e5) {}
        return;
      }
      // 右下角一个可见悬浮控件都没有：兜底槽位（保持可见，绝不再隐身）
      if (posSane(lastGoodPos)) { fab.style.bottom = lastGoodPos.bottom; fab.style.right = lastGoodPos.right; }
      else { fab.style.bottom = '96px'; fab.style.right = '16px'; }
      if (fab.style.visibility === 'hidden') {
        fab.style.visibility = 'visible';
        try { console.log('[TGShare] 右下角没有可见悬浮控件，按兜底位置显示悬浮按钮'); } catch (e2) {}
      }
    }
    // 弹窗（大图查看器等）打开时隐藏悬浮按钮，关闭后恢复
    var lastDlg = null;
    checkModal = function () {
      var dlg = hasDialog();
      if (dlg && fabEl.style.display !== 'none') {
        try { console.log('[TGShare] 检测到弹窗/大图查看器，隐藏悬浮按钮'); } catch (e2) {}
      }
      fabEl.style.display = dlg ? 'none' : '';
      if (dlg && panelOpen && cardEl) { cardEl.style.display = 'none'; panelOpen = false; }
      if (!dlg && lastDlg) placeFab();   // 仅在弹窗关闭瞬间重定位
      lastDlg = dlg;
    };
    // 手动转储：页面控制台执行 document.documentElement.setAttribute('data-tgshare-dump','1') 触发
    function dumpState() {
      var hits = visibleStack();
      console.log('[TGShare-DUMP] 右下角可见悬浮控件 ' + hits.length + ' 项: ' + hits.map(function (h) {
        return (h.el.getAttribute('aria-label') || h.el.getAttribute('data-testid') || h.el.tagName) +
          ' L' + Math.round(h.r.left) + ' T' + Math.round(h.r.top) + ' ' + Math.round(h.r.width) + 'x' + Math.round(h.r.height);
      }).join(' | '));
      console.log('[TGShare-DUMP] fab pos: bottom=' + fabEl.style.bottom + ' right=' + fabEl.style.right + ' rect=' + JSON.stringify({ l: Math.round(fabEl.getBoundingClientRect().left), t: Math.round(fabEl.getBoundingClientRect().top), w: Math.round(fabEl.getBoundingClientRect().width), h: Math.round(fabEl.getBoundingClientRect().height) }) + ' 已记忆位置=' + JSON.stringify(savedPos()));
    }
    document.documentElement.addEventListener('click', function (e) {
      if (e.target === document.documentElement && document.documentElement.getAttribute('data-tgshare-dump') === '1') {
        document.documentElement.removeAttribute('data-tgshare-dump');
        dumpState();
      }
    }, true);
    window.addEventListener('load', function () { setTimeout(function () { try { dumpState(); } catch (e) {} }, 1500); });
    checkModal();
    placeFab();
    // 自愈：每 2 秒静默比对，仅当偏差 >1.5px 时重排（防加载期/滚动条/缩放导致的漂移）
    setInterval(function () {
      if (hasDialog() || fabEl.style.display === 'none') return;
      if (savedPos()) return;                                            // 用户定过位置：不自作主张
      if (fabEl.style.visibility === 'hidden') { placeFab(); return; }   // 兜底：绝不长期隐身
      var hits = visibleStack();
      if (!hits.length) return;
      var r = hits[0].r, fr = fabEl.getBoundingClientRect();
      var rightEdge = Math.max.apply(null, hits.map(function (h) { return h.r.right; }));
      var gap = 12;
      if (hits.length > 1) { var g = hits[1].r.top - hits[0].r.bottom; if (g >= 4 && g <= 40) gap = g; }
      if (Math.abs(rightEdge - fr.right) > 1.5 || Math.abs((r.top - gap) - fr.bottom) > 1.5) placeFab();
    }, 2000);
    // X 悬浮按钮可能晚于脚本挂载：延迟重试几次，确保站到正确槽位
    [800, 2000, 4000].forEach(function (ms) { setTimeout(function () { if (!hasDialog()) placeFab(); }, ms); });
    var pf = null;
    document.addEventListener('scroll', function () { clearTimeout(pf); pf = setTimeout(function () { placeFab(); }, 150); }, { passive: true, capture: true });

    var card = document.createElement('div');
    card.className = 'tgshare-card';
    cardEl = card;
    card.style.display = 'none';

    function statusLine() {
      var h = document.createElement('div');
      h.className = 'h';
      h.innerHTML = '<span class="dot" style="background:#8b98a5"></span><span>TGShare · 连接中…</span>';
      return h;
    }
    function render() {
      card.innerHTML = '';
      var h = statusLine();
      card.appendChild(h);
      // 右上角关闭按钮
      var closeBtn = document.createElement('button');
      closeBtn.textContent = '×';
      closeBtn.setAttribute('aria-label', '关闭');
      closeBtn.style.cssText = 'position:absolute;top:6px;right:8px;background:none;border:0;color:#8b98a5;font-size:18px;cursor:pointer;line-height:1;padding:4px;font-family:inherit';
      closeBtn.addEventListener('click', function (e) { e.stopPropagation(); closePanel(); });
      card.appendChild(closeBtn);
      httpReq('GET', CFG.relay + '/status')
        .then(function (r) {
          var s = {};
          try { s = JSON.parse(r.text || ''); } catch (e) {}
          var online = !!(s && s.ok);
          if (online && s.share_mode) CFG.shareMode = s.share_mode;
          var modeTxt = online ? (SHARE_LABELS[CFG.shareMode] || CFG.shareMode) : '';
          h.innerHTML = '<span class="dot" style="background:' + (online ? '#00ba7c' : '#f4212e') + '"></span>' +
            '<span>TGShare · ' + (online ? (s.authed === false ? '未登录' : (s.mode === 'bot' ? 'Bot 模式' : '在线')) : '离线') +
            (modeTxt ? ' · ' + modeTxt : '') + '</span>';
        })
        .catch(function () { h.innerHTML = '<span class="dot" style="background:#f4212e"></span><span>TGShare · 离线</span>'; });
      if (!CFG.targets.length) {
        var e = document.createElement('div');
        e.className = 'foot';
        e.textContent = '还没有目标，去 config.json 添加或点 /pick';
        card.appendChild(e);
      }
      CFG.targets.forEach(function (t) {
        var label = (t.label || t.chat) + (t.share_mode ? ' [' + (SHARE_LABELS[t.share_mode] || t.share_mode) + ']' : '');
        card.appendChild(menuItem(label, '📮', function () {
          var s = currentShare();
          if (s) sendTo(t.chat, t.label || t.chat, s.link, s.media, s.text);
        }));
      });
      if (CFG.targets.length > 1) {
        card.appendChild(menuItem('发送到全部 (' + CFG.targets.length + ')', '📤', function () {
          var s = currentShare();
          if (!s) return;
          CFG.targets.forEach(function (t, i) {
            setTimeout(function () { sendTo(t.chat, t.label || t.chat, s.link, s.media, s.text); },
                       i * (CFG.shareMode === 'link' ? 900 : 1500));
          });
        }));
      }
      var sep = document.createElement('div'); sep.className = 'sep'; card.appendChild(sep);
      // 分享形式切换（持久化到 config.json；媒体模式=发图/相册，配文用原版链接）
      card.appendChild(menuItem('分享形式：' + (SHARE_LABELS[CFG.shareMode] || CFG.shareMode), '🖼', function () {
        var next = SHARE_MODES[(SHARE_MODES.indexOf(CFG.shareMode) + 1) % SHARE_MODES.length];
        httpReq('POST', CFG.relay + '/config', { share_mode: next })
          .then(function (r) {
            var j = {};
            try { j = JSON.parse(r.text || ''); } catch (e) {}
            if (r.status >= 200 && r.status < 300 && j.ok) {
              CFG.shareMode = j.share_mode;
              toast('✓ 分享形式：' + (SHARE_LABELS[j.share_mode] || j.share_mode));
              render();
            } else toast('✗ 切换失败：' + (j.error || r.status));
          })
          .catch(function () { toast('✗ 中继不可达'); });
      }));
      // 链接域名切换（持久化到 config.json；仅链接模式生效）
      (function () {
        var names = ['fixupx', 'fixvx', 'fxtwitter', 'vxtwitter'];
        card.appendChild(menuItem('链接域名：' + CFG.service, '🌐', function () {
          var next = names[(names.indexOf(CFG.service) + 1) % names.length];
          httpReq('POST', CFG.relay + '/config', { service: next })
            .then(function (r) {
              var j = {};
              try { j = JSON.parse(r.text || ''); } catch (e) {}
              if (r.status >= 200 && r.status < 300 && j.ok) {
                CFG.service = j.service;
                toast('✓ 链接域名已切换：' + j.service);
                render();
              } else toast('✗ 切换失败：' + (j.error || r.status));
            })
            .catch(function () { toast('✗ 中继不可达'); });
        }));
      })();
      card.appendChild(menuItem('复制分享链接', '🔗', function () {
        var l = currentLink();
        if (l) { copyText(linkForShare(l)); toast('✓ 已复制 ' + (CFG.shareMode === 'link' ? CFG.service : '原版') + ' 链接'); }
        else toast('✗ 找不到当前推文');
      }));
      card.appendChild(menuItem('t.me 分享对话框', '🌐', function () {
        var l = currentLink();
        if (l) window.open('https://t.me/share/url?url=' + encodeURIComponent(linkForShare(l)), '_blank');
      }));
      card.appendChild(menuItem('刷新配置', '🔄', function () {
        toast('配置刷新中…');
        loadConfig(function (ok) {
          toast(ok ? '✓ 配置已更新（' + CFG.targets.length + ' 个目标 · ' + (SHARE_LABELS[CFG.shareMode] || CFG.shareMode) + '）' : '✗ 中继不可达');
          render();
        });
      }));
      card.appendChild(menuItem('重置悬浮按钮位置', '🎯', function () {
        clearSavedPos();
        lastGoodPos = null; lastRefEl = null; stackCache = null;
        placeFab(true);
        toast('✓ 已恢复自动对齐');
      }));
      var foot = document.createElement('div');
      foot.className = 'foot';
      foot.textContent = CFG.relay + ' · 修改 config.json 后可刷新';
      card.appendChild(foot);
    }
    function closePanel() {
      panelOpen = false;
      card.style.display = 'none';
    }
    function togglePanel() {
      panelOpen = !panelOpen;
      card.style.display = panelOpen ? 'block' : 'none';
      if (panelOpen) render();
    }
    // 点面板外部 / Esc 关闭
    document.addEventListener('click', function (e) {
      if (!panelOpen) return;
      if (card.contains(e.target) || fab.contains(e.target)) return;
      closePanel();
    }, true);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && panelOpen) closePanel();
    }, true);
    render();
    document.body.appendChild(card);
  }

  // ---------- 初始化 ----------
  function init() {
    injectCss();
    if (!document.body) { setTimeout(init, 300); return; }
    processArticles();
    buildPanel();
    loadConfig();
    // 优化：仅在新增节点里确实出现推文时才重新扫描，避免全量遍历拖慢页面
    var t = null;
    new MutationObserver(function (muts) {
      var need = false;
      for (var i = 0; i < muts.length; i++) {
        var m = muts[i];
        if (!m.addedNodes || !m.addedNodes.length) continue;
        for (var j = 0; j < m.addedNodes.length; j++) {
          var n = m.addedNodes[j];
          if (n.nodeType !== 1) continue;
          if (n.matches && n.matches(DIALOG_SEL)) { checkModal(); need = false; }
          else if (n.querySelector && (n.querySelector(DIALOG_SEL) || n.querySelector(TWEET_SEL))) need = true;
        }
      }
      // 弹窗关闭（节点被移除）后重新扫描，给期间重渲染的推文补注入按钮
      for (var i2 = 0; i2 < muts.length; i2++) {
        var m2 = muts[i2];
        if (!m2.removedNodes || !m2.removedNodes.length) continue;
        for (var j2 = 0; j2 < m2.removedNodes.length; j2++) {
          var n2 = m2.removedNodes[j2];
          if (n2.nodeType !== 1) continue;
          if ((n2.matches && n2.matches(DIALOG_SEL)) || (n2.querySelector && n2.querySelector(DIALOG_SEL))) need = true;
        }
      }
      checkModal();
      if (need) { clearTimeout(t); t = setTimeout(processArticles, 200); }
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
