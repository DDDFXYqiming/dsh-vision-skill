Simplified Chinese | [English](README.en.md)

# dsh-plugins / dsh-vision-skill

**Image-recognition skill plugin for DeepSeek Harness (DSH).** It packages the `General_skills/vision-skill` image workflow as a native DSH plugin, so a text-only model that cannot receive images can still look at pictures, run OCR, and locate targets.

Since v0.4, pasted images are uploaded by the client to a workspace path before the message is sent. The model receives a path and calls the plugin tools. The older `pi-ai` image-to-path patch stays available for installations that still use the original attachment channel.

## Tools

| Name | Purpose |
|---|---|
| `vision` | Runtime skill that exposes the image tools on demand |
| `vision_analyze` | Analyze a local image in general, ocr, table, code, error, or evidence mode |
| `vision_ocr` | Extract visible text while preserving its layout |
| `vision_ground` | Locate a named target and return pixel and normalized boxes |
| `vision_detect` | Enumerate elements such as UI controls with numbered boxes |
| `vision_dominant_colors` | Calculate dominant colors locally without a vision API |
| `vision_long_screenshot_ocr` | OCR a long screenshot in overlapping chunks, using local Tesseract before a VLM fallback |
| `vision_clipboard` | Save a clipboard image to the workspace for recognition |
| `vision_activate` | Explicitly expose the tool set when automatic skill activation is unavailable |

`vision_analyze` evidence mode returns `summary`, `ocr_full_text`, reading-order `layout`, semantic `entities` and `relations`, `uncertainty`, and `visual` fields. Results can be cached by image SHA-256, mode, budget, crop, and prompt. The cache has configurable TTL and entry limits.

## Three ways to deliver an image

| Method | What you do | Where it works |
|---|---|---|
| Direct path | Type "recognize this image <path>" in the chat | Everywhere |
| Clipboard | Take a screenshot with Win+Shift+S and ask for the clipboard image; `vision_clipboard` stores it in the workspace | Everywhere |
| Direct paste | The pasted image is uploaded to `.dsh-vision/pasted/` and a path reference enters the message | Everywhere |

The image tools take a path argument. The path must resolve inside the session workspace, the DSH attachment directory, or a configured `allowedDirs` entry.

## Installation

For a normal profile installation:

```powershell
dsh plugin --profile web add github:DDDFXYqiming/dsh-vision-skill
```

For local development, add a link to the web profile dependencies and run `pnpm install` there:

```powershell
git clone https://github.com/DDDFXYqiming/dsh-vision-skill.git
cd dsh-vision-skill
# add dsh-vision-skill: link:<absolute-path> to the profile dependencies
```

The bundled `cordis.patch.yml` contributes `id: vision-skill`. When overriding it in a profile, use one complete bare entry and do not insert a second entry with the same id. Patch replacement is line-based, so include every config field that must remain active.

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

`credential` refers to a DSH credential and is preferred over an inline `apiKey`. Provider entries are tried in order; a 429, 5xx, or network error can move the request to the next entry. Store the credential in `$DSH_HOME/.credentials.yaml`.

The main options include `timeoutMs` with a default of 180 seconds, `concurrency` with a default of 2, `allowedDirs` for path fencing, and the cache controls above. `progressive: false` registers the full tool set globally instead of waiting for the runtime skill.

## Adapter support

| Adapter or scene | Pasted image | Notes |
|---|---|---|
| `dsh-llm-deepseek` | Works out of the box | Recent DSH versions include image-to-path conversion. |
| `dsh-llm-pi-ai` | Works through v0.4 paste-to-path | The older vendor patch serves installations that still use the original attachment path. |
| Native multimodal model | Image is sent directly | The model handles the image without conversion. |

The compatibility patch is machine-specific and targets the vendor `dsh-llm-pi-ai` package inside your profile. After a DSH upgrade, rerun it only when the old attachment behavior is required, then restart the host.

```powershell
powershell -File scripts\reapply-pi-ai-vision-patch.ps1
```

## Requirements

The plugin needs Node.js with DSH (`@deepseek-ai/dsh-tools`, `@deepseek-ai/dsh-credentials`, and `@deepseek-ai/schemastery`), Python 3 with Pillow, Tesseract for the local OCR fast path, and a credential for the chosen OpenAI-compatible vision model.

## Examples

```text
recognize this image <path>     → vision_analyze
OCR this image <path>           → vision_ocr
find <target> in this image     → vision_ground
list all buttons in this image  → vision_detect
what is the dominant color      → vision_dominant_colors
extract text from a long shot   → vision_long_screenshot_ocr
read the clipboard screenshot   → vision_clipboard
```

## More

- [Development](docs/development.md) covers the test commands and the compatibility patch
- [Design](docs/design.md) covers the recognition method, tool exposure, and directory layout
- `SKILL.md` contains the runtime instructions loaded by DSH
- `templates/.env.example` documents standalone script configuration
- The runtime skill name is `vision`. When a skill with the same name is installed at the project or user layer, DSH resolves project, runtime, and user skills by precedence, so install it in one layer only

## License

MIT
