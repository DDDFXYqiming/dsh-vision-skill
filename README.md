简体中文 | [English](README.en.md)

# dsh-plugins / dsh-vision-skill

**DeepSeek Harness（DSH）识图技能插件**。它把 `General_skills/vision-skill` 的图像工作流做成 DSH 原生插件，让不能接收图片的纯文本模型也能看图、做 OCR、定位目标。

自 v0.4 起，粘贴的图片由客户端先上传到工作区路径，再随消息发出，模型拿到路径后调用插件工具。旧的 `pi-ai` 图片转路径补丁保留下来，供仍在使用原附件通道的安装使用。

## 工具

| 名称 | 用途 |
|---|---|
| `vision` | 运行时技能，按需暴露下面的图像工具 |
| `vision_analyze` | 分析本地图片，支持 general、ocr、table、code、error、evidence 六种模式 |
| `vision_ocr` | 提取可见文字并保留排版 |
| `vision_ground` | 定位指定目标，返回像素坐标与归一化坐标 |
| `vision_detect` | 枚举界面控件等元素，输出带编号的框 |
| `vision_dominant_colors` | 本地计算主色，不调用视觉 API |
| `vision_long_screenshot_ocr` | 长截图分块 OCR，先用本地 Tesseract，再由 VLM 兜底 |
| `vision_clipboard` | 把剪贴板图片保存到工作区，供后续识别 |
| `vision_activate` | 自动技能激活不可用时，手动暴露工具集 |

`vision_analyze` 的 evidence 模式返回 `summary`、`ocr_full_text`、按阅读顺序排列的 `layout`、语义 `entities` 与 `relations`、`uncertainty` 和 `visual` 字段。识别结果可按图片 SHA-256、模式、预算、裁剪和提示词缓存，缓存有效期与条目上限可配置。

## 三种送图方式

| 方式 | 操作 | 适用场景 |
|---|---|---|
| 直接给路径 | 在对话里写「识别这张图 <路径>」 | 所有环境 |
| 剪贴板 | 用 Win+Shift+S 截图后说「识别剪贴板截图」，`vision_clipboard` 会把它存进工作区 | 所有环境 |
| 直接粘贴 | 粘贴的图片上传到 `.dsh-vision/pasted/`，消息里插入路径文本 | 所有环境 |

图片工具的参数是路径，图片字节不会进入消息。路径必须位于会话工作区、DSH 附件目录或配置的 `allowedDirs` 之内。

## 安装

常规 profile 安装：

```powershell
dsh plugin --profile web add github:DDDFXYqiming/dsh-vision-skill
```

本地开发时，把链接加进 web profile 的依赖并执行 `pnpm install`：

```powershell
git clone https://github.com/DDDFXYqiming/dsh-vision-skill.git
cd dsh-vision-skill
# 在 profile 依赖里加入 dsh-vision-skill: link:<绝对路径>
```

插件自带的 `cordis.patch.yml` 提供 `id: vision-skill` 条目。覆盖配置时写一条完整的裸条目，不要另外插入同 id 的第二条；补丁替换按行进行，需要保留的每个配置字段都要写上。

```yaml
- id: vision-skill
  config:
    apiUrl: 'https://api.example.com/v1/chat/completions'
    model: 'your-vision-model'
    credential: 'VISION_API_KEY'
    visionProviders:
      - apiUrl: 'https://api.example.com/v1/chat/completions'
        model: 'your-vision-model'
        credential: 'VISION_API_KEY'
    tesseract: tesseract
    tesseractLangs: chi_sim+eng
    pasteMaxBytes: 10485760
    cache: true
    cacheTtlSeconds: 3600
    cacheMaxEntries: 200
```

`credential` 指向 DSH 凭据，优先于内联 `apiKey`。provider 按顺序尝试，遇到 429、5xx 或网络错误会转到下一条。凭据存放在 `$DSH_HOME/.credentials.yaml`。

主要选项包括 `timeoutMs`（默认 180 秒）、`concurrency`（默认 2）、用于路径限制的 `allowedDirs`，以及上面的缓存开关。`progressive: false` 会把完整工具集注册到全局，跳过运行时技能这一层。

## 适配器支持

| 适配器或场景 | 粘贴图片 | 说明 |
|---|---|---|
| `dsh-llm-deepseek` | 可直接使用 | 较新的 DSH 版本内置图片转路径 |
| `dsh-llm-pi-ai` | 通过 v0.4 的 paste-to-path 使用 | 旧厂商补丁保留给仍在使用原附件通道的安装 |
| 原生多模态模型 | 直接发送图片 | 模型自行处理图片 |

兼容补丁按机器调整，目标是 profile 内的厂商包 `dsh-llm-pi-ai`。DSH 升级后，只有在需要旧附件行为时才重新执行，然后重启宿主。

```powershell
powershell -File scripts\reapply-pi-ai-vision-patch.ps1
```

## 运行要求

插件需要带 DSH 的 Node.js（`@deepseek-ai/dsh-tools`、`@deepseek-ai/dsh-credentials`、`@deepseek-ai/schemastery`）、装有 Pillow 的 Python 3、用于本地 OCR 快路径的 Tesseract，以及所选 OpenAI 兼容视觉模型的凭据。

## 示例

```text
识别这张图 <路径>        → vision_analyze
OCR 这张图 <路径>        → vision_ocr
找到图中的 <目标>        → vision_ground
清点图里的按钮          → vision_detect
分析图片主色            → vision_dominant_colors
提取长截图文字          → vision_long_screenshot_ocr
识别剪贴板截图          → vision_clipboard
```

## 更多

- [开发与自检](docs/development.md) 说明测试命令与兼容补丁的重放方式
- [设计说明](docs/design.md) 说明识别方法、工具暴露方式与目录结构
- `SKILL.md` 是 DSH 加载的运行时说明
- `templates/.env.example` 记录独立脚本的配置
- 运行时技能名是 `vision`。同名技能若同时出现在项目层或用户层，DSH 按 `project > runtime > user` 的优先级解析，因此只装一层

## 许可

MIT
