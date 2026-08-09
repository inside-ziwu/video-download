---
name: video-download
description: |
  下载视频到本地的专用 skill。支持抖音 / 小红书 / B站 / YouTube / 微信视频号分享链接 / 本地视频文件复制归档。输出重点是 durable MP4 文件，不做逐字稿。下载后必须用 ffprobe 验证视频流、音频流、时长、分辨率、文件大小。
  触发场景:
  - 用户说"下载视频"、"下载这个视频"、"只下载不用转录"
  - 用户说"视频号下载"、"下载视频号"
  - 用户贴视频链接且明确要保存本地文件
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
user-invocable: true
---

# 视频下载

> 输入链接或本地视频路径 → 下载/复制到可见目录 → ffprobe 校验 → 返回 MP4 路径。

## 阶段 0 · 定位 skill 根目录

被触发时先定位自己:

```bash
VD_HOME="$(
  for d in "$HOME/.workbuddy/skills/video-download" \
           "$HOME/.agents/skills/video-download" \
           "$HOME/.Codex/skills/video-download" \
           "$HOME/.codex/skills/video-download" \
           "$HOME/.claude/skills/video-download" \
           "$(pwd)/skills/video-download"; do
    [ -f "$d/SKILL.md" ] && echo "$d" && break
  done
)"
export VD_HOME
echo "VD_HOME=$VD_HOME"
```

如果输出为空,让用户给出路径并手工 `export VD_HOME=<路径>`。

## 阶段 1 · 依赖体检

首次运行或可疑时报:

```bash
python3 "$VD_HOME/scripts/download_video.py" --doctor
```

体检项:
- ffmpeg / ffprobe
- yt-dlp
- playwright + chromium
- 可复用的 `video-transcript/scripts/platform_extractor.py`
- 微信视频号 SPH Cookie 配置状态

## 阶段 2 · 下载

```bash
python3 "$VD_HOME/scripts/download_video.py" "<URL或本地路径>"
```

默认保存到:

```text
~/Downloads/video-downloads/
```

改保存目录:

```bash
python3 "$VD_HOME/scripts/download_video.py" "<URL或本地路径>" --output-dir "/path/to/videos"
```

输出 JSON,供其他脚本调用:

```bash
python3 "$VD_HOME/scripts/download_video.py" "<URL或本地路径>" --json
```

## 支持输入

- 抖音: `douyin.com/video/...`、`v.douyin.com/...`
- 小红书: `xiaohongshu.com/explore/...`、`xhslink.com/...`
- B站: `bilibili.com/video/...`、`b23.tv/...`
- YouTube: `youtube.com/watch?v=...`、`youtu.be/...`
- 微信视频号: `https://weixin.qq.com/sph/...`、`channels.weixin.qq.com/...`
- 本地视频文件路径

## 微信视频号说明

默认读取 `$VD_HOME/.env` 里的 `WECHAT_RESOLVER`:
- `WECHAT_RESOLVER=cookie`: 使用本机元宝 Cookie 解析,隐私更好,需要配置 `SPH_COOKIE` 或 `YUANBAO_COOKIE`。
- `WECHAT_RESOLVER=public-worker`: 使用 `https://sph.litao.workers.dev` 公共 Worker,不需要本机 Cookie,但视频号链接会发给第三方服务。

本机 Cookie 路线:
1. 读取 `$VD_HOME/.env` 里的 `SPH_COOKIE` 或 `YUANBAO_COOKIE`。
2. 调用腾讯元宝 Web 解析接口取得 `playable_url`。
3. 从 `playable_url` 提取 `token` 和 `eid/exportId`。
4. 调用视频号 `get_feed_info`。
5. 优先下载 h264 视频流;可用 `--quality h265` 改为 h265。

如果 `WECHAT_RESOLVER=cookie` 且没有 Cookie,脚本会停止并提示配置。

当前本机便捷配置可以写成:

```env
WECHAT_RESOLVER=public-worker
```

也可以临时显式指定:

```bash
python3 "$VD_HOME/scripts/download_video.py" "https://weixin.qq.com/sph/xxx" --wechat-resolver public-worker
```

## 验收标准

每次下载完成后必须检查:
- 文件存在且大小 > 100KB
- ffprobe 能读取容器
- 有视频流
- 记录是否有音频流
- 时长 > 0
- 输出分辨率、编码、音频编码、时长和文件大小

不要把带 token 的视频直链写入日志或 metadata。
