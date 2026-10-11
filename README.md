简体中文 | [English](README.en.md)

# dsh-vision-skill

**面向 DeepSeek Harness (DSH) 的多模态视觉感知与目标定位扩展**。

本插件将通用的多模态图像感知能力封装为 DSH 原生 Skill 插件。即使用户所用的主模型为纯文本大语言模型，也能通过本地混合处理流水线与多模态 VLM 工具链，实现全格式图像深度解析、长截图切片 OCR、界面 UI 控件目标检测（Grounding）与像素级坐标定位。

---

## 核心特性

* **全能多模态工具链**：
  * **深度多维度分析（`vision_analyze`）**：支持通用场景、代码/报错截图、数据表格、高保真证据链等多种专业分析模式。
  * **精准界面定位（`vision_ground`）**：按自然语言语义检索目标元素，返回像素坐标与归一化边界框（Bounding Box）。
  * **控件全量枚举（`vision_detect`）**：自动探测界面中所有可交互元素与按钮，生成带编号的标记清单。
  * **超长截图分块识别（`vision_long_screenshot_ocr`）**：自动重叠切片扫描超长界面，优先走本地 Tesseract 快速路径，并在需要时平滑回退至 VLM 视觉大模型。
  * **本地主色提取（`vision_dominant_colors`）**：纯本地解算画面主导色谱，不消耗任何外部 API 预算。
* **三通道极简交互**：
  * **直接粘贴**：粘贴图片自动上传至 `.dsh-vision/pasted/`，无缝转化为路径引用进入消息流。
  * **系统剪贴板（Win+Shift+S）**：调用 `vision_clipboard` 一键将剪贴板最新截图持久化至工作区并立即识别。
  * **文件路径引用**：在对话中直接输入工作区内的绝对或相对图片路径。
* **高可用故障转移与多提供商 Fallback**：支持配置多个视觉模型提供商，遇到限流（429）、服务器故障（5xx）或网络超时自动故障转移至下一个节点。
* **多级安全围栏与缓存加速**：严格校验文件操作边界（仅限工作区与授权目录），并提供带 TTL 和容量上限的图像特征缓存。

---

## 工具矩阵一览

| 工具名称 | 核心定位 | 技术实现 |
| :--- | :--- | :--- |
| `vision` | 运行时 Skill 入口，按需动态加载视觉工具集 | 渐进式加载 |
| `vision_analyze` | 深度多模式分析（通用、OCR、表格、代码、错误、证据链） | VLM API + 结构化提示词 |
| `vision_ocr` | 保持排版结构的可见文字提取 | 本地 Tesseract / VLM |
| `vision_ground` | 根据描述定位目标，输出精确像素与归一化边界框 | 语义定位引擎 |
| `vision_detect` | 枚举界面中的 UI 控件并输出编号坐标框 | 目标检测管道 |
| `vision_dominant_colors`| 纯本地计算主色调分布，零 API 消耗 | Python Pillow 颜色聚类 |
| `vision_long_screenshot_ocr` | 长截图重叠分块扫描与文字重组拼接 | 重叠切片 + 混合 OCR |
| `vision_clipboard` | 读取系统剪贴板图像并安全落盘至工作区 | 本地剪贴板操作 |

---

## 安装与快速上手

```bash
# 通过 DSH 插件管理器直接安装
dsh plugin --profile web add github:DDDFXYqiming/dsh-vision-skill
```

本地开发：
```bash
git clone https://github.com/DDDFXYqiming/dsh-vision-skill.git
cd dsh-vision-skill
dsh plugin --profile web add .
```

---

## 配置指南

在对应 Profile 的 `cordis.patch.yml` 中配置视觉模型接口与本地 OCR 参数：

```yaml
- id: vision-skill
  config:
    # 主视觉模型端点（支持 OpenAI 兼容的多模态 API 格式）
    apiUrl: 'https://api.example.com/v1/chat/completions'
    model: 'your-vision-model'
    credential: 'VISION_API_KEY'     # 引用 $DSH_HOME/.credentials.yaml 中的凭据
    # 多节点故障转移备选列表
    visionProviders:
      - apiUrl: 'https://api.backup.com/v1/chat/completions'
        model: 'backup-vision-model'
        credential: 'BACKUP_API_KEY'
    tesseract: 'tesseract'            # 本地 Tesseract 可执行文件路径
    tesseractLangs: 'chi_sim+eng'     # OCR 语言支持
    pasteMaxBytes: 10485760           # 粘贴图片大小上限（10MB）
    cache: true                       # 启用结果缓存
    cacheTtlSeconds: 3600             # 缓存生存时间
```

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
