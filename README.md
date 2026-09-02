简体中文 | [English](README.en.md)

# dsh-plugins / dsh-vision-skill

**DeepSeek Harness（DSH）标准插件版识图技能**。它把本仓库 `General_skills/vision-skill`（源自 Qwen 官方动态分辨率方法）包装成 DSH 原生插件，让不支持图片的纯文本模型也能看图、OCR、定位目标。

> 零框架补丁。插件只使用官方扩展接缝（`ctx.skills.register` / `ctx.tools.register` / `ctx.credentials` / `ctx.sessions` / `ctx.webServer` / client 注入）。v0.4 起直接贴图走 paste-to-path，不再需要 pi-ai 补丁。旧补丁仅作兼容保留，附还原脚本。

## 能力（8 工具 + 1 运行时 skill）

| 名称 | 说明 |
|---|---|
| `vision`（runtime skill） | 模型按需加载的识图指令。加载后自动激活下列工具（渐进式暴露） |
| `vision_analyze` | 识别本地图片，共 6 种模式（general / ocr / table / code / error / **evidence 结构化证据**），`budget` 含 `mega` 档 16M 像素 |
| `vision_ocr` | 独立 OCR，保留原始排版 |
| `vision_ground` | 目标定位（比如找「微信图标」），返回像素坐标和归一化坐标 |
| `vision_detect` | 枚举一类元素，给出编号和像素坐标框 |
| `vision_dominant_colors` | 主色分析（本地像素算法，不耗视觉 API） |
| `vision_long_screenshot_ocr` | 超长截图分块 OCR。先跑本地 tesseract，不行再交给 VLM 兜底，最后合并 |
| `vision_clipboard` | 剪贴板图片兜底识别（paste-to-path 失败或特殊场景的手动通道） |
| `vision_activate` | 渐进式暴露的兜底。skill 加载后工具没自动出现时调用一次 |

## 工程化要点

- **渐进式工具暴露**。全局只挂 1 个轻量激活工具，完整工具集等 skill 加载后再按 Agent 挂载，省上下文。`progressive: false` 可回退为全局注册。
- **paste-to-path 直贴（v0.4.2 起输入框显示 📎 chip）**。client 在 capture 阶段截获粘贴的图片，发送时同源 POST 落盘到 `.dsh-vision/pasted/`。消息里没有 image 块，DSH 因此不再报 `MODEL_DOES_NOT_SUPPORT_IMAGES`。旧版宿主没有 reference 能力时，自动回退为插入路径文本。
- **多 provider failover 和 429 退避**。`visionProviders` 数组按顺序 failover，每个 provider 配 `apiUrl/model/apiKey/credential`。遇到 429 就按 `Retry-After` 退避重试一次。
- **结构化证据**。`vision_analyze` 的 `mode=evidence` 返回一段 JSON，包含 `summary / ocr_full_text / layout（阅读顺序）/ semantics（entities+relations）/ uncertainty / visual`。
- **本地 OCR 快路径**。长截图每一块先跑 tesseract，跑不了才调 VLM，省 token 也更快。
- **图像记忆缓存**。按图片 SHA-256 加 mode/budget/crop/prompt 做缓存，TTL 内命中直接返回 `cached:true`。
- **路径围栏**。图片路径必须位于会话工作区 / DSH 附件目录 / `allowedDirs` 之一，经 realpath 校验，防止路径穿越。
- **密钥 Credential 化**。config 支持 `credential: VISION_API_KEY`（DSH Credential 引用，每操作解析，推荐），也兼容 `apiKey` 明文（不推荐）。

## 识图核心方法

Qwen 官方动态分辨率预处理打头，`smart_resize` 负责像素预算和 patch 网格吸附，随后交给任意 OpenAI 兼容多模态模型。默认模型是 MiniMax-M3，`thinking: disabled` 关掉思考，可替换。Grounding 用 Qwen 官方方法，VLM 输出 0-1000 归一化 bbox，插件解析 JSON 和 `<ref><box>` 两种格式，再映射回像素坐标。

## 图片投递（三种）

| 方式 | 操作 | 适用 |
|---|---|---|
| ① 路径直发 | 对话框里发一句“识别这张图 `E:\...\xxx.png`” | 所有环境 |
| ② 剪贴板 | Win+Shift+S 截屏后说一声“看图”，`vision_clipboard` 自动保存到工作区 `.dsh-vision/` | 所有环境 |
| ③ 直接贴图 | v0.4 起内置。粘贴的图会同源上传到 `.dsh-vision/pasted/`，路径文本进入消息，模型再调 `vision_analyze` | ✅ 所有环境，**不需 pi-ai 补丁** |

pi-ai 适配器（opencode-go 等）的 image→path 旧补丁仅作兼容保留。dsh 升级后旧补丁若被重新打上，运行 `scripts/restore_pi_ai_vision_patch.py` 还原。

## 目录结构

```
dsh-vision-skill/
├── lib/index.js          # 插件主体（skill 注册 + 8 工具 + 渐进暴露 + 围栏）
├── scripts/vision.py     # 识图脚本（动态分辨率 / OCR / grounding / 主色 / 长图分块）
├── scripts/reapply-pi-ai-vision-patch.ps1  # pi-ai 补丁（兼容保留）
├── SKILL.md              # 运行时 skill 内容（模型按需加载）
├── package.json          # 插件包声明
└── templates/.env.example # 脚本独立运行时的配置模板
```

## 安装

### 方法一，本地 link（开发/直装）

```powershell
git clone https://github.com/DDDFXYqiming/dsh-vision-skill.git
cd dsh-vision-skill
# 在 C:\Users\<user>\.dsh\profiles\web\package.json 的 dependencies 加：
#   "dsh-vision-skill": "link:<绝对路径>\dsh-plugins\dsh-vision-skill"
# 然后在该目录执行 pnpm install
```

### 方法二，插件命令（推荐，bundle 标准安装）

```powershell
dsh plugin --profile web add github:DDDFXYqiming/dsh-vision-skill
```

安装后插件包自带的 `cordis.patch.yml` 会自动贡献 `id: vision-skill` 条目，不需要手动 insert。配置默认值由插件内置 Schemastery Config schema 提供（`apiUrl`=MiniMax / `model`=MiniMax-M3 / `credential`=VISION_API_KEY）。

### 配置（覆盖 bundle 默认值）

在 profile 的 `cordis.patch.yml` 里再 insert 一个 `id: vision-skill` 条目会出事。重复 id 会触发 `duplicate loader entry id`，宿主启动直接崩溃。需要自定义配置时，用裸条目按 id 覆盖（不带 `insert:` 包装）。

```yaml
# profile cordis.patch.yml —— 裸条目覆盖 bundle 行（patch 整行替换，不深合并）
- id: vision-skill
  config:
    apiUrl: '<你的多模态模型 OpenAI 兼容接口地址>'  # 如 https://api.minimaxi.com/v1/chat/completions
    model: '<模型名>'                                # 如 MiniMax-M3 / qwen-vl-plus / gemini-2.5-flash
    credential: 'VISION_API_KEY'   # 推荐：DSH Credential 引用
    # apiKey: '<明文 key>'         # 兼容旧方式（不推荐）
    visionProviders:               # 顺序 = failover 优先级（429/5xx/网络错误自动切下一个）
      - apiUrl: 'https://api.minimaxi.com/v1/chat/completions'
        model: MiniMax-M3
        credential: VISION_API_KEY
      - apiUrl: '<第三个 OpenAI 兼容端点>'
        model: '<模型>'
        apiKey: '<或明文 key>'
    tesseract: tesseract
    tesseractLangs: chi_sim+eng
    pasteMaxBytes: 10485760
    cache: true
    cacheTtlSeconds: 3600
    cacheMaxEntries: 200
    timeoutMs: 180000
    concurrency: 2
```

Credential 存到 `$DSH_HOME/.credentials.yaml`。

```yaml
VISION_API_KEY: sk-xxxx
```

## 使用示例

对话里用自然语言说需求就行，请求会被路由到对应的工具。

```
识别这张图 <路径>          → vision_analyze
OCR 这张图 <路径>          → vision_ocr
在这张图里找到 <目标>      → vision_ground（返回像素坐标框）
清点这张图的所有按钮       → vision_detect
这张图的主色是什么         → vision_dominant_colors（本地算法，不耗 API）
提取这段长聊天记录的文字   → vision_long_screenshot_ocr
看图（剪贴板截图）         → vision_clipboard
```

## 测试与自检

```bash
python -m unittest discover -s tests -v   # 16 项纯函数/回退链测试
npm run check                             # 语法 + 不请求 API 的自检
python scripts/vision.py --check --no-api # provider 链路 + PIL + tesseract 自检
```

改动后按 AGENTS.md 红线优先用 headless 自测。直接贴图属于 client/Web 行为，重启 web 宿主后强刷浏览器才能验证。

## 相关

- 通用技能源在 [General_skills/vision-skill](../../General_skills/vision-skill)
- 同名技能冲突的处理。本插件以 `runtime` 层注册技能名 `vision`。若同时在 `$DSH_HOME/skills`（user 层）或项目 `.dsh/skills`（project 层）装了同名技能，按官方优先级 project > runtime > user 可能互相遮蔽，建议二选一安装
- 采用 MIT 授权
