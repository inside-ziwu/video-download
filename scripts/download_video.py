#!/usr/bin/env python3
"""Durable video downloader for social-video links."""

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = SKILL_DIR / ".env"
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads" / "video-downloads"

DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def log(message):
    print(message, file=sys.stderr)


def load_dotenv(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        os.environ.setdefault(key, val)


load_dotenv(ENV_FILE)

WECHAT_RESOLVERS = ("cookie", "public-worker")


def default_wechat_resolver():
    resolver = (
        os.getenv("WECHAT_RESOLVER")
        or os.getenv("VIDEO_DOWNLOAD_WECHAT_RESOLVER")
        or "cookie"
    ).strip()
    if resolver not in WECHAT_RESOLVERS:
        log(f"[WARN] WECHAT_RESOLVER={resolver!r} 无效,回退 cookie")
        return "cookie"
    return resolver


def check_cmd(cmd):
    try:
        subprocess.run([cmd, "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def check_ytdlp():
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def safe_filename(name, max_len=90):
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:max_len].strip(" .") or "video"


def unique_path(path):
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 1000):
        candidate = path.with_name(f"{stem}-{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不重复文件名: {path}")


def is_url(value):
    return value.startswith("http://") or value.startswith("https://")


def detect_platform(value):
    lower = value.lower()
    if "weixin.qq.com/sph" in lower or "channels.weixin.qq.com" in lower:
        return "wechat_channels"
    if "xiaohongshu.com" in lower or "xhslink.com" in lower:
        return "xiaohongshu"
    if "douyin.com" in lower or "v.douyin.com" in lower:
        return "douyin"
    if "bilibili.com" in lower or "b23.tv" in lower:
        return "bilibili"
    if "youtube.com" in lower or "youtu.be" in lower:
        return "youtube"
    if is_url(value):
        return "unknown"
    return "local"


def request_json(url, payload, headers, timeout=35):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"请求失败: HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络请求失败: {exc.reason}") from None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise RuntimeError("接口返回不是 JSON") from None


def sph_cookie():
    return os.getenv("SPH_COOKIE") or os.getenv("YUANBAO_COOKIE") or ""


def normalize_sph_url(url):
    parsed = urllib.parse.urlparse(url)
    if "weixin.qq.com" in parsed.netloc and "/sph/" in parsed.path:
        return url
    if "channels.weixin.qq.com" in parsed.netloc:
        qs = urllib.parse.parse_qs(parsed.query)
        sid = (qs.get("id") or [""])[0]
        if sid:
            return f"https://weixin.qq.com/sph/{sid}"
    return url


def parse_share_url(share_url, cookie):
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/json",
        "origin": "https://yuanbao.tencent.com",
        "referer": "https://yuanbao.tencent.com/chat/naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
        "user-agent": DESKTOP_UA,
        "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "t-userid": "b9575f6b0a8c4a55a08096904a5ef20a",
        "x-agentid": "naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
        "x-commit-tag": "72282a0d",
        "x-device-id": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
        "x-hy106": "",
        "x-hy92": "e963067ffa31002b9646bd0c03000008b1951a",
        "x-hy93": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
        "x-id": "b9575f6b0a8c4a55a08096904a5ef20a",
        "x-instance-id": "5",
        "x-language": "zh-CN",
        "x-os_version": "Mac OS(10.15.7)-Blink",
        "x-web-third-source": "main",
        "x-webdriver": "0",
        "x-webversion": "2.69.0",
        "x-ybuitest": "0",
        "x-requested-with": "XMLHttpRequest",
        "x-source": "web",
        "x-platform": "mac",
        "cookie": cookie,
    }
    payload = {"type": "video_channel_url", "url": share_url, "scene": 1}
    result = request_json(
        "https://yuanbao.tencent.com/api/weixin/get_parse_result",
        payload,
        headers,
    )
    if result.get("code") not in (None, 0):
        raise RuntimeError(f"元宝解析失败: {result.get('msg') or result.get('message') or result.get('code')}")
    data = result.get("data") or {}
    if not data.get("playable_url") and not data.get("wx_export_id"):
        raise RuntimeError("元宝解析未返回 playable_url 或 wx_export_id, Cookie 可能失效")
    return data


def generate_rid():
    return f"{int(time.time()):x}-" + "".join(random.choice("0123456789abcdef") for _ in range(8))


def get_feed_info(export_id, general_token):
    rid = generate_rid()
    api_url = (
        "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
        f"?_rid={rid}&_pageUrl=https:%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed"
    )
    referer = (
        "https://channels.weixin.qq.com/finder-preview/pages/feed"
        f"?entry_card_type=48&comment_scene=39&appid=0"
        f"&token={urllib.parse.quote(general_token)}"
        f"&entry_scene=0&eid={urllib.parse.quote(export_id)}"
    )
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Origin": "https://channels.weixin.qq.com",
        "Referer": referer,
        "User-Agent": DESKTOP_UA,
    }
    result = request_json(
        api_url,
        {"baseReq": {"generalToken": general_token}, "exportId": export_id},
        headers,
    )
    if result.get("errCode") not in (None, 0):
        raise RuntimeError(f"视频号详情接口失败: {result.get('errMsg') or result.get('errCode')}")
    return result


def best_wechat_url(feed_info, quality):
    h264 = ((feed_info.get("h264VideoInfo") or {}).get("videoUrl") or "").strip()
    h265 = ((feed_info.get("h265VideoInfo") or {}).get("videoUrl") or "").strip()
    base = (feed_info.get("videoUrl") or "").strip()
    if quality == "h265":
        picked = h265 or h264 or base
    else:
        picked = h264 or base or h265
    if not picked:
        raise RuntimeError("视频号详情没有返回可下载视频流")
    return picked


def wechat_profile_from_feed(feed, parsed, input_url, quality, resolver):
    data = feed.get("data") or {}
    feed_info = data.get("feedInfo") or {}
    author_info = data.get("authorInfo") or {}
    video_url = best_wechat_url(feed_info, quality)
    desc = feed_info.get("description") or parsed.get("desc") or "weixin_channels_video"
    author = author_info.get("nickname") or parsed.get("author") or ""
    title = f"{author}-{desc}" if author else desc
    return {
        "platform": "wechat_channels",
        "title": title,
        "author": author,
        "description": desc,
        "source_url": normalize_sph_url(input_url),
        "quality": quality,
        "resolver": resolver,
        "direct_url": video_url,
        "stats": {
            "fav": feed_info.get("favCountFmt"),
            "like": feed_info.get("likeCountFmt"),
            "forward": feed_info.get("forwardCountFmt"),
            "comment": feed_info.get("commentCountFmt"),
        },
    }


def fetch_public_worker_profile(input_url):
    log("[INFO] 视频号: 使用公共 Worker 解析(第三方服务)")
    return request_json(
        "https://sph.litao.workers.dev/api/fetch_video_profile",
        {"url": normalize_sph_url(input_url)},
        {"Content-Type": "application/json", "User-Agent": DESKTOP_UA},
    )


def wechat_profile(input_url, quality, resolver="cookie"):
    if resolver == "public-worker":
        feed = fetch_public_worker_profile(input_url)
        return wechat_profile_from_feed(feed, {}, input_url, quality, resolver)

    cookie = sph_cookie()
    if not cookie:
        raise RuntimeError(
            "缺少 SPH_COOKIE/YUANBAO_COOKIE。请复制 video-download/.env.example 为 .env 后填入元宝 Web Cookie。"
        )
    share_url = normalize_sph_url(input_url)
    log("[INFO] 视频号: 使用本地 SPH Cookie 解析分享链接")
    parsed = parse_share_url(share_url, cookie)
    playable = parsed.get("playable_url") or ""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(playable).query)
    general_token = (query.get("token") or [""])[0]
    export_id = (query.get("eid") or query.get("exportId") or [""])[0]
    if not export_id:
        export_id = parsed.get("wx_export_id") or ""
    if not general_token or not export_id:
        raise RuntimeError("元宝 playable_url 缺少 token 或 eid,无法继续请求视频流")
    feed = get_feed_info(export_id, general_token)
    return wechat_profile_from_feed(feed, parsed, share_url, quality, resolver)


def find_video_transcript_scripts():
    candidates = [
        Path.home() / ".workbuddy" / "skills" / "video-transcript" / "scripts",
        Path.home() / ".agents" / "skills" / "video-transcript" / "scripts",
        Path.home() / ".Codex" / "skills" / "video-transcript" / "scripts",
        Path.home() / ".codex" / "skills" / "video-transcript" / "scripts",
        Path.home() / ".claude" / "skills" / "video-transcript" / "scripts",
    ]
    for path in candidates:
        if (path / "platform_extractor.py").exists():
            return path
    return None


def platform_extract(url):
    scripts_dir = find_video_transcript_scripts()
    if not scripts_dir:
        raise RuntimeError("找不到 video-transcript/scripts/platform_extractor.py")
    sys.path.insert(0, str(scripts_dir))
    from platform_extractor import extract

    return extract(url, headless=True)


def download_url(url, out_path, headers=None, timeout=900):
    req = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp, open(out_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as exc:
        if out_path.exists():
            out_path.unlink()
        raise RuntimeError(f"下载失败: {type(exc).__name__}") from None
    if not out_path.exists() or out_path.stat().st_size < 1024:
        raise RuntimeError("下载失败: 文件为空或过小")


def download_browser_platform(url, output_dir):
    info = platform_extract(url)
    title = info.get("title") or detect_platform(url)
    out_path = unique_path(output_dir / f"{safe_filename(title)}.mp4")
    headers = info.get("headers") or {}
    if info.get("needs_merge"):
        temp_dir = output_dir / ".tmp-video-download"
        temp_dir.mkdir(exist_ok=True)
        v_path = temp_dir / f"{int(time.time())}_video.m4s"
        a_path = temp_dir / f"{int(time.time())}_audio.m4s"
        download_url(info["video_url"], v_path, headers)
        download_url(info["audio_url"], a_path, headers)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(v_path),
            "-i",
            str(a_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        for p in (v_path, a_path):
            try:
                p.unlink()
            except OSError:
                pass
        if result.returncode != 0 or not out_path.exists():
            raise RuntimeError(f"ffmpeg 合并失败: {result.stderr[-300:]}")
    else:
        download_url(info["video_url"], out_path, headers)
    return {
        "platform": info.get("platform") or detect_platform(url),
        "title": title,
        "source_url": url,
        "path": str(out_path),
    }


def download_ytdlp(url, output_dir):
    if not check_ytdlp():
        raise RuntimeError("yt-dlp 未安装")
    start = time.time()
    template = str(output_dir / "%(title).90B-%(id)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f",
        "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "--merge-output-format",
        "mp4",
        "--no-playlist",
        "-o",
        template,
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp 下载失败: {result.stderr[-400:]}")
    files = [
        p
        for p in output_dir.iterdir()
        if p.is_file() and p.stat().st_mtime >= start - 1 and p.suffix.lower() in (".mp4", ".webm", ".mkv")
    ]
    if not files:
        raise RuntimeError("yt-dlp 下载完成但未找到输出文件")
    path = max(files, key=lambda p: p.stat().st_mtime)
    return {
        "platform": detect_platform(url),
        "title": path.stem,
        "source_url": url,
        "path": str(path),
    }


def copy_local_video(input_path, output_dir):
    src = Path(input_path).expanduser().resolve()
    if not src.exists():
        raise RuntimeError(f"本地文件不存在: {src}")
    dst = unique_path(output_dir / src.name)
    shutil.copy2(src, dst)
    return {
        "platform": "local",
        "title": src.stem,
        "source_url": str(src),
        "path": str(dst),
    }


def ffprobe(path):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 读取失败: {result.stderr[-300:]}")
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float((data.get("format") or {}).get("duration") or 0)
    size = int((data.get("format") or {}).get("size") or Path(path).stat().st_size)
    if not video_streams:
        raise RuntimeError("ffprobe 未发现视频流")
    if duration <= 0:
        raise RuntimeError("ffprobe 时长为 0")
    if size < 100 * 1024:
        raise RuntimeError("文件小于 100KB,疑似下载不完整")
    v0 = video_streams[0]
    a0 = audio_streams[0] if audio_streams else {}
    return {
        "duration": duration,
        "size_bytes": size,
        "video_codec": v0.get("codec_name"),
        "width": v0.get("width"),
        "height": v0.get("height"),
        "has_audio": bool(audio_streams),
        "audio_codec": a0.get("codec_name"),
        "format": (data.get("format") or {}).get("format_name"),
    }


def write_metadata(result, output_dir):
    meta = {
        "platform": result.get("platform"),
        "title": result.get("title"),
        "author": result.get("author"),
        "description": result.get("description"),
        "source_url": result.get("source_url"),
        "quality": result.get("quality"),
        "resolver": result.get("resolver"),
        "stats": result.get("stats"),
        "path": result.get("path"),
        "verification": result.get("verification"),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    path = Path(result["path"]).with_suffix(".json")
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def download(input_value, output_dir, quality, wechat_resolver="cookie"):
    output_dir.mkdir(parents=True, exist_ok=True)
    platform = detect_platform(input_value)
    if platform == "wechat_channels":
        profile = wechat_profile(input_value, quality, resolver=wechat_resolver)
        out_path = unique_path(output_dir / f"{safe_filename(profile['title'])}.mp4")
        log("[INFO] 视频号: 下载视频流")
        download_url(
            profile["direct_url"],
            out_path,
            {
                "User-Agent": DESKTOP_UA,
                "Referer": "https://channels.weixin.qq.com/",
            },
        )
        result = {k: v for k, v in profile.items() if k != "direct_url"}
        result["path"] = str(out_path)
    elif platform in ("douyin", "xiaohongshu", "bilibili"):
        log(f"[INFO] {platform}: 复用 video-transcript 平台提取器")
        result = download_browser_platform(input_value, output_dir)
    elif platform in ("youtube", "unknown"):
        log(f"[INFO] {platform}: 使用 yt-dlp 下载")
        result = download_ytdlp(input_value, output_dir)
    else:
        result = copy_local_video(input_value, output_dir)

    verification = ffprobe(result["path"])
    result["verification"] = verification
    result["metadata_path"] = write_metadata(result, output_dir)
    return result


def probe(input_value, quality, wechat_resolver="cookie"):
    platform = detect_platform(input_value)
    if platform == "wechat_channels":
        profile = wechat_profile(input_value, quality, resolver=wechat_resolver)
        return {k: v for k, v in profile.items() if k != "direct_url"}
    if platform in ("douyin", "xiaohongshu", "bilibili"):
        info = platform_extract(input_value)
        return {
            "platform": info.get("platform") or platform,
            "title": info.get("title"),
            "duration": info.get("duration"),
            "source_url": input_value,
        }
    return {"platform": platform, "source_url": input_value}


def doctor():
    print("=" * 55)
    print("  video-download 体检")
    print("=" * 55)
    issues = []
    for cmd in ("ffmpeg", "ffprobe"):
        if check_cmd(cmd):
            print(f"  ✓ {cmd}")
        else:
            print(f"  ✗ {cmd} 未安装")
            issues.append(cmd)
    if check_ytdlp():
        print("  ✓ yt-dlp")
    else:
        print("  ⚠ yt-dlp 未安装(YouTube/部分未知平台会不可用)")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = p.chromium.executable_path
            if exe and Path(exe).exists():
                print("  ✓ playwright + chromium")
            else:
                print("  ✗ chromium 未安装")
                issues.append("chromium")
    except ImportError:
        print("  ✗ playwright 未安装")
        issues.append("playwright")
    if find_video_transcript_scripts():
        print("  ✓ video-transcript platform_extractor")
    else:
        print("  ✗ 找不到 video-transcript platform_extractor")
        issues.append("platform_extractor")
    if ENV_FILE.exists():
        print(f"  ✓ .env 文件: {ENV_FILE}")
    else:
        print(f"  ⚠ 未找到 .env 文件: {ENV_FILE}")
    resolver = default_wechat_resolver()
    print(f"  ✓ WECHAT_RESOLVER: {resolver}")
    if resolver == "public-worker":
        print("  ⚠ 视频号将使用公共 Worker 解析(会把链接发给第三方服务)")
    elif sph_cookie():
        print("  ✓ SPH_COOKIE/YUANBAO_COOKIE: 已配置")
    else:
        print("  ⚠ SPH_COOKIE/YUANBAO_COOKIE: 未配置(视频号 SPH 解析不可用)")
    print("=" * 55)
    if issues:
        print(f"  ❌ 发现 {len(issues)} 个必需项问题")
        return 1
    print("  ✅ 基础下载依赖就绪")
    return 0


def main():
    parser = argparse.ArgumentParser(description="下载视频到本地并验证")
    parser.add_argument("input", nargs="?", help="视频 URL 或本地视频路径")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--quality", choices=["h264", "h265"], default="h264", help="视频号优先清晰度")
    parser.add_argument(
        "--wechat-resolver",
        choices=["cookie", "public-worker"],
        default=default_wechat_resolver(),
        help="视频号解析方式: cookie=本地元宝 Cookie; public-worker=公共 Worker",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--probe", action="store_true", help="只探测元信息,不下载")
    parser.add_argument("--doctor", action="store_true", help="检查依赖")
    args = parser.parse_args()

    if args.doctor:
        sys.exit(doctor())
    if not args.input:
        parser.error("缺少 input 参数")

    try:
        if args.probe:
            result = probe(args.input, args.quality, args.wechat_resolver)
        else:
            result = download(args.input, Path(args.output_dir).expanduser(), args.quality, args.wechat_resolver)
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    result["ok"] = True
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        if args.probe:
            print(f"[OK] 探测完成: {result.get('title') or result.get('platform')}")
            return
        v = result["verification"]
        print("[OK] 下载完成")
        print(f"路径: {result['path']}")
        print(
            "校验: "
            f"{v.get('video_codec')} {v.get('width')}x{v.get('height')}, "
            f"audio={v.get('audio_codec') or 'none'}, "
            f"{v.get('duration'):.3f}s, {v.get('size_bytes')} bytes"
        )
        print(f"metadata: {result['metadata_path']}")


if __name__ == "__main__":
    main()
