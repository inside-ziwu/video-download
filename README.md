# 视频下载（video-download）Skill

把 抖音 / 小红书 / B站 / YouTube / 微信视频号 链接 或 本地视频文件，下载成 durable MP4 保存到本地。输出重点是**文件**，不做逐字稿（那是 [video-transcript](https://github.com/inside-ziwu/video-transcript) 的活）。

> 本仓库是 [Backtthefuture/video-download](https://github.com/Backtthefuture/video-download) 的 fork，与 [inside-ziwu/video-transcript](https://github.com/inside-ziwu/video-transcript) 配套，安装命令均指向 fork。

本 skill 也是 [video-transcript](https://github.com/inside-ziwu/video-transcript) 的**配套依赖**：处理微信视频号时，video-transcript 会调用本 skill 先把视频保存为本地 MP4，再交给 FunASR 转录。

---

## 安装

```bash
# 与 video-transcript 一起装（推荐，会自动带本 skill）
bash <(curl -fsSL https://raw.githubusercontent.com/inside-ziwu/video-transcript/main/bootstrap.sh)
```

单独装：

```bash
npx skills add inside-ziwu/video-download -a claude-code -g -y
pip install --break-system-packages -r ~/.claude/skills/video-download/requirements.txt
python3 -m playwright install chromium
```

## 用法

```bash
python3 ~/.claude/skills/video-download/scripts/download_video.py "<URL或本地路径>"
```

输出 JSON（供其他脚本调用）：

```bash
python3 ~/.claude/skills/video-download/scripts/download_video.py "<URL或本地路径>" --json
```

默认保存到 `~/Downloads/video-downloads/`，可用 `--output-dir` 改目录。

## 支持的平台

- 抖音：`douyin.com/video/...`、`v.douyin.com/...`
- 小红书：`xiaohongshu.com/explore/...`、`xhslink.com/...`
- B站：`bilibili.com/video/...`、`b23.tv/...`
- YouTube：`youtube.com/watch?v=...`、`youtu.be/...`
- 微信视频号：`weixin.qq.com/sph/...`、`channels.weixin.qq.com/...`
- 本地视频文件路径

## 微信视频号解析方式

`.env` 里配 `WECHAT_RESOLVER`：

- `yuanbao-login`（**默认**）：复用 `~/.workbuddy/credentials/yuanbao_state.json` 的腾讯元宝持久化登录态（扫码一次长期复用），走腾讯官方接口，不导出 Cookie、不依赖第三方服务
- `public-worker`：走 `https://sph.litao.workers.dev` 公共 Worker，无需本机配置，但链接会发给第三方服务；**公共 Worker 失效时自动回退到元宝登录态解析**
- `cookie`：用本机元宝 Cookie 解析，需在 `.env` 配置 `SPH_COOKIE` 或 `YUANBAO_COOKIE`

```bash
cp ~/.claude/skills/video-download/.env.example ~/.claude/skills/video-download/.env
# 编辑 .env，设置 WECHAT_RESOLVER
```

### 元宝登录态解析（推荐，最稳）

公共 Worker 已失效（返回微信错误码 1042）。推荐配置元宝登录态：

```bash
# 1. 首次建立登录态（弹出浏览器,微信扫码一次,保存到 ~/.workbuddy/credentials/yuanbao_state.json）
python3 ~/.workbuddy/skills/video-transcript/scripts/sph_resolver.py --login

# 2. 检查登录态是否有效
python3 ~/.workbuddy/skills/video-transcript/scripts/sph_resolver.py --check

# 3. 直接解析视频号链接(输出 JSON,含 direct_url)
python3 ~/.workbuddy/skills/video-transcript/scripts/sph_resolver.py "https://weixin.qq.com/sph/xxx"
```

登录态有效期与微信授权一致，过期后重新 `--login` 扫码即可。之后无论 `WECHAT_RESOLVER` 配的什么，公共 Worker 或 cookie 失败时都会自动回退到这条链路。

## 体检

```bash
python3 ~/.claude/skills/video-download/scripts/download_video.py --doctor
```

检查项：ffmpeg / ffprobe / yt-dlp / playwright + chromium / video-transcript platform_extractor（抖音/小红书/B站复用）/ 视频号 Cookie 配置状态。

## 依赖关系

```
video-transcript ──(视频号)──> video-download
video-download  ──(抖音/小红书/B站)──> video-transcript 的 platform_extractor.py
```

两个 skill 互相依赖，建议一起安装。下载完成后必须用 ffprobe 校验：文件存在、大小 > 100KB、有视频流、时长 > 0，并记录分辨率/编码/时长。

## 隐私

- `.env` 只在你本机，`.gitignore` 已屏蔽，不提交
- 不带 token 的视频直链不会写入日志或 metadata
- 使用 `public-worker` 时视频号链接会发送给第三方 Worker 服务；在意隐私用默认的 `yuanbao-login` 模式（链接只发给腾讯官方接口）
