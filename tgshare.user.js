// ==UserScript==
// @name         TGShare – X 一键分享到 Telegram
// @namespace    local.tgshare
// @version      1.0.15
// @description  推文操作栏新增分享按钮，一键把 fixupx/fixvx 链接发送到指定 Telegram 聊天（本机 tgshare 中继）
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
    relay: 'http://127.0.0.1:8787',
    service: 'fixupx',        // fixupx | fixvx | fxtwitter | vxtwitter
    fallback: 'copy',         // 中继不可用时: copy=复制链接 share=打开 t.me 分享 none=不处理
    textTemplate: '{link}',
    targets: [{ label: '我的收藏', chat: 'me' }],
    authToken: ''
  };
  var CFG = { relay: EMBED.relay, service: EMBED.service, fallback: EMBED.fallback, textTemplate: EMBED.textTemplate, targets: EMBED.targets.slice(), authToken: EMBED.authToken };

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
    var mid = innerHeight / 2;
    var arts = $$('article[data-testid="tweet"]').filter(function (a) {
      var r = a.getBoundingClientRect();
      return r.top < mid && r.bottom > mid;
    });
    for (var i = 0; i < arts.length; i++) {
      var l = tweetLink(arts[i]);
      if (l) return l;
    }
    return null;
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
    if (f === 'copy') { copyText(link); toast('⚠ 中继不可达，已复制链接'); }
    else if (f === 'share') { window.open('https://t.me/share/url?url=' + encodeURIComponent(link), '_blank'); toast('已打开分享窗口'); }
  }

  function sendTo(chat, label, link) {
    link = convert(link);  // x.com/twitter.com → fixupx/fixvx 等
    var text = buildText(link);
    toast('发送中 → ' + label);
    httpReq('POST', CFG.relay + '/send', { chat: chat, text: text }, 8000)
      .then(function (r) {
        var j = {};
        try { j = JSON.parse(r.text || ''); } catch (e) {}
        if (r.status >= 200 && r.status < 300 && j.ok) toast('✓ 已发送到 ' + label);
        else toast('✗ 发送失败：' + (j.error || r.status));
      })
      .catch(function () { doFallback(link); });
  }

  function shareArticle(article) {
    var l = tweetLink(article) || currentLink();
    if (!l) { toast('✗ 未找到推文链接'); return null; }
    return l;
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
        var l = shareArticle(article);
        if (l) sendTo(t.chat, t.label || t.chat, l);
      }));
    });
    if (CFG.targets.length > 1) {
      menu.appendChild(document.createElement('div')).className = 'sep';
      menu.appendChild(menuItem('发送到全部 (' + CFG.targets.length + ')', '📤', function () {
        var l = shareArticle(article);
        if (!l) return;
        CFG.targets.forEach(function (t, i) {
          setTimeout(function () { sendTo(t.chat, t.label || t.chat, l); }, i * 900);
        });
      }));
    }
    var sep = document.createElement('div'); sep.className = 'sep'; menu.appendChild(sep);
    menu.appendChild(menuItem('复制转换后链接', '🔗', function () {
      var l = shareArticle(article);
      if (l) { copyText(convert(l)); toast('✓ 已复制 ' + CFG.service + ' 链接'); }
    }));
    menu.appendChild(menuItem('t.me 分享对话框', '🌐', function () {
      var l = shareArticle(article);
      if (l) window.open('https://t.me/share/url?url=' + encodeURIComponent(convert(l)), '_blank');
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
    var d = document.querySelector(DIALOG_SEL);
    // 仅当弹窗真实可见（有尺寸）时才视为打开，避免隐藏的常驻 dialog 误隐藏按钮
    return !!(d && d.getBoundingClientRect().width > 0);
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
        var groups = $$('div[role="group"]', article);
        var group = groups.filter(function (g) {
          return $('[data-testid="reply"],[data-testid="retweet"],[data-testid="like"],[data-testid="bookmark"]', g);
        })[0] || groups[groups.length - 1];
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
    fab.addEventListener('click', function (e) { e.stopPropagation(); togglePanel(); });
    document.body.appendChild(fab);

    // 定位：注入 X 原生悬浮按钮容器，让 X 的布局引擎接管间距/对齐；样式实时克隆原生按钮
    function findNativeBtns() {
      var out = [];
      var cands = document.querySelectorAll('[data-testid="BackToTopButton"],[aria-label="回到顶部"],[aria-label="Back to top"],[aria-label="Grok"],[data-testid="Grok"]');
      for (var i = 0; i < cands.length; i++) {
        var r = cands[i].getBoundingClientRect();
        // 只认右下角固定悬浮区（避免匹配到推文内的分享按钮）
        if (r.width > 0 && r.left > innerWidth * 0.6 && r.top > innerHeight * 0.5) out.push({ el: cands[i], r: r });
      }
      out.sort(function (a, b) { return a.r.top - b.r.top; });
      return out;
    }
    function cloneBtnStyle(ref) {
      try {
        var cs = getComputedStyle(ref);
        ['background-color', 'border', 'border-radius', 'box-shadow', 'width', 'height', 'color', 'box-sizing'].forEach(function (p) {
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
    var lastGoodPos = null;   // 最近一次成功对齐的位置，避免原生按钮短暂消失时跳位
    function placeFab() {
      var btns = findNativeBtns();
      if (!btns.length) {
        if (lastGoodPos) { fab.style.bottom = lastGoodPos.bottom; fab.style.right = lastGoodPos.right; }
        else { fab.style.bottom = '96px'; fab.style.right = '16px'; }
        return;
      }
      var ref = btns[0].el, r = btns[0].r;
      cloneBtnStyle(ref);
      var gap = 12;
      if (btns.length > 1) {
        var g = btns[1].r.top - btns[0].r.bottom;
        if (g > 0 && g < 80) gap = g;
      }
      var w = fab.offsetWidth || r.width || 40;
      fab.style.bottom = Math.max(14, innerHeight - r.top + gap) + 'px';
      fab.style.right = Math.max(14, innerWidth - (r.left + r.width / 2 + w / 2)) + 'px';
      // 收敛校验（比较底边与中心，方向正确）：漂移时自愈，不漂移则零开销跳过
      for (var k = 0; k < 3; k++) {
        var fr = fab.getBoundingClientRect();
        var dx = (r.left + r.width / 2) - (fr.left + fr.width / 2);
        var dy = (r.top - gap) - fr.bottom;   // 目标：底边 = 原生顶边 - 间距
        if (Math.abs(dx) <= 0.5 && Math.abs(dy) <= 0.5) break;
        fab.style.right = (parseFloat(fab.style.right) - dx) + 'px';
        fab.style.bottom = (parseFloat(fab.style.bottom) - dy) + 'px';
      }
      fab.style.visibility = 'visible';
      lastGoodPos = { bottom: fab.style.bottom, right: fab.style.right };
      try {
        console.log('[TGShare] btns=' + btns.length + ' [' + btns.map(function (b) { return (b.el.getAttribute('aria-label') || b.el.getAttribute('data-testid') || '?') + '@' + Math.round(b.r.top); }).join(' ') + '] gap=' + gap + ' posBottom=' + fab.style.bottom + ' posRight=' + fab.style.right + ' size=' + Math.round(fab.offsetWidth) + 'x' + Math.round(fab.offsetHeight));
      } catch (e) {}
    }
    // 弹窗（大图查看器等）打开时隐藏悬浮按钮，关闭后恢复
    var lastDlg = null;
    checkModal = function () {
      var dlg = hasDialog();
      fabEl.style.display = dlg ? 'none' : '';
      if (dlg && panelOpen && cardEl) { cardEl.style.display = 'none'; panelOpen = false; }
      if (!dlg && lastDlg) placeFab();   // 仅在弹窗关闭瞬间重定位
      lastDlg = dlg;
    };
    // 手动转储：页面控制台执行 document.documentElement.setAttribute('data-tgshare-dump','1') 触发
    function dumpState() {
      var out = [];
      var cands = document.querySelectorAll('[data-testid="BackToTopButton"],[aria-label="回到顶部"],[aria-label="Back to top"],[aria-label="Grok"],[data-testid="Grok"],[role="button"]');
      for (var i = 0; i < cands.length; i++) {
        var r = cands[i].getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && r.right > innerWidth * 0.5 && r.top > innerHeight * 0.4) {
          out.push((cands[i].getAttribute('aria-label') || cands[i].getAttribute('data-testid') || cands[i].tagName) + ' L' + Math.round(r.left) + ' T' + Math.round(r.top) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
        }
      }
      console.log('[TGShare-DUMP] ' + out.join(' | '));
      console.log('[TGShare-DUMP] fab pos: bottom=' + fabEl.style.bottom + ' right=' + fabEl.style.right + ' rect=' + JSON.stringify({ l: Math.round(fabEl.getBoundingClientRect().left), t: Math.round(fabEl.getBoundingClientRect().top), w: Math.round(fabEl.getBoundingClientRect().width), h: Math.round(fabEl.getBoundingClientRect().height) }));
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
      if (hasDialog() || fabEl.style.display === 'none' || fabEl.style.visibility === 'hidden') return;
      var btns = findNativeBtns();
      if (!btns.length) return;
      var r = btns[0].r;
      var fr = fabEl.getBoundingClientRect();
      var gap = 12;
      if (btns.length > 1) {
        var g = btns[1].r.top - btns[0].r.bottom;
        if (g > 0 && g < 80) gap = g;
      }
      var dx = (r.left + r.width / 2) - (fr.left + fr.width / 2);
      var dy = (r.top - gap) - fr.bottom;
      if (Math.abs(dx) > 1.5 || Math.abs(dy) > 1.5) placeFab();
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
          h.innerHTML = '<span class="dot" style="background:' + (online ? '#00ba7c' : '#f4212e') + '"></span>' +
            '<span>TGShare · ' + (online ? (s.authed === false ? '未登录' : (s.mode === 'bot' ? 'Bot 模式' : '在线')) : '离线') + '</span>';
        })
        .catch(function () { h.innerHTML = '<span class="dot" style="background:#f4212e"></span><span>TGShare · 离线</span>'; });
      if (!CFG.targets.length) {
        var e = document.createElement('div');
        e.className = 'foot';
        e.textContent = '还没有目标，去 config.json 添加或点 /pick';
        card.appendChild(e);
      }
      CFG.targets.forEach(function (t) {
        card.appendChild(menuItem(t.label || t.chat, '📮', function () {
          var l = currentLink();
          if (l) sendTo(t.chat, t.label || t.chat, l);
          else toast('✗ 找不到当前推文');
        }));
      });
      if (CFG.targets.length > 1) {
        card.appendChild(menuItem('发送到全部 (' + CFG.targets.length + ')', '📤', function () {
          var l = currentLink();
          if (!l) { toast('✗ 找不到当前推文'); return; }
          CFG.targets.forEach(function (t, i) { setTimeout(function () { sendTo(t.chat, t.label || t.chat, l); }, i * 900); });
        }));
      }
      var sep = document.createElement('div'); sep.className = 'sep'; card.appendChild(sep);
      // 链接域名切换（持久化到 config.json）
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
      card.appendChild(menuItem('复制当前链接(转换后)', '🔗', function () {
        var l = currentLink();
        if (l) { copyText(convert(l)); toast('✓ 已复制 ' + CFG.service + ' 链接'); }
        else toast('✗ 找不到当前推文');
      }));
      card.appendChild(menuItem('t.me 分享对话框', '🌐', function () {
        var l = currentLink();
        if (l) window.open('https://t.me/share/url?url=' + encodeURIComponent(convert(l)), '_blank');
      }));
      card.appendChild(menuItem('刷新配置', '🔄', function () {
        toast('配置刷新中…');
        loadConfig(function (ok) {
          toast(ok ? '✓ 配置已更新（' + CFG.targets.length + ' 个目标）' : '✗ 中继不可达');
          render();
        });
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
