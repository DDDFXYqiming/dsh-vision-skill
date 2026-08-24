[简体中文](README.md) | English

# dsh-plugins / dsh-vision-skill

**DeepSeek Harness (DSH) image-recognition skill plugin** — wraps this repo's `General_skills/vision-skill` (Qwen official dynamic-resolution approach) as a native DSH plugin.

> Zero framework patching: the plugin only uses official extension seams (`ctx.skills.register` / `ctx.tools.register` / `ctx.credentials` / `ctx.sessions` / `ctx.webServer` / client injection). Since v0.4, direct image paste uses paste-to-path — **no pi-ai patch needed**; the old patch is kept only for compatibility, with a restore script.

## Capabilities (8 tools + 1 runtime skill)

| Name | Description |
|---|---|
| `vision` (runtime skill) | Loaded on demand; auto-activates the tools below (progressive exposure) |
| `vision_analyze` | Recognize a local image (6 modes: general / ocr / table / code / error / **structured evidence** + `budget` includes `mega` 16M pixels) |
| `vision_ocr` | Standalone OCR preserving the original layout |
| `vision_ground` | Locate a target (e.g. "WeChat icon"), returns pixel + normalized coordinates |
| `vision_detect` | Enumerate a category of elements, indexed + pixel bounding boxes |
| `vision_dominant_colors` | Dominant-color analysis (local pixel algorithm, no vision API) |
| `vision_long_screenshot_ocr` | Long-screenshot chunked OCR: local tesseract first → VLM fallback → merge |
| `vision_clipboard` | Clipboard-image fallback (manual channel when paste-to-path fails / special cases) |
| `vision_activate` | Progressive-exposure safety net: call once if tools don't appear after the skill loads |

## Engineering highlights

- **Progressive tool exposure**: only 1 lightweight activate tool is registered globally; the full toolset is mounted per Agent after the skill loads (saves context); `progressive: false` falls back to global registration
- **paste-to-path direct paste (since v0.4.2, input box shows 📎 chip)**: client intercepts the pasted image at capture, POSTs to the server on send, lands in `.dsh-vision/pasted/`; the message contains **no** image block, so DSH no longer throws `MODEL_DOES_NOT_SUPPORT_IMAGES`; older hosts without reference capability fall back to inlining a path text
- **Multi-provider failover + 429 backoff**: `visionProviders` array, failover by order; each provider configures `apiUrl/model/apiKey/credential`; 429 honors `Retry-After` for one retry
- **Structured evidence**: `vision_analyze` with `mode=evidence` returns `summary / ocr_full_text / layout (reading order) / semantics (entities+relations) / uncertainty / visual` JSON
- **Local OCR fast path**: long-screenshot chunks run tesseract first (falls back to VLM only when unavailable — saves tokens and time)
- **Image memory cache**: SHA-256 + mode/budget/crop/prompt cache; TTL hits return `cached:true` directly
- **Path sandboxing**: image path must be under the session workspace / DSH attachment dir / `allowedDirs` (realpath check, prevents path traversal)
- **Credential indirection**: config supports `credential: VISION_API_KEY` (DSH credential reference, resolved per call, recommended); also accepts plaintext `apiKey` (legacy, not recommended)

## Core recognition method

Qwen official dynamic-resolution preprocessing (`smart_resize`: pixel budget + patch-grid snap) → any OpenAI-compatible multimodal model (default `MiniMax-M3` with `thinking: disabled`; replaceable). Grounding follows the Qwen official method: VLM outputs 0–1000 normalized bboxes → parse JSON / `<ref><box>` dual formats → map to pixel coordinates.

## Image delivery (three ways)

| Method | What you do | Where it works |
|---|---|---|
| ① Direct path | Send the path text in chat: "recognize `E:\...\xxx.png`" | Everywhere |
| ② Clipboard | Win+Shift+S screenshot → say "看图" → `vision_clipboard` saves to `.dsh-vision/` | Everywhere |
| ③ Direct paste | Since v0.4, pasting an image uploads it to `.dsh-vision/pasted/` and injects a path text into the message; the model then calls `vision_analyze` | ✅ Everywhere, **no pi-ai patch needed** |

The legacy pi-ai adapter (`opencode-go` etc.) image→path patch is kept only for compatibility; after a dsh upgrade, if the old patch reappears, run `scripts/restore_pi_ai_vision_patch.py` to restore.

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

### Method 1: local link (dev / direct install)

```powershell
git clone https://github.com/DDDFXYqiming/dsh-vision-skill.git
cd dsh-vision-skill
# Add to C:\Users\<user>\.dsh\profiles\web\package.json dependencies:
#   "dsh-vision-skill": "link:<absolute path>\dsh-plugins\dsh-vision-skill"
# Then pnpm install in that profile dir.
```

### Method 2: plugin command (recommended; bundle-style install)

```powershell
dsh plugin --profile web add github:DDDFXYqiming/dsh-vision-skill
```

The plugin's bundled `cordis.patch.yml` auto-contributes the `id: vision-skill` entry — **no manual `insert` needed**. Default config is provided by the plugin's built-in Schemastery schema (`apiUrl`=MiniMax / `model`=MiniMax-M3 / `credential`=VISION_API_KEY).

### Configuration (override bundle defaults)

⚠️ **Don't** add another `insert: - id: vision-skill` line in your profile's `cordis.patch.yml` — duplicate id will crash the loader with `duplicate loader entry id`. To customize config, override the entry by id (without `insert:` wrapper):

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

Store the credential in `$DSH_HOME/.credentials.yaml`:

```yaml
VISION_API_KEY: sk-xxxx
```

## Usage examples

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

Per the AGENTS.md red lines, prefer headless self-test after changes. Direct paste is a client/web behavior — needs a web host restart and a hard browser reload to verify.

## Related

- Generic skill source: [General_skills/vision-skill](../../General_skills/vision-skill)
- Name collision: the plugin registers skill `vision` at the `runtime` layer. If a same-name skill is also installed in `$DSH_HOME/skills` (user layer) or `.dsh/skills` (project layer), the official priority `project > runtime > user` may shadow this one — install in only one layer
- Full version history: [CHANGELOG.md](./CHANGELOG.md)
- License: MIT
