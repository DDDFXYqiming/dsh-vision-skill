[简体中文](README.md) | English

# dsh-plugins / dsh-vision-skill

**DeepSeek Harness (DSH) image-recognition skill plugin.** It wraps this repo's `General_skills/vision-skill` (Qwen official dynamic-resolution approach) as a native DSH plugin, so a text-only model that cannot take images can still look at pictures, run OCR, and locate targets.

> Zero framework patching. The plugin only uses official extension seams (`ctx.skills.register` / `ctx.tools.register` / `ctx.credentials` / `ctx.sessions` / `ctx.webServer` / client injection). Since v0.4, direct image paste goes through paste-to-path, so no pi-ai patch is needed. The old patch is kept only for compatibility, with a restore script.

## Capabilities (8 tools + 1 runtime skill)

| Name | Description |
|---|---|
| `vision` (runtime skill) | Recognition instructions the model loads on demand. Loading it auto-activates the tools below (progressive exposure) |
| `vision_analyze` | Recognize a local image, 6 modes (general / ocr / table / code / error / **structured evidence**), with a `mega` budget of 16M pixels in `budget` |
| `vision_ocr` | Standalone OCR that preserves the original layout |
| `vision_ground` | Locate a target (e.g. "WeChat icon"), returns pixel and normalized coordinates |
| `vision_detect` | Enumerate a category of elements, indexed with pixel bounding boxes |
| `vision_dominant_colors` | Dominant-color analysis (local pixel algorithm, no vision API) |
| `vision_long_screenshot_ocr` | Chunked OCR for long screenshots. Local tesseract runs first, VLM takes over as fallback, results get merged |
| `vision_clipboard` | Clipboard-image fallback (the manual channel for when paste-to-path fails or for special cases) |
| `vision_activate` | The progressive-exposure safety net. Call once if tools don't appear after the skill loads |

## Engineering highlights

- **Progressive tool exposure**. Only 1 lightweight activate tool is registered globally. The full toolset is mounted per Agent after the skill loads, which saves context. `progressive: false` falls back to global registration.
- **paste-to-path direct paste (since v0.4.2 the input box shows a 📎 chip)**. The client intercepts the pasted image at capture time and POSTs it to the server on send, landing in `.dsh-vision/pasted/`. The message contains no image block, so DSH no longer throws `MODEL_DOES_NOT_SUPPORT_IMAGES`. On older hosts without the reference capability, it falls back to inlining a path text.
- **Multi-provider failover and 429 backoff**. The `visionProviders` array fails over in order, and each provider configures `apiUrl/model/apiKey/credential`. On a 429 the plugin backs off per `Retry-After` and retries once.
- **Structured evidence**. `vision_analyze` with `mode=evidence` returns a JSON object containing `summary / ocr_full_text / layout (reading order) / semantics (entities+relations) / uncertainty / visual`.
- **Local OCR fast path**. Each long-screenshot chunk runs tesseract first. VLM is called only when tesseract is unavailable, which saves tokens and time.
- **Image memory cache**. Cached by image SHA-256 plus mode/budget/crop/prompt. A hit within the TTL returns `cached:true` directly.
- **Path sandboxing**. The image path must sit under the session workspace, the DSH attachment dir, or one of `allowedDirs`, verified with a realpath check to prevent path traversal.
- **Credential indirection**. The config accepts `credential: VISION_API_KEY` (a DSH credential reference, resolved per call, recommended), and also accepts plaintext `apiKey` (legacy, not recommended).

## Core recognition method

Qwen's official dynamic-resolution preprocessing comes first. `smart_resize` handles the pixel budget and patch-grid snapping, then any OpenAI-compatible multimodal model takes over. The default is MiniMax-M3 with `thinking: disabled`; it is replaceable. Grounding follows the Qwen official method. The VLM outputs 0-1000 normalized bboxes, the plugin parses both JSON and `<ref><box>` formats, and the boxes are mapped back to pixel coordinates.

## Image delivery (three ways)

| Method | What you do | Where it works |
|---|---|---|
| ① Direct path | Type “recognize `E:\...\xxx.png`” in chat | Everywhere |
| ② Clipboard | Screenshot with Win+Shift+S, say “看图”, and `vision_clipboard` saves it to `.dsh-vision/` in the workspace | Everywhere |
| ③ Direct paste | Built in since v0.4. A pasted image is uploaded to `.dsh-vision/pasted/`, a path text enters the message, and the model calls `vision_analyze` | ✅ Everywhere, **no pi-ai patch needed** |

The legacy pi-ai adapter (`opencode-go` etc.) image→path patch is kept only for compatibility. After a dsh upgrade, if the old patch reappears, run `scripts/restore_pi_ai_vision_patch.py` to restore.

## Directory layout

```
dsh-vision-skill/
├── lib/index.js          # plugin main (skill registration + 8 tools + progressive exposure + sandbox)
├── scripts/vision.py     # recognition script (dynamic resolution / OCR / grounding / dominant colors / long-screenshot)
├── scripts/reapply-pi-ai-vision-patch.ps1  # pi-ai patch (kept for compatibility)
├── SKILL.md              # runtime skill content (loaded on demand)
├── package.json          # plugin manifest
└── templates/.env.example # config template for standalone script execution
```

## Install

### Method 1, local link (dev / direct install)

```powershell
git clone https://github.com/DDDFXYqiming/dsh-vision-skill.git
cd dsh-vision-skill
# Add to C:\Users\<user>\.dsh\profiles\web\package.json dependencies:
#   "dsh-vision-skill": "link:<absolute path>\dsh-plugins\dsh-vision-skill"
# Then pnpm install in that profile dir.
```

### Method 2, plugin command (recommended; bundle-style install)

```powershell
dsh plugin --profile web add github:DDDFXYqiming/dsh-vision-skill
```

The plugin's bundled `cordis.patch.yml` auto-contributes the `id: vision-skill` entry, so no manual `insert` is needed. Default config comes from the plugin's built-in Schemastery schema (`apiUrl`=MiniMax / `model`=MiniMax-M3 / `credential`=VISION_API_KEY).

### Configuration (override bundle defaults)

Adding another insert entry with the same `id: vision-skill` in your profile's `cordis.patch.yml` will break things. The duplicate id trips `duplicate loader entry id`, and the host crashes at startup. To customize config, override the entry by id (a bare entry, without the `insert:` wrapper).

```yaml
# profile cordis.patch.yml — bare entry overrides the bundle row (patch replaces the whole config, not deep-merge)
- id: vision-skill
  config:
    apiUrl: '<your multimodal OpenAI-compatible endpoint>'   # e.g. https://api.minimaxi.com/v1/chat/completions
    model: '<model name>'                                    # e.g. MiniMax-M3 / qwen-vl-plus / gemini-2.5-flash
    credential: 'VISION_API_KEY'   # recommended: DSH credential reference
    # apiKey: '<plaintext key>'   # legacy (not recommended)
    visionProviders:               # order = failover priority (429/5xx/network errors auto-fall-through)
      - apiUrl: 'https://api.minimaxi.com/v1/chat/completions'
        model: MiniMax-M3
        credential: VISION_API_KEY
      - apiUrl: '<third OpenAI-compatible endpoint>'
        model: '<model>'
        apiKey: '<or plaintext key>'
    tesseract: tesseract
    tesseractLangs: chi_sim+eng
    pasteMaxBytes: 10485760
    cache: true
    cacheTtlSeconds: 3600
    cacheMaxEntries: 200
    timeoutMs: 180000
    concurrency: 2
```

Store the credential in `$DSH_HOME/.credentials.yaml`.

```yaml
VISION_API_KEY: sk-xxxx
```

## Usage examples

Plain natural-language requests in chat are enough. Each one gets routed to the matching tool.

```
recognize this image <path>     → vision_analyze
OCR this image <path>           → vision_ocr
find <target> in this image     → vision_ground (returns pixel bbox)
list all buttons in this image  → vision_detect
what's the dominant color       → vision_dominant_colors (local, no API)
extract text from a long chat   → vision_long_screenshot_ocr
view (clipboard screenshot)     → vision_clipboard
```

## Test & self-check

```bash
python -m unittest discover -s tests -v   # 16 pure-function / fallback-chain tests
npm run check                             # syntax + no-API self-check
python scripts/vision.py --check --no-api # provider chain + PIL + tesseract self-check
```

Per the AGENTS.md red lines, prefer headless self-test after changes. Direct paste is a client/web behavior, so verifying it takes a web host restart plus a hard browser reload.

## Related

- Generic skill source lives at [General_skills/vision-skill](../../General_skills/vision-skill)
- Name collisions. The plugin registers skill `vision` at the `runtime` layer. If a same-name skill is also installed in `$DSH_HOME/skills` (user layer) or `.dsh/skills` (project layer), the official priority `project > runtime > user` may shadow this one, so install in only one layer
- Licensed under MIT
