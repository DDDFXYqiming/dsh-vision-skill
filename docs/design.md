# 设计说明

## 识别方法

图像脚本先做 Qwen 官方动态分辨率预处理，由 `smart_resize` 处理像素预算与 patch 网格对齐，再交给 OpenAI 兼容的多模态端点识别。默认模型是 MiniMax-M3，思考关闭，可在配置里替换。

定位沿用同一套做法：模型输出 0 到 1000 的归一化坐标，插件同时解析 JSON 与 `<ref><box>` 两种格式，再把坐标映射回像素。

长截图的每个分块先跑本地 `tesseract`，Tesseract 不可用时才调用配置的 VLM。

## 运行时行为

- 渐进式工具暴露。全局只注册一个轻量的激活工具，技能加载后按 Agent 挂载完整工具集，节省上下文。`progressive: false` 改为全局注册。
- 多 provider 故障转移。`visionProviders` 按顺序尝试，遇到 429 时按 `Retry-After` 退避并重试一次，5xx 与网络错误直接转到下一条。
- 图片缓存。以图片 SHA-256 加上模式、预算、裁剪和提示词为键，命中且未过期时直接返回 `cached:true`。
- 路径沙箱。图片路径必须位于会话工作区、DSH 附件目录或 `allowedDirs` 之内，并用 realpath 校验阻断目录穿越。
- 凭据间接引用。配置里写 `credential: VISION_API_KEY` 指向 DSH 凭据，每次调用时解析；内联 `apiKey` 仍然可用。

## 目录结构

```text
dsh-vision-skill/
├── lib/index.js          # 插件主体：技能注册、工具注册、渐进暴露与路径沙箱
├── scripts/vision.py     # 识别脚本：动态分辨率、OCR、定位、主色与长截图
├── scripts/reapply-pi-ai-vision-patch.ps1   # pi-ai 兼容补丁
├── SKILL.md              # 运行时技能内容，按需加载
├── package.json          # 插件清单
└── templates/.env.example # 独立运行脚本的配置模板
```
