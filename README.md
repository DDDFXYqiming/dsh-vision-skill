# dsh-plugins / dsh-vision-skill

`dsh-vision-skill` packages the `General_skills/vision-skill` image workflow as a native DeepSeek Harness plugin. It uses DSH extension points for runtime skills, tools, credentials, sessions, the web server, and client injection.

Since v0.4, pasted images are uploaded by the client to a workspace path before the message is sent. The model receives a path and calls the plugin. The older `pi-ai` image-to-path patch remains available for compatibility.

## Tools

| Name | Purpose |
|---|---|
| `vision` | Runtime skill that exposes the image tools on demand |
| `vision_analyze` | Analyze a local image in general, OCR, table, code, error, or evidence mode |
| `vision_ocr` | Extract visible text while preserving its layout |
| `vision_ground` | Locate a named target and return pixel and normalized boxes |
| `vision_detect` | Enumerate elements such as UI controls with numbered boxes |
| `vision_dominant_colors` | Calculate dominant colors locally without a vision API |
| `vision_long_screenshot_ocr` | OCR a long screenshot in overlapping chunks, using local Tesseract before a VLM fallback |
| `vision_clipboard` | Save a clipboard image to the workspace for recognition |
| `vision_activate` | Explicitly expose the tool set when automatic skill activation is unavailable |

`vision_analyze` evidence mode returns `summary`, `ocr_full_text`, reading-order `layout`, semantic `entities` and `relations`, `uncertainty`, and `visual` fields. Results can be cached by image SHA-256, mode, budget, crop, and prompt. The cache has configurable TTL and entry limits.

## Request flow

The image script applies Qwen's dynamic-resolution preprocessing and sends the result to an OpenAI-compatible multimodal endpoint. Grounding accepts either JSON or `<ref><box>` output and converts the model's 0 to 1000 coordinates to pixels. Long screenshots run local `tesseract` first, then use the configured VLM when Tesseract is unavailable.

The plugin accepts a local image path as text. Direct paths work in every environment. A Windows screenshot can be saved from the clipboard with `vision_clipboard`. In v0.4, pasting into the DSH input uploads the image to `.dsh-vision/pasted/` and inserts a path reference into the message. The message therefore contains text rather than an image block, so text-only DSH adapters can still call the vision tools.

## Installation

For a normal profile installation:

```powershell
dsh plugin --profile web add github:DDDFXYqiming/dsh-vision-skill
```

For local development, add a link to the web profile and run `pnpm install` there:

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
| `dsh-llm-deepseek` | Works without a patch | Recent DSH versions include image-to-path conversion. |
| `dsh-llm-pi-ai` | Works through v0.4 paste-to-path | The older vendor patch is retained for installations that still use the original attachment path. |
| Native multimodal model | Image is sent directly | The model handles the image without conversion. |

The compatibility patch is optional and machine-specific. After a DSH upgrade, rerun it only when the old attachment behavior is required, then restart the host.

```powershell
powershell -File scripts\reapply-pi-ai-vision-patch.ps1
```

The patch edits the vendor `dsh-llm-pi-ai` package and contains a local profile path. Change that path before using it on another machine. It is excluded from the package file list.

## Tests and dependencies

```bash
npm run check
python -m unittest discover -s tests -v
python scripts/vision.py --check --no-api
```

The plugin needs Node.js with DSH (`@deepseek-ai/dsh-tools`, `@deepseek-ai/dsh-credentials`, and `@deepseek-ai/schemastery`), Python 3 with Pillow, Tesseract for the local OCR fast path, and a credential for the chosen OpenAI-compatible vision model.

## Examples

```text
识别这张图 <路径>        → vision_analyze
OCR 这张图 <路径>        → vision_ocr
找到图中的 <目标>        → vision_ground
清点图里的按钮          → vision_detect
分析图片主色            → vision_dominant_colors
提取长截图文字          → vision_long_screenshot_ocr
识别剪贴板截图          → vision_clipboard
```

All image tools receive a path, not the image bytes. The path must resolve inside the session workspace, the DSH attachment directory, or a configured `allowedDirs` entry.

## Related

- `SKILL.md` contains the runtime instructions loaded by DSH.
- `templates/.env.example` documents standalone script configuration.
- `General_skills/vision-skill` contains the shared image workflow.
- The runtime skill name is `vision`. Avoid installing another `vision` skill in a project or user scope, because DSH resolves project, runtime, and user skills by precedence.

## License

MIT
