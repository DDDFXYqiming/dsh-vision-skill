[简体中文](README.md) | English

# dsh-vision-skill

**Multimodal visual perception and target grounding extension for DeepSeek Harness (DSH).**

Wraps comprehensive multimodal computer vision capabilities into a native DSH Skill plugin. Even when operating with text-only foundation models, agents gain complete access to structured image comprehension, multi-pass OCR, UI element grounding, and pixel-precise bounding box detection through a hybrid on-device and VLM execution pipeline.

---

## Key Features

* **Comprehensive Vision Suite**:
  * **Deep Multimodal Analysis (`vision_analyze`)**: Specialized modes for general scenes, terminal/stack traces, code snippets, tabular data, and formal evidence chains.
  * **Semantic Grounding (`vision_ground`)**: Locates UI targets via natural language queries, returning exact pixel dimensions and normalized bounding coordinates.
  * **Interface Control Detection (`vision_detect`)**: Identifies all interactable elements across application windows with indexed boxes.
  * **Long Screenshot Slicing (`vision_long_screenshot_ocr`)**: Automatically tiles tall scrolling screenshots with overlap, prioritizing fast local Tesseract OCR before falling back to VLM reasoning.
  * **Local Color Profiling (`vision_dominant_colors`)**: Computes dominant palettes locally without consuming token quotas.
* **Three Flexible Ingestion Channels**:
  * **Direct Paste**: Web client uploads pasted images to `.dsh-vision/pasted/` and attaches filesystem references into the message stream.
  * **Clipboard Integration (`vision_clipboard`)**: Reads the active system clipboard (e.g. after Win+Shift+S) and stages screenshots directly into the workspace.
  * **Path References**: References existing workspace files directly in conversation turns.
* **Resilient Multi-Provider Fallbacks**: Configurable provider cascades automatically roll over upon rate limits (429), upstream server downtime (5xx), or connection timeouts.
* **Sandbox Confinement & Caching**: Strictly enforces path containment within workspace bounds, backed by a persistent result cache with configurable TTL.

---

## Tool Overview

| Tool Name | Core Role | Implementation |
| :--- | :--- | :--- |
| `vision` | Runtime skill activator exposing the image toolchain on demand | Dynamic skill loading |
| `vision_analyze` | Multimodal scene comprehension across six structured modes | OpenAI-compatible VLM endpoints |
| `vision_ocr` | Structure-preserving layout and text extraction | Local Tesseract / VLM fallback |
| `vision_ground` | Semantic visual query returning bounding boxes | Grounding pipeline |
| `vision_detect` | Enumerates interactable UI components with indexed labels | Component detector |
| `vision_dominant_colors`| Local color extraction with zero external API calls | Pillow color clustering |
| `vision_long_screenshot_ocr` | Chunks long scrolling screenshots and reconstructs text | Overlapping tiles + OCR |
| `vision_clipboard` | Ingests system clipboard buffers into workspace assets | OS clipboard handler |

---

## Installation & Setup

```bash
# Install directly via DSH Plugin Manager
dsh plugin --profile web add github:DDDFXYqiming/dsh-vision-skill
```

For local development:
```bash
git clone https://github.com/DDDFXYqiming/dsh-vision-skill.git
cd dsh-vision-skill
dsh plugin --profile web add .
```

---

## Configuration

Configure endpoints and local engine binaries in your profile's `cordis.patch.yml`:

```yaml
- id: vision-skill
  config:
    # Primary OpenAI-compatible vision model endpoint
    apiUrl: 'https://api.example.com/v1/chat/completions'
    model: 'your-vision-model'
    credential: 'VISION_API_KEY'     # Resolves from $DSH_HOME/.credentials.yaml
    # Automatic failover provider chain
    visionProviders:
      - apiUrl: 'https://api.backup.com/v1/chat/completions'
        model: 'backup-vision-model'
        credential: 'BACKUP_API_KEY'
    tesseract: 'tesseract'            # System Tesseract binary path
    tesseractLangs: 'chi_sim+eng'     # OCR language packs
    pasteMaxBytes: 10485760           # 10MB paste ceiling
    cache: true                       # Enable result caching
    cacheTtlSeconds: 3600             # Cache retention period
```

---

## License

This project is open-sourced under the [MIT License](LICENSE).
