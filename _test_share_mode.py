# -*- coding: utf-8 -*-
"""share_mode 相关纯函数的离线自测（不发送任何消息）"""
import server as s

fails = []


def ck(name, got, want):
    ok = got == want
    if not ok:
        fails.append(f"{name}: got={got!r} want={want!r}")
    print(("ok  " if ok else "FAIL") + f" {name} -> {got!r}")


ck("mode.global", s.resolve_share_mode({"share_mode": "album"}), "album")
ck("mode.target-override", s.resolve_share_mode({}, {"share_mode": "MEDIA"}), "album")
ck("mode.alias", s.resolve_share_mode({"share_mode": "gallery"}), "album")
ck("mode.unknown->link", s.resolve_share_mode({"share_mode": "bogus"}), "link")
ck("mode.default", s.resolve_share_mode({}), "link")

ck("convert.fixupx", s.convert_link("fixupx", "https://x.com/a/status/1"), "https://fixupx.com/a/status/1")
ck("convert.vxtwitter", s.convert_link("vxtwitter", "https://twitter.com/a/status/1"),
   "https://vxtwitter.com/a/status/1")
ck("convert.unknown-host", s.convert_link("fixupx", "https://example.com/a"), "https://example.com/a")

ck("official.fixupx", s.official_link("https://fixupx.com/a/status/1"), "https://x.com/a/status/1")
ck("official.vxtwitter", s.official_link("https://vxtwitter.com/a/status/1"),
   "https://twitter.com/a/status/1")
ck("official.keep-x", s.official_link("https://x.com/a/status/1"), "https://x.com/a/status/1")
ck("official.force", s.official_link("https://vxtwitter.com/a/status/1", "x.com"),
   "https://x.com/a/status/1")

ck("photo_orig.query", s.photo_orig("https://pbs.twimg.com/media/ABC?format=jpg&name=small"),
   "https://pbs.twimg.com/media/ABC?format=jpg&name=orig")
ck("photo_orig.noquery", s.photo_orig("https://pbs.twimg.com/media/ABC.jpg"),
   "https://pbs.twimg.com/media/ABC.jpg")
ck("photo_large", s.photo_large("https://pbs.twimg.com/media/ABC?format=jpg&name=orig"),
   "https://pbs.twimg.com/media/ABC?format=jpg&name=large")
ck("media_key", s.media_key("https://pbs.twimg.com/media/HR2rD3eagAAukv1?format=jpg&name=small"),
   "HR2rD3eagAAukv1")

ph = [s.Media("photo", f"https://pbs.twimg.com/media/K{i}?format=jpg&name=orig") for i in range(3)]
link = "https://x.com/u/status/999"
ck("plan.album", s.plan_media(ph, "album", link)[0], "album")
ck("plan.album.count", len(s.plan_media(ph, "album", link)[1]), 3)
ck("plan.mosaic.kind", s.plan_media(ph, "mosaic", link)[0], "photo")
ck("plan.mosaic.url", s.plan_media(ph, "mosaic", link)[1][0].url,
   "https://mosaic.fxtwitter.com/jpeg/999/K0/K1/K2")
ck("plan.photo.first", s.plan_media(ph, "photo", link)[1][0].url, ph[0].url)
ck("plan.single->photo", s.plan_media(ph[:1], "album", link)[0], "photo")
vid = [s.Media("video", "https://video.twimg.com/x.mp4", "v.mp4", thumb="https://pbs.twimg.com/t.jpg")]
ck("plan.video-priority", s.plan_media(ph + vid, "album", link)[0], "video")

ck("dom_media", [m.url for m in s.dom_media({"photos": ["https://pbs.twimg.com/media/A?format=jpg&name=small"]})],
   ["https://pbs.twimg.com/media/A?format=jpg&name=orig"])
ck("dom_media.blob-video-ignored", len(s.dom_media({"photos": [], "video": "blob:https://x.com/x"})), 0)
ck("dom_media.http-video", len(s.dom_media({"video": "https://video.twimg.com/a.mp4"})), 1)
ck("dom_media.garbage", s.dom_media(None), [])

ck("tweet_re", bool(s.TWEET_RE.search("https://x.com/u/status/12345")), True)
ck("tweet_re.i", bool(s.TWEET_RE.search("https://twitter.com/i/status/12345")), True)
ck("text_template", s.build_text({"text_template": "[X] {link}"}, "https://x.com/a"),
   "[X] https://x.com/a")

# ---- 图片候选链（DOM 给的是 webp 缩略图时，应优先取 jpg 原图）----
ck("cand.webp-dom", s.photo_candidates("https://pbs.twimg.com/media/ABC?format=webp&name=large"),
   ["https://pbs.twimg.com/media/ABC?format=jpg&name=orig",
    "https://pbs.twimg.com/media/ABC?format=webp&name=large"])
ck("cand.keep-png", s.photo_candidates("https://pbs.twimg.com/media/ABC?format=png&name=large")[0],
   "https://pbs.twimg.com/media/ABC?format=png&name=orig")
ck("cand.api-url", s.photo_candidates("https://pbs.twimg.com/media/ABC.jpg?name=orig")[0],
   "https://pbs.twimg.com/media/ABC.jpg?format=jpg&name=orig")
ck("cand.keep-other-params", s.photo_candidates("https://pbs.twimg.com/media/A?format=jpg&name=small&foo=1")[0],
   "https://pbs.twimg.com/media/A?foo=1&format=jpg&name=orig")
ck("curl-retry-tail", s.photo_candidates("https://pbs.twimg.com/media/A?format=webp&name=large")[-1],
   "https://pbs.twimg.com/media/A?format=webp&name=large")
ck("sniff.jpg", s.sniff_image(b"\xff\xd8\xff\xe0rest"), (".jpg", "image/jpeg"))
ck("sniff.png", s.sniff_image(b"\x89PNG" + b"\r\n\x1a\n"), (".png", "image/png"))
ck("sniff.webp", s.sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 "), (".webp", "image/webp"))

# ---- 媒体模式配文 ----
ck("caption.text+link", s.build_caption({}, {}, "https://x.com/u/status/1", "正文"),
   "正文\n\nhttps://x.com/u/status/1")
ck("caption.no-text->template", s.build_caption({"text_template": "📌 {link}"}, {},
                                                "https://x.com/u/status/1", ""),
   "📌 https://x.com/u/status/1")
ck("caption.custom", s.build_caption({"caption_template": "{text} / {link}"}, {},
                                     "https://x.com/u/status/1", "hi"),
   "hi / https://x.com/u/status/1")

print("\n" + ("ALL PASS" if not fails else "FAILURES:\n" + "\n".join(fails)))
raise SystemExit(1 if fails else 0)
