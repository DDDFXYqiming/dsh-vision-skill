[简体中文](README.md) | English

# dsh-plugins / dsh-vision-skill

**Vision skill packaged as a standard DeepSeek Harness (DSH) plugin** — wraps this repo's `General_skills/vision-skill` (derived from Qwen's official dynamic-resolution method) as a native DSH plugin.

> Zero framework patches: the plugin itself only uses the official extension seams (`ctx.skills.register` / `ctx.tools.register` / `ctx.credentials` / `ctx.sessions` / `ctx.webServer` / client injection), so it can ride along with DSH version upgrades. **As of v0.4, direct image pasting goes through paste-to-path — the pi-ai patch is no longer needed**; the old patch is kept only for compatibility and ships with a restore script.

## Capabilities at a Glance (8 tools + 1 runtime skill)

| Name | Description |
|---|---|
| `vision` (runtime skill) | Vision instructions loaded on demand by the model; once loaded, the tools below are activated automatically (progressive exposure) |
| `vision_analyze` | Analyze a local image (6 modes: general/ocr/table/code/error/**evidence structured evidence** + `budget` including `mega` ultra-HD 16M pixels) |
| `vision_ocr` | Standalone OCR: extract all visible text while preserving the original layout |
| `vision_ground` | Locate a target (e.g. "WeChat icon"), returning pixel-coordinate boxes + normalized coordinates |
| `vision_detect` | Enumerate a class of elements (all UI elements by default), numbered with pixel-coordinate boxes |
| `vision_dominant_colors` | Dominant-color analysis (local pixel algorithm, no vision API needed) |
| `vision_long_screenshot_ocr` | Chunked OCR for extra-long screenshots: split into overlapping chunks → **local tesseract first** → VLM fallback → merge full text |
| `vision_clipboard` | Clipboard-image fallback recognition (manual channel for paste-to-path failures / special cases) |
| `vision_activate` | Progressive-exposure fallback: call once if tools did not appear automatically after the skill loaded |

## Engineering Features

- **Progressive tool exposure**: only 1 lightweight activation tool is registered globally; the full tool set is mounted per Agent after the skill loads successfully (saves context). Set `progressive: false` to fall back to global registration.
- **paste-to-path direct pasting (input box shows a 📎 chip since v0.4.2)**: the client plugin intercepts pasted images during the capture phase and inserts an image chip via `input.insertReference`; on send, `codec.serialize` POSTs the image same-origin to `/dsh-vision-skill/paste`, writes it to the workspace `.dsh-vision/pasted/`, and hands the path text to the model. The message contains no image block, so DSH no longer reports `MODEL_DOES_NOT_SUPPORT_IMAGES`; on older clients without reference support it automatically falls back to inserting the path text directly.
- **Multi-provider failover + 429 backoff**: the `visionProviders` array fails over in order; each provider can configure `apiUrl/model/apiKey/credential`; 429 responses back off per `Retry-After` and retry once.
- **Structured evidence**: `vision_analyze` with `mode=evidence` returns `summary / ocr_full_text / layout (reading order) / semantics (entities/relations) / uncertainty / visual` JSON.
- **Local OCR fast path**: long-screenshot OCR runs tesseract on each chunk first (`tesseract` / `tesseractLangs` configurable); the VLM is only called when tesseract is unavailable — cheaper in tokens and faster.
- **Image-memory cache**: `vision_analyze` results are cached by image-content SHA-256 + mode/budget/crop/prompt (`cache` / `cacheTtlSeconds` / `cacheMaxEntries`); hits within the TTL return `cached:true` directly without re-burning the vision API.
- **Credentials for secrets**: config supports `credential: VISION_API_KEY` (a DSH Credential reference, resolved per operation — recommended) or `apiKey` (legacy compatibility; plaintext not recommended).
- **Path fencing**: image paths must reside in the session workspace, the DSH attachments directory, or one of `allowedDirs` (realpath validation, preventing traversal).
- **Timeout & concurrency gating**: `timeoutMs` (default 180s) and `concurrency` (default 2) are configurable.
- **Structured output**: all tools return results conforming to a strict JSON Schema definition.
- **Tests & self-check**: `python -m unittest discover -s tests` (16 pure-function/fallback-chain tests); `python scripts/vision.py --check --no-api` checks the provider chain, PIL, and tesseract.

## Core Vision Method

Qwen's official dynamic-resolution preprocessing (`smart_resize`: pixel budget + patch-grid snapping) → **any OpenAI-compatible multimodal model** (default MiniMax-M3, with `thinking: disabled` to turn off reasoning; replaceable). Grounding follows Qwen's official method: the VLM outputs 0-1000 normalized bboxes → parse both JSON / `<ref><box>` formats → map to pixel coordinates.

## Directory Structure

```
dsh-vision-skill/
├── lib/index.js          # Plugin main body (skill registration + 8 tools + progressive exposure + fencing)
├── scripts/vision.py     # Vision script (dynamic resolution / OCR / grounding / dominant colors / long-image chunking)
├── scripts/reapply-pi-ai-vision-patch.ps1  # pi-ai adapter "image→path" idempotent patch script (re-run after dsh upgrades)
├── SKILL.md              # Runtime skill content (loaded on demand by the model)
├── package.json          # Plugin package manifest (peerDependencies: dsh-tools / dsh-credentials / schemastery)
└── templates/.env.example # Config template for running the script standalone
```

## Installation

### Method 1: Local link (development / direct install, recommended)

```powershell
# 1. Clone the repo (or use an existing copy)
git clone https://github.com/DDDFXYqiming/dsh-vision-skill.git
cd dsh-vision-skill

# 2. (Optional) Local dev dependencies: peer packages ship with DSH (dsh-base provides @deepseek-ai/dsh-tools etc.),
#    so no separate install in the plugin directory is needed; if running the script standalone you need types/tools, temporarily add:
#    pnpm add -D "@deepseek-ai/dsh-tools@rc" "@deepseek-ai/dsh-credentials@rc"

# 3. Register with the web profile (link mode; source changes take effect immediately)
#    Add to the dependencies of C:\Users\<user>\.dsh\profiles\web\package.json:
#    "dsh-vision-skill": "link:<absolute path>\dsh-plugins\dsh-vision-skill"
#    Then run pnpm install in that directory
```

### Method 2: Plugin command (recommended, standard bundle install)

```powershell
dsh plugin --profile web add github:DDDFXYqiming/dsh-vision-skill
```

After installation, the `cordis.patch.yml` bundled with the plugin package automatically contributes an `id: vision-skill` entry (into the profile's bundles list) — **no manual insert needed**. Config defaults are provided by the plugin's built-in Schemastery Config schema (`apiUrl`=MiniMax / `model`=MiniMax-M3 / `credential`=VISION_API_KEY).

### Configuration (overriding bundle defaults)

⚠️ **Important**: after a bundle install, do **not** also `insert` an `id: vision-skill` entry in the profile's `cordis.patch.yml` — a duplicate id causes a `duplicate loader entry id` startup crash. To customize the config, use a **bare entry to override by id** (without the `insert:` wrapper):

```yaml
# profile cordis.patch.yml —— bare entry overrides the bundle line (last writer wins; the config line is replaced wholesale)
- id: vision-skill
  config:
    apiUrl: '<your multimodal model OpenAI-compatible endpoint>'  # e.g. https://api.minimaxi.com/v1/chat/completions
    model: '<model name>'                                # e.g. MiniMax-M3 / qwen-vl-plus / gemini-2.5-flash
    credential: 'VISION_API_KEY'   # Recommended: DSH Credential reference
    # apiKey: '<plaintext key>'         # Legacy compatibility (not recommended)
```

When overriding, can you write only the fields you want to change? — **No**: the patch replaces the **entire** config of the target line (no deep merge), so an override must also restate the default fields you want to keep (e.g. the full apiUrl/model/credential set above). You may also skip overriding entirely and use the built-in defaults (MiniMax-M3 + the VISION_API_KEY credential reference); in that case the profile needs no vision-skill line at all.

Example fallback chain (order = priority; 429/5xx/network errors switch to the next automatically):

```yaml
- id: vision-skill
  config:
    apiUrl: '<primary provider>'
    model: '<primary model>'
    credential: VISION_API_KEY
    visionProviders:
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
```

Store the credential value in `$DSH_HOME/.credentials.yaml`:

```yaml
VISION_API_KEY: sk-xxxx
```

The patch layer supports hot reload (no restart needed); **after modifying plugin source (lib/index.js), the host must be restarted**.

## Testing & Verification

```bash
# Pure-function / fallback-chain tests (16 items)
python -m unittest discover -s tests -v

# Syntax & self-check (no API calls)
npm run check
python scripts/vision.py --check --no-api
```

After making changes, prefer headless self-testing per the AGENTS.md red lines; direct image pasting is client/Web behavior, so verify by restarting the web host and hard-refreshing the browser.

## Dependencies

- Node.js + DSH (`@deepseek-ai/dsh-tools`, `@deepseek-ai/dsh-credentials`, `@deepseek-ai/schemastery`)
- Python 3 + Pillow (`pip install pillow`; `vision.py --check` self-check)
- Vision model API key (**any OpenAI-compatible multimodal model**: Qwen-VL / MiniMax-M3 / Gemini / GPT-4o etc.; default MiniMax-M3)

## How Images Are Fed to the Plugin (three ways)

All of the plugin's tools accept only a **local image path (text)**, not the image itself. Three ways to feed an image:

| Method | Operation | Applicable environments |
|---|---|---|
| ① Send the path directly | The image is already local (or copy it into the workspace); send path text in the chat: "recognize this image `E:\...\xxx.png`" | **All environments** |
| ② Clipboard | Win+Shift+S screenshot (image lands on the clipboard) → say "look at the image" in chat; `vision_clipboard` saves it to the workspace `.dsh-vision/` and recognizes it | **All environments** |
| ③ Direct paste | Built in since v0.4: paste in the input box → same-origin upload to `.dsh-vision/pasted/` → path text enters the message → model calls `vision_analyze`; **no pi-ai patch needed** | ✅ All environments |

## Image Delivery Mechanism & Adapter Support Matrix

**How it works (v0.4 paste-to-path)**: when an image is pasted, the client plugin intercepts the bytes during the capture phase and POSTs them to `/dsh-vision-skill/paste`; the image is written to the session workspace `.dsh-vision/pasted/`, and the input box only inserts `[pasted image available at absolute path: "..."]` text. The message contains no image block, so DSH's `MODEL_DOES_NOT_SUPPORT_IMAGES` admission check is never triggered. The model receives the path and calls `vision_analyze`. Vision capability comes from this plugin (an independent multimodal API); the main model only needs to read path text and call tools.

| Adapter / scenario | Direct paste (method ③) | Notes |
|---|---|---|
| `dsh-llm-deepseek` (deepseek-official) | ✅ Works out of the box | Recent DSH versions have image→path conversion **natively built in** (derived from vision-skill patch v2, adopted upstream) |
| `dsh-llm-pi-ai` (opencode-go / custom OpenAI-compatible provider) | ✅ No patch needed since v0.4 | paste-to-path converts images to path text before they reach the adapter; the old image→path patch is kept only for compatibility |
| Multimodal models (`input` contains image) | ✅ Image passes through | No conversion needed (the model sees images natively) |

**Zero-patch note (v0.4)**: paste-to-path means image blocks no longer appear in messages, so the pi-ai adapter never triggers `UNSUPPORTED_CONTENT`. This upgrade has already been reverted; the zen-ua patch is kept. If a DSH upgrade re-applies the old patch, run `python scripts\restore_pi_ai_vision_patch.py` (or `powershell -File scripts\restore-pi-ai-vision-patch.ps1`) to restore.

### pi-ai adapter patch (opencode-go etc.; compatibility only since v0.4)

v0.4's paste-to-path means direct pasting no longer needs the pi-ai patch. Use the old patch only if you want to keep the old behavior of "the image first enters the official attachment pipeline and the adapter converts it to a path":

```powershell
# Run once after upgrading/reinstalling dsh via npm (idempotent: already-patched is skipped automatically)
powershell -File scripts\reapply-pi-ai-vision-patch.ps1
# Then restart the DSH host for it to take effect
```

- Patch contents: two patches to `dsh-llm-pi-ai/lib/index.js` — `zen-ua` (OpenCode Zen's free tier only accepts the `opencode/<ver>` User-Agent) + `image→path` (converts images to path placeholders, in exactly the same format as the official `dsh-llm-deepseek`, keeping the vision workflow's format consistent)
- ⚠️ **This script is a machine-level maintenance tool for the author's machine** (hardcoded local `.dsh/profiles` paths; it modifies vendor packages inside node_modules), and **has been excluded from the files whitelist when distributing the package**; on other machines you must first modify the `$piAi` path at the top of the script
- **The script must be re-run after dsh upgrades** (node_modules gets overwritten); after modifying `lib/index.js`, restart the host
- The patch only affects the pi-ai adapter's text-only models (`input` without image); genuinely multimodal models are unaffected

## Usage Examples

```
Recognize this image <path>              → vision_analyze
OCR this image <path>                    → vision_ocr
Find <target> in this image              → vision_ground (returns pixel-coordinate box)
List all buttons in this image           → vision_detect
What are the dominant colors of this image → vision_dominant_colors (local algorithm, no API cost)
Extract the text of this long chat log   → vision_long_screenshot_ocr
Look at the image (clipboard screenshot) → vision_clipboard
```

## Related

- Running the script standalone: see `templates/.env.example`; `python scripts/vision.py <image> --check`
- General-skill source: [General_skills/vision-skill](../../General_skills/vision-skill)
- ⚠️ **Same-name skill conflict**: this plugin registers the skill name `vision` at the `runtime` layer; if a skill with the same name is also installed in `$DSH_HOME/skills` (user layer) or the project's `.dsh/skills` (project layer), they may shadow each other per the official precedence project > runtime > user — install only one of the two
- License: MIT
