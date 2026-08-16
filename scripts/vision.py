# -*- coding: utf-8 -*-
"""
识图脚本：把本地图片交给配置的视觉模型识别，输出文字描述。

用法:
  python vision.py <图片路径> [提示词]
  python vision.py <图片路径> --mode ocr
  python vision.py <图片路径> --crop 10,10,300,200 --budget large
  python vision.py a.png --images b.png c.png --prompt "对比这两张截图"
  python vision.py --check

配置（不硬编码任何模型地址/模型名/密钥）：
  通过环境变量或 .env 提供 VISION_API_URL / VISION_MODEL / VISION_API_KEY，
  模板见 templates/.env.example。

功能：
  --budget small|normal|large   动态分辨率（默认 normal，约 1024×1024）
  --crop x1,y1,x2,y2            先裁局部再识别（坐标相对原图像素）
  --mode general|ocr|table|code|error  专用提示词与参数
  --images p1 p2 ...            附加多张图片，与主图一起发送
  --max-tokens N / --temperature T      覆盖默认值
  --no-resize                   不缩放，原图直发
  --save-crop 路径               把实际发送的（裁切+缩放后）图片存下来
  --check                       自检：配置 / PIL / 接口连通
"""

import argparse
import base64
from datetime import datetime, timezone
import io
import json
import math
import os
import re
import sys
import time
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request


def _load_dotenv():
    """轻量 .env 加载（不引入第三方依赖）。

    查找顺序：<技能根目录>/.env（推荐位置）→ <脚本目录>/.env。
    优先级：真实环境变量 > .env 文件（便于 CI/容器注入覆盖）。
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.path.dirname(script_dir), ".env"),
        os.path.join(script_dir, ".env"),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
        except OSError:
            continue


_load_dotenv()

# ── 配置（环境变量 / .env）──────────────────────────────────────────
VISION_API_URL = os.environ.get("VISION_API_URL", "").strip()
VISION_MODEL = os.environ.get("VISION_MODEL", "").strip()
# [spec-audit 2026-08-14] 思考开关与 HTTP 超时可配置（不同模型部署无需改代码）：
# VISION_THINKING = disabled | adaptive | off（缺省 disabled）；VISION_TIMEOUT 秒（缺省 180）
VISION_THINKING = os.environ.get("VISION_THINKING", "disabled").strip().lower()
VISION_TIMEOUT = float(os.environ.get("VISION_TIMEOUT", "180").strip() or "180")
# [upgrade 2026-08-15] 多 provider failover：插件通过 VISION_PROVIDERS_JSON 传入完整链路
# （数组 [{apiUrl, model, apiKey}]，顺序 = 优先级）。缺失时回退单端点 env。
VISION_PROVIDERS_JSON = os.environ.get("VISION_PROVIDERS_JSON", "").strip()
TESSERACT_BIN = os.environ.get("TESSERACT_BIN", "tesseract").strip() or "tesseract"
TESSERACT_LANGS = os.environ.get("TESSERACT_LANGS", "chi_sim+eng").strip() or "chi_sim+eng"
TESSERACT_TIMEOUT = float(os.environ.get("TESSERACT_TIMEOUT", "120").strip() or "120")

MAX_FILE_BYTES = 10 * 1024 * 1024

# 分辨率预算（像素总数）：small≈512²、normal≈1024²、large≈1448²、mega≈16M
# （mega 对应 Qwen 官方 vl_high_resolution_images 的 16384 visual-token 预算：
#   16384 × TOKEN_SIZE(32)² = 16,777,216 ≈ 4096²，供超高清截图/长文档使用）
BUDGET_PIXELS = {
    "small": 512 * 512,
    "normal": 1024 * 1024,
    "large": 1448 * 1448,
    "mega": 4096 * 4096,
}
MIN_PIXELS = 224 * 224
FACTOR = 28  # 吸附网格（部分 VLM 的 patch grid 惯例，对通用接口无害）

# 模式：专用提示词 + 参数
MODES = {
    "general": {
        "prompt": "请详细描述这张图片的内容，包括其中的文字、报错信息等细节。",
        "max_tokens": 2048,
        "temperature": 1.0,
    },
    "ocr": {
        "prompt": (
            "请对这张图片进行OCR文字识别，提取图片中所有可见的文字内容，"
            "保持原始排版格式。不要概括、不要翻译，原样输出文字。"
        ),
        "max_tokens": 4096,
        "temperature": 0.2,
    },
    "table": {
        "prompt": (
            "这张图片是表格/数据截图。请把表格内容原样转成 Markdown 表格，"
            "保留所有行列与数值，不要省略或估算。"
        ),
        "max_tokens": 4096,
        "temperature": 0.2,
    },
    "code": {
        "prompt": (
            "这张图片是代码/日志/报错截图。请原样转述其中的代码、日志和错误信息，"
            "保留缩进与关键内容，再简要说明问题。"
        ),
        "max_tokens": 4096,
        "temperature": 0.2,
    },
    "error": {
        "prompt": (
            "这张图片是报错/异常截图。请原样转述所有错误文本（包括错误码、堆栈、"
            "文件名），再分析可能的原因。"
        ),
        "max_tokens": 4096,
        "temperature": 0.2,
    },
    # [upgrade 2026-08-15] structured evidence（modlens 风格）：
    # summary + ocr_full_text + layout(阅读顺序) + uncertainty，便于引用证据回答。
    "evidence": {
        "prompt": (
            "Analyze this image and return ONLY a JSON object with this exact shape: "
            '{"summary": "<concise factual description>", '
            '"ocr": {"full_text": "<every visible text verbatim, line by line>"}, '
            '"layout": [{"region": "<region name>", "reading_order": <int>, "text": "<content>"}], '
            '"semantics": {"scene": "<scene>", "entities": [{"name": "<name>", "type": "<type>", "evidence": "<what supports it>"}]}, '
            '"visual": {"dominant_colors": ["#RRGGBB"], "style": "<style>", "notes": ["<note>"]}, '
            '"uncertainty": ["<anything uncertain or illegible>"]}. '
            "No markdown fences, no extra text. Quote text verbatim; never guess."
        ),
        "max_tokens": 4096,
        "temperature": 0.2,
    },
}


def log(msg):
    """调试信息走 stderr，不污染 stdout 的识别结果。"""
    print(msg, file=sys.stderr)


def get_key():
    return os.environ.get("VISION_API_KEY", "").strip()


def mime_for(path):
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")


def smart_resize(height, width, min_pixels, max_pixels, factor=FACTOR):
    """把 (h, w) 缩放进 [min_pixels, max_pixels]，吸附到 factor 的整数倍。"""
    if height * width < min_pixels:
        scale = math.sqrt(min_pixels / (height * width))
        height, width = int(height * scale), int(width * scale)
    if height * width > max_pixels:
        scale = math.sqrt(max_pixels / (height * width))
        height, width = int(height * scale), int(width * scale)
    height = max(factor, round(height / factor) * factor)
    width = max(factor, round(width / factor) * factor)
    return height, width


def encode_image(path, budget, crop=None, no_resize=False, save_path=None):
    """读取 -> 可选裁切 -> 可选动态缩放 -> base64。返回 (b64, mime, info)。"""
    from PIL import Image

    img = Image.open(path)
    orig_w, orig_h = img.size
    info = {"orig": f"{orig_w}x{orig_h}"}

    if crop:
        x1, y1, x2, y2 = crop
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(orig_w, x2), min(orig_h, y2)
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"裁剪区域无效: ({x1},{y1})-({x2},{y2})，图片尺寸 {orig_w}x{orig_h}")
        img = img.crop((x1, y1, x2, y2))
        info["crop"] = f"({x1},{y1})-({x2},{y2})"

    if not no_resize:
        max_pixels = BUDGET_PIXELS.get(budget, BUDGET_PIXELS["normal"])
        if img.width * img.height < MIN_PIXELS or img.width * img.height > max_pixels:
            target_h, target_w = smart_resize(img.height, img.width, MIN_PIXELS, max_pixels)
            if (target_w, target_h) != (img.width, img.height):
                img = img.resize((target_w, target_h), Image.LANCZOS)
            info["resized"] = f"{target_w}x{target_h} (budget={budget})"
        else:
            info["resized"] = f"原尺寸 {img.width}x{img.height}（预算内不缩放）"
    else:
        info["resized"] = "原图直发"

    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA", "PA", "P"):
        fmt, mime, save_kwargs = "PNG", "image/png", {}
    else:
        fmt, mime, save_kwargs = "JPEG", "image/jpeg", {"quality": 90}
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
    img.save(buf, format=fmt, **save_kwargs)

    if save_path:
        img.save(save_path, format=fmt, **save_kwargs)
        info["saved"] = save_path

    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return b64, mime, info


def provider_chain():
    """构造按优先级排序的视觉 provider 链路。

    优先 VISION_PROVIDERS_JSON（插件传入 [{apiUrl, model, apiKey}]）；
    缺失时回退 VISION_API_URL / VISION_MODEL / VISION_API_KEY 单端点。
    """
    chain = []
    raw = os.environ.get("VISION_PROVIDERS_JSON", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    api_url = str(item.get("apiUrl") or item.get("api_url") or "").strip()
                    model = str(item.get("model") or "").strip()
                    api_key = str(item.get("apiKey") or item.get("api_key") or "").strip()
                    if api_url and model:
                        chain.append({"apiUrl": api_url, "model": model, "apiKey": api_key})
        except (TypeError, ValueError) as e:
            log(f"[vision] VISION_PROVIDERS_JSON 解析失败，忽略 fallback 链路: {e}")
    if not chain and VISION_API_URL and VISION_MODEL:
        chain.append({"apiUrl": VISION_API_URL, "model": VISION_MODEL, "apiKey": get_key()})
    return chain


def _retry_after_seconds(resp):
    """读取 Retry-After（秒或 HTTP 日期），封顶 30 秒，避免长时间卡死。"""
    raw = resp.headers.get("Retry-After", "").strip()
    if not raw:
        return 2.0
    if raw.isdigit():
        return max(0.5, min(float(raw), 30.0))
    try:
        from email.utils import parsedate_to_datetime
        delta = (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
        return max(0.5, min(delta, 30.0))
    except Exception:
        return 2.0


def _request_once(provider, content, max_tokens, temperature):
    """向单个 provider 发一次请求；429 时按 Retry-After 退避重试一次。"""
    payload = {
        "model": provider["model"],
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if VISION_THINKING == "off":
        pass
    else:
        payload["thinking"] = {"type": VISION_THINKING if VISION_THINKING in ("disabled", "adaptive") else "disabled"}
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if provider.get("apiKey"):
        headers["Authorization"] = f"Bearer {provider['apiKey']}"
    last_error = None
    for attempt in range(2):
        req = urllib.request.Request(provider["apiUrl"], data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=VISION_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            try:
                msg = data["choices"][0]["message"]
            except (KeyError, IndexError):
                raise RuntimeError(f"视觉模型返回异常: {json.dumps(data, ensure_ascii=False)[:500]}")
            text = msg.get("content")
            if text is None:
                text = msg.get("reasoning_content") or ""
                if not text:
                    raise RuntimeError(f"视觉模型返回异常（无 content）: {json.dumps(data, ensure_ascii=False)[:500]}")
            return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip() or text
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"视觉模型 API {e.code}: {body_text[:500]}")
            if e.code == 429 and attempt == 0:
                wait = _retry_after_seconds(e)
                log(f"[vision] {provider['model']} 429，{wait:.1f}s 后重试")
                time.sleep(wait)
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = RuntimeError(f"视觉模型网络错误: {e}")
            break
    raise last_error or RuntimeError("视觉模型请求失败")


def call_api(key, content, max_tokens, temperature):
    """沿 provider 链路依次尝试；所有 provider 失败后才抛错（failover）。"""
    chain = provider_chain()
    if not chain:
        raise RuntimeError("未配置视觉模型（VISION_PROVIDERS_JSON 或 VISION_API_URL/VISION_MODEL，见 templates/.env.example）")
    last_error = None
    for i, provider in enumerate(chain, 1):
        try:
            return _request_once(provider, content, max_tokens, temperature)
        except Exception as e:
            last_error = e
            log(f"[vision] provider {i}/{len(chain)} ({provider['model']}) 失败 -> {e}")
    raise RuntimeError(f"视觉模型链路全部失败（{len(chain)} 个 provider）: {last_error}") from last_error


# ── grounding 定位（Qwen 官方方法：VLM 输出 bbox → 解析 → 像素坐标）───────────

def norm_to_pixel(bbox, img_w, img_h):
    """把 [0,1000] 归一化 bbox 转成原图像素坐标。"""
    nx1, ny1, nx2, ny2 = bbox
    return [
        round(nx1 / 1000 * img_w),
        round(ny1 / 1000 * img_h),
        round(nx2 / 1000 * img_w),
        round(ny2 / 1000 * img_h),
    ]


def parse_grounding(text, img_w, img_h):
    """解析模型定位输出：JSON 数组优先，<ref>/<box> 标签兜底（Qwen 官方双格式）。

    JSON 格式: [{"label": "...", "bbox_2d": [x1,y1,x2,y2]}]（0-1000 归一化）
    标签格式: <ref>label</ref><box>(x1,y1),(x2,y2)</box>（0-1000 归一化）
    返回 [{"label", "bbox_pixel", "bbox_normalized"}]；解析失败返回 None。
    """
    def to_boxes(item, img_w, img_h):
        label = str(item.get("label") or item.get("name") or item.get("object") or "target")
        bbox = item.get("bbox_2d") or item.get("bbox") or item.get("box") or item.get("bounding_box")
        if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return None
        nums = []
        for v in bbox:
            try:
                nums.append(int(float(v)))
            except (TypeError, ValueError):
                return None
        return {"label": label, "bbox_normalized": nums, "bbox_pixel": norm_to_pixel(nums, img_w, img_h)}

    # 1) JSON 优先（剥掉 markdown 代码围栏）；空数组是合法结果（“没有找到”）
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    raw = m.group(1).strip() if m else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        data = data.get("detections") or data.get("objects") or data.get("results") or []
    if isinstance(data, list):
        results = []
        for item in data:
            if isinstance(item, dict):
                box = to_boxes(item, img_w, img_h)
                if not box:
                    continue
                nums = box["bbox_normalized"]
                # 启发式：模型直接输出像素坐标（非 0-1000 归一化）→ 按像素用并 clamp
                if max(nums) > 1100 or max(nums) > max(img_w, img_h):
                    x1 = max(0, min(nums[0], img_w)); y1 = max(0, min(nums[1], img_h))
                    x2 = max(0, min(nums[2], img_w)); y2 = max(0, min(nums[3], img_h))
                    box["bbox_pixel"] = [x1, y1, x2, y2]
                    box["bbox_normalized"] = [
                        round(x1 / img_w * 1000), round(y1 / img_h * 1000),
                        round(x2 / img_w * 1000), round(y2 / img_h * 1000),
                    ]
                results.append(box)
        # 空数组 = 模型明确说没有 → 返回 [] 而非解析失败
        return results

    # 3) <ref>label</ref><box>(x1,y1),(x2,y2)</box> 标签格式
    ref_re = re.compile(r"<ref>(.*?)</ref>")
    box_re = re.compile(r"<box>\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*,\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)</box>")
    refs = list(ref_re.finditer(text))
    if refs:
        results = []
        for i, ref_match in enumerate(refs):
            label = ref_match.group(1)
            start = ref_match.end()
            end = refs[i + 1].start() if i + 1 < len(refs) else len(text)
            region = text[start:end]
            for box_match in box_re.finditer(region):
                nums = [int(box_match.group(j)) for j in range(1, 5)]
                results.append({"label": label, "bbox_normalized": nums, "bbox_pixel": norm_to_pixel(nums, img_w, img_h)})
        if results:
            return results
    return None


def find_font(size):
    """CJK 优先的字体查找（标注中文标签用），找不到则用默认字体。"""
    from PIL import ImageFont
    if sys.platform == "win32":
        patterns = [
            os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "Fonts", "msyh*.ttc"),
            os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "Fonts", "simhei.ttf"),
            os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "Fonts", "simsun.ttc"),
            os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "Fonts", "arial*.ttf"),
        ]
    else:
        patterns = [
            "/usr/share/fonts/**/Noto*CJK*.ttc",
            "/usr/share/fonts/**/wqy*.ttc",
            "/usr/share/fonts/**/Noto*CJK*.ttf",
            "/usr/share/fonts/**/*DejaVu*Bold*.ttf",
        ]
    import glob
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue
    return ImageFont.load_default()


def draw_boxes(img, detections):
    """在原图副本上画定位框 + 标签，返回标注图（Qwen draw_boxes 同款）。"""
    from PIL import ImageDraw
    annotated = img.copy()
    draw = ImageDraw.Draw(annotated)
    short_edge = min(img.width, img.height)
    line_width = max(2, short_edge // 200)
    font = find_font(max(14, short_edge // 40))
    colors = [
        (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
        (255, 0, 255), (0, 255, 255), (255, 128, 0), (128, 0, 255),
    ]
    for i, det in enumerate(detections):
        color = colors[i % len(colors)]
        x1, y1, x2, y2 = det["bbox_pixel"]
        draw.rectangle([x1, y1, x2, y2], outline=color, width=line_width)
        label = det.get("label") or ""
        if label:
            tb = draw.textbbox((0, 0), label, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            label_y = max(0, y1 - th - 6)
            draw.rectangle([x1, label_y, x1 + tw + 6, label_y + th + 6], fill=color)
            draw.text((x1 + 3, label_y + 2), label, fill=(255, 255, 255), font=font)
    return annotated


GROUND_PROMPT_TMPL = (
    "请定位图片中所有满足「{target}」的目标。"
    "只输出一个 JSON 数组，不要输出任何其他文字或解释。"
    "数组每一项是一个对象，包含两个字段："
    "label（目标的简短中文名称，字符串）和 bbox_2d（整数数组 [x1,y1,x2,y2]，"
    "坐标把图片宽高归一化到 0-1000 范围）。"
    "如果找不到任何目标，输出空数组 []。"
)


def ground(path, target, budget="normal", crop=None, temperature=0.2, max_tokens=2048,
           return_img=False, save_path=None, prompt=None):
    """定位图片中的目标，返回结构化结果（含像素坐标框）。

    与 analyze 同一套核心方法：动态分辨率预处理 + OpenAI 兼容 VLM，
    由模型输出归一化 bbox，解析后映射回原图像素坐标。
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"图片不存在: {path}")
    size = os.path.getsize(path)
    if size > MAX_FILE_BYTES:
        raise ValueError(f"图片超过 {MAX_FILE_BYTES // 1024 // 1024}MB 限制: {path} ({size / 1024 / 1024:.1f}MB)")

    from PIL import Image
    img = Image.open(path)
    orig_w, orig_h = img.size

    b64, mime, info = encode_image(path, budget, crop=crop)
    log(f"[ground] {' | '.join(f'{k}={v}' for k, v in info.items())}")

    if not provider_chain():
        raise RuntimeError("未配置视觉模型（VISION_PROVIDERS_JSON 或 VISION_API_URL/VISION_MODEL，见 templates/.env.example）")
    key = get_key()
    target_prompt = prompt or GROUND_PROMPT_TMPL.format(target=target)
    content = [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        {"type": "text", "text": target_prompt},
    ]
    raw = call_api(key, content, max_tokens, temperature)

    # 归一化坐标基于"发送图"尺寸，但 bbox 数值是模型按 0-1000 输出，
    # 映射目标始终是原图（与 crop 场景一致：crop 后模型看到的是局部图）。
    matches = parse_grounding(raw, orig_w, orig_h)
    if matches is None:
        raise RuntimeError(
            f"grounding 解析失败，模型输出无法识别为 bbox 格式。原始输出: {raw[:300]}"
        )

    result = {
        "target": target,
        "image": {"path": path, "width": orig_w, "height": orig_h, "bytes": size, "format": (img.format or mime)},
        "matches": matches,
        "raw": raw,
    }
    if return_img:
        annotated = draw_boxes(img, matches)
        dest = save_path or f".dsh-vision-ground-{int(time.time())}.png"
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        annotated.save(dest, format="PNG")
        result["annotated_path"] = dest
    return result


# ── detect 枚举（grounding 变体：枚举一类元素，编号输出）────────────────

DETECT_PROMPT_TMPL = (
    "请枚举图片中所有满足「{category}」的元素，逐个给出位置。"
    "只输出一个 JSON 数组，不要输出任何其他文字或解释。"
    "数组每一项是一个对象：{{label: 元素的简短名称（若元素含可见文字请原样包含该文字，字符串）, "
    "bbox_2d: [x1,y1,x2,y2]（把图片宽高归一化到 0-1000 的整数坐标）}}。"
    "如果找不到任何元素，输出空数组 []。"
)


def detect(path, category="所有 UI 元素（按钮、链接、输入框、图标、标签、标题、图片、徽章等）",
           budget="normal", crop=None, temperature=0.2, max_tokens=4096,
           return_img=False, save_path=None, prompt=None):
    """枚举图片中某一类元素（默认所有 UI 元素），编号 + 像素坐标框。

    与 ground 同一套核心方法（动态分辨率 + VLM bbox 解析），提示词改为枚举。
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"图片不存在: {path}")
    size = os.path.getsize(path)
    if size > MAX_FILE_BYTES:
        raise ValueError(f"图片超过 {MAX_FILE_BYTES // 1024 // 1024}MB 限制: {path} ({size / 1024 / 1024:.1f}MB)")

    from PIL import Image
    img = Image.open(path)
    orig_w, orig_h = img.size

    b64, mime, info = encode_image(path, budget, crop=crop)
    log(f"[detect] {' | '.join(f'{k}={v}' for k, v in info.items())}")

    if not provider_chain():
        raise RuntimeError("未配置视觉模型（VISION_PROVIDERS_JSON 或 VISION_API_URL/VISION_MODEL，见 templates/.env.example）")
    key = get_key()
    detect_prompt = prompt or DETECT_PROMPT_TMPL.format(category=category)
    content = [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        {"type": "text", "text": detect_prompt},
    ]
    raw = call_api(key, content, max_tokens, temperature)

    matches = parse_grounding(raw, orig_w, orig_h)
    if matches is None:
        raise RuntimeError(
            f"detect 解析失败，模型输出无法识别为 bbox 格式。原始输出: {raw[:300]}"
        )

    elements = [
        {"index": i + 1, "label": m["label"], "bbox_pixel": m["bbox_pixel"], "bbox_normalized": m["bbox_normalized"]}
        for i, m in enumerate(matches)
    ]
    result = {
        "category": category,
        "image": {"path": path, "width": orig_w, "height": orig_h, "bytes": size, "format": (img.format or mime)},
        "elements": elements,
        "raw": raw,
    }
    if return_img:
        annotated = draw_boxes(img, matches)
        dest = save_path or f".dsh-vision-detect-{int(time.time())}.png"
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        annotated.save(dest, format="PNG")
        result["annotated_path"] = dest
    return result


# ── 主色分析（本地算法，无需视觉 API：降采样 + 中位切分量化 + 近色合并）──

def _parse_region(region, width, height):
    """解析 'x1,y1,x2,y2'（原图像素），越界 clamp，空区域抛错。"""
    try:
        x1, y1, x2, y2 = (int(v) for v in region.replace("，", ",").split(","))
    except (ValueError, AttributeError):
        raise ValueError(f"区域格式应为 x1,y1,x2,y2: {region!r}")
    x1, x2 = sorted((max(0, min(x1, width)), max(0, min(x2, width))))
    y1, y2 = sorted((max(0, min(y1, height)), max(0, min(y2, height))))
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"区域为空: {region}（图片 {width}x{height}）")
    return (x1, y1, x2, y2)


def _chebyshev(a, b):
    return max(abs(a[i] - b[i]) for i in range(3))


def dominant_colors(path, region=None, top=8, quantize_k=16, max_pixels=262144, merge_tol=24):
    """提取图片（或区域）的主要颜色：降采样 → 中位切分量化 → 近色合并 → 占比。

    纯本地算法（PIL），不调用视觉 API。返回 [{color:'#RRGGBB', share_pct}]。
    """
    from PIL import Image
    img = Image.open(path).convert("RGB")
    orig_w, orig_h = img.size

    if region:
        box = _parse_region(region, orig_w, orig_h)
    else:
        box = (0, 0, orig_w, orig_h)
    crop = img.crop(box)

    if crop.width * crop.height > max_pixels:
        scale = math.sqrt(max_pixels / (crop.width * crop.height))
        crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.LANCZOS)

    quantized = crop.quantize(colors=quantize_k, method=Image.MEDIANCUT)
    palette = quantized.getpalette()
    clusters = []
    for count, index in sorted(quantized.getcolors(maxcolors=quantize_k), reverse=True):
        rgb = tuple(palette[index * 3:index * 3 + 3])
        merged = False
        for existing in clusters:
            if _chebyshev(existing[0], rgb) <= merge_tol:
                existing[1] += count
                merged = True
                break
        if not merged:
            clusters.append([rgb, count])
    clusters.sort(key=lambda c: c[1], reverse=True)

    total = sum(c[1] for c in clusters) or 1
    colors = [
        {"color": "#%02X%02X%02X" % c[0], "share_pct": round(c[1] / total * 100, 2)}
        for c in clusters[:top]
    ]
    return {
        "image": {"path": path, "width": orig_w, "height": orig_h, "region": region or "full"},
        "colors": colors,
        "sampled_pixels": crop.width * crop.height,
    }


# ── 结构化证据（modlens 风格 evidence mode）──────────────────────────

def _strip_json_fence(text):
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", t, re.DOTALL)
    return (m.group(1) if m else t).strip()


def normalize_evidence(text):
    """把 VLM 的 evidence JSON 归一化为稳定结构；解析失败则降级为 raw summary。

    返回 {summary, ocr_full_text, layout, semantics, uncertainty, visual, parse_error}。
    """
    def _list(value):
        return value if isinstance(value, list) else []

    def _str(value):
        return str(value).strip() if value is not None else ""

    raw = _strip_json_fence(text)
    try:
        data = json.loads(raw)
        # 部分模型会把完整 evidence JSON 再次包进 summary 字符串，或整体多包一层字符串。
        for _ in range(2):
            if isinstance(data, str):
                data = json.loads(_strip_json_fence(data))
            if isinstance(data, dict) and isinstance(data.get("summary"), str):
                summary_text = data.get("summary", "").strip()
                if summary_text.startswith("{") and ("ocr" in summary_text or "layout" in summary_text):
                    nested = json.loads(_strip_json_fence(summary_text))
                    if isinstance(nested, dict) and ("summary" in nested or "ocr" in nested):
                        data = nested
                        continue
            break
        if not isinstance(data, dict):
            raise ValueError("evidence 不是 JSON object")
        ocr = data.get("ocr") if isinstance(data.get("ocr"), dict) else {}
        layout = []
        for item in _list(data.get("layout")):
            if isinstance(item, dict):
                layout.append({
                    "region": _str(item.get("region")),
                    "reading_order": int(item.get("reading_order") or 0),
                    "text": _str(item.get("text")),
                })
        semantics = data.get("semantics") if isinstance(data.get("semantics"), dict) else {}
        entities = []
        for item in _list(semantics.get("entities")):
            if isinstance(item, dict):
                entities.append({
                    "name": _str(item.get("name")),
                    "type": _str(item.get("type")),
                    "evidence": _str(item.get("evidence")),
                })
        relations = []
        for item in _list(semantics.get("relations")):
            if isinstance(item, dict):
                relations.append({
                    "subject": _str(item.get("subject")),
                    "predicate": _str(item.get("predicate")),
                    "object": _str(item.get("object")),
                })
        uncertainty = [_str(x) for x in _list(data.get("uncertainty")) if _str(x)]
        visual = data.get("visual") if isinstance(data.get("visual"), dict) else {}
        return {
            "summary": _str(data.get("summary")) or _str(text),
            "ocr_full_text": _str(ocr.get("full_text")),
            "layout": layout,
            "semantics": {
                "scene": _str(semantics.get("scene")),
                "entities": entities,
                "relations": relations,
            },
            "uncertainty": uncertainty,
            "visual": {
                "dominant_colors": _list(visual.get("dominant_colors")),
                "style": _str(visual.get("style")),
                "notes": [_str(x) for x in _list(visual.get("notes")) if _str(x)],
            },
            "parse_error": False,
        }
    except Exception as e:
        return {
            "summary": _str(text),
            "ocr_full_text": "",
            "layout": [],
            "semantics": {"scene": "", "entities": [], "relations": []},
            "uncertainty": [f"evidence JSON 解析失败，已保留原文: {e}"],
            "visual": {},
            "parse_error": True,
        }


def plan_chunk_tops(orig_h, target_height, overlap):
    """长截图切块计划：返回每块 top 像素列表（可测试纯函数）。"""
    if overlap < 0 or overlap * 2 >= target_height:
        raise ValueError("overlap 必须 >= 0 且小于 target_height 的一半")
    step = target_height - overlap
    tops = list(range(0, orig_h, step))
    if tops and tops[-1] + target_height < orig_h:
        tops.append(orig_h - target_height)
    return sorted(set(tops))


def evidence_json(paths, prompt, budget="normal", crop=None,
                  temperature=None, max_tokens=None, no_resize=False, save_crop=None):
    """调 evidence 模式并归一化为 JSON 证据对象。"""
    raw = analyze(paths, prompt, mode="evidence", budget=budget, crop=crop,
                  temperature=temperature, max_tokens=max_tokens,
                  no_resize=no_resize, save_crop=save_crop)
    return normalize_evidence(raw)


# ── 本地 tesseract OCR（免费快路径，失败自动回退 VLM）────────────────

class TesseractUnavailable(RuntimeError):
    pass


def tesseract_ocr(img, langs=None):
    """对 PIL Image 运行本地 tesseract；不可用/无输出时抛错由调用方回退。"""
    exe = shutil.which(TESSERACT_BIN)
    if not exe:
        raise TesseractUnavailable(f"未找到 tesseract（{TESSERACT_BIN}）。安装后长截图 OCR 会自动优先本地识别")
    use_langs = (langs or TESSERACT_LANGS).strip()
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="dsh-vision-ocr-")
    os.close(fd)
    try:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(tmp, format="PNG")
        proc = subprocess.run(
            [exe, tmp, "stdout", "-l", use_langs, "--psm", "6"],
            capture_output=True, text=True, timeout=TESSERACT_TIMEOUT, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"tesseract 退出码 {proc.returncode}: {(proc.stderr or '').strip()[:300]}")
        text = (proc.stdout or "").strip()
        if not text:
            raise RuntimeError("tesseract 无输出")
        return text
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"tesseract 超时（{TESSERACT_TIMEOUT}s）") from e
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ── 长截图分块 OCR（切块 + 重叠 + 逐块识别 + 合并）─────────────────

LONG_OCR_PROMPT_TMPL = (
    "这张图片是超长截图（聊天记录/网页）的第 {n} 块（共 {total} 块）。"
    "请提取本块中所有可见的文字内容，保持原始排版顺序，"
    "不要概括、不要翻译、不要遗漏。若本块顶部/底部是上一块/下一块的重叠区域，"
    "重复出现的文字正常输出即可。"
)


def _pil_to_data_url(img, budget="normal"):
    """把 PIL Image 按预算动态缩放后转 data URL（复用核心 smart_resize）。"""
    from PIL import Image
    max_pixels = BUDGET_PIXELS.get(budget, BUDGET_PIXELS["normal"])
    w, h = img.size
    if w * h > max_pixels:
        target_h, target_w = smart_resize(h, w, MIN_PIXELS, max_pixels)
        img = img.resize((target_w, target_h), Image.LANCZOS)
    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA", "PA", "P"):
        fmt, mime = "PNG", "image/png"
        save_img = img
    else:
        fmt, mime = "JPEG", "image/jpeg"
        save_img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
    save_img.save(buf, format=fmt, quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:{mime};base64,{b64}", mime


def long_screenshot_ocr(path, target_height=2000, overlap=100, budget="normal",
                        temperature=0.2, max_tokens=4096, prompt=None,
                        tesseract_first=True, tesseract_langs=None):
    """超长截图分块 OCR：本地 tesseract 优先、VLM 兜底，逐块识别后合并全文。

    返回 {source, chunk_count, chunks:[{index, top, bottom, engine}], text, engines}。
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"图片不存在: {path}")
    from PIL import Image
    img = Image.open(path)
    orig_w, orig_h = img.size
    tops = plan_chunk_tops(orig_h, target_height, overlap)
    if not tops:
        tops = [0]

    chunks = []
    texts = []
    total = len(tops)
    engine_usage = {"tesseract": 0, "vision": 0}
    for i, top in enumerate(tops, 1):
        bottom = min(top + target_height, orig_h)
        chunk_img = img.crop((0, max(0, top), orig_w, bottom))
        engine = "vision"
        raw = None
        if tesseract_first:
            try:
                raw = tesseract_ocr(chunk_img, langs=tesseract_langs)
                engine = "tesseract"
                log(f"[long_ocr] chunk {i}/{total}: rows {top}-{bottom} -> tesseract")
            except Exception as e:
                log(f"[long_ocr] chunk {i}/{total}: tesseract 不可用/失败，回退 VLM（{e}）")
        if raw is None:
            url, _ = _pil_to_data_url(chunk_img, budget)
            chunk_prompt = prompt or LONG_OCR_PROMPT_TMPL.format(n=i, total=total)
            content = [
                {"type": "image_url", "image_url": {"url": url}},
                {"type": "text", "text": chunk_prompt},
            ]
            raw = call_api(get_key(), content, max_tokens, temperature)
        engine_usage[engine] = engine_usage.get(engine, 0) + 1
        texts.append(raw.strip())
        chunks.append({"index": i, "top": max(0, top), "bottom": bottom, "engine": engine})

    merged = "\n\n".join(f"[第 {c['index']} 块，行 {c['top']}-{c['bottom']}]\n{t}" for c, t in zip(chunks, texts))
    return {
        "source": {"path": path, "width": orig_w, "height": orig_h},
        "chunk_count": total,
        "chunks": chunks,
        "text": merged,
        "engines": engine_usage,
    }


def analyze(paths, prompt, mode="general", budget="normal", crop=None,
            temperature=None, max_tokens=None, no_resize=False, save_crop=None):
    if mode not in MODES:
        raise ValueError(f"未知模式: {mode}（可选 {', '.join(MODES)}）")
    cfg = MODES[mode]
    if not prompt:
        prompt = cfg["prompt"]
    if max_tokens is None:
        max_tokens = cfg["max_tokens"]
    if temperature is None:
        temperature = cfg["temperature"]

    if not provider_chain():
        raise RuntimeError("未配置视觉模型（VISION_PROVIDERS_JSON 或 VISION_API_URL/VISION_MODEL，见 templates/.env.example）")
    key = get_key()

    content = []
    for i, p in enumerate(paths):
        if not os.path.isfile(p):
            raise FileNotFoundError(f"图片不存在: {p}")
        size = os.path.getsize(p)
        if size > MAX_FILE_BYTES:
            raise ValueError(f"图片超过 {MAX_FILE_BYTES // 1024 // 1024}MB 限制: {p} ({size / 1024 / 1024:.1f}MB)")
        # 裁切只作用于第一张主图
        cur_crop = crop if i == 0 else None
        b64, mime, info = encode_image(
            p, budget, crop=cur_crop, no_resize=no_resize,
            save_path=save_crop if i == 0 else None,
        )
        log(f"[{p}] {' | '.join(f'{k}={v}' for k, v in info.items())}")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    content.append({"type": "text", "text": prompt})

    return call_api(key, content, max_tokens, temperature)


def check(no_api=False):
    """自检：配置 / PIL / tesseract / provider 链路（可选连通性）。"""
    ok = True
    chain = provider_chain()
    log(f"[check] provider 链路: {len(chain)} 个（" + " -> ".join(p["model"] for p in chain) + "）")
    if not chain:
        ok = False
    log(f"[check] VISION_THINKING: {VISION_THINKING}")
    try:
        import PIL  # noqa: F401
        log(f"[check] PIL: 可用（{PIL.__version__}）")
    except Exception as e:
        log(f"[check] PIL: 不可用（{e}），请 pip install pillow")
        ok = False
    try:
        exe = shutil.which(TESSERACT_BIN)
        log(f"[check] tesseract: {'可用（' + exe + '）' if exe else '不可用（本地 OCR 将回退 VLM）'}")
    except Exception as e:
        log(f"[check] tesseract 检测失败: {e}")
    if not no_api and chain:
        try:
            call_api(
                "",
                [{"type": "text", "text": "回复：OK"}],
                max_tokens=8,
                temperature=0,
            )
            log("[check] API 连通正常（provider 链路可用）")
        except Exception as e:
            log(f"[check] API 调用失败 -> {e}")
            ok = False
    return ok


def _setup_io():
    """统一输出编码，避免 PowerShell 管道/重定向下中文乱码。

    - 交互终端（TTY）：保持 Python 默认；Windows 控制台原生走 Unicode
      （WriteConsoleW），强制 UTF-8 反而可能按代码页误显示。
    - 管道 / 重定向：stdout 与 stderr 都强制 UTF-8，避免 Python 默认按
      GBK 输出后被按 UTF-8 或其他编码误读导致乱码。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="识图（可配置视觉模型）")
    parser.add_argument("image", nargs="?", help="主图片路径")
    parser.add_argument("prompt", nargs="?", help="（可选）提示词，兼容旧用法")
    parser.add_argument("--prompt", dest="prompt_opt", default=None,
                        help="提示词（多图场景请用此选项，避免被 --images 吞掉）")
    parser.add_argument("--images", nargs="+", default=[], help="附加图片路径（与主图一起发送）")
    parser.add_argument("--budget", choices=["small", "normal", "large", "mega"], default="normal",
                        help="分辨率预算（默认 normal≈1024²；mega≈4096² 超高清，对应 Qwen 高分辨率模式）")
    parser.add_argument("--crop", default=None,
                        help="先裁切再识别：x1,y1,x2,y2（原图像素坐标）")
    parser.add_argument("--mode", choices=list(MODES), default="general",
                        help="识别模式（默认 general）")
    parser.add_argument("--ground", default=None,
                        help="定位模式：指定要查找的目标（如“所有按钮”），返回像素坐标框 JSON")
    parser.add_argument("--draw", default=None,
                        help="配合 --ground/--detect 使用：把定位框画到图上并保存到该路径")
    parser.add_argument("--detect", nargs="?", const="所有 UI 元素（按钮、链接、输入框、图标、标签、标题、图片、徽章等）", default=None,
                        help="枚举模式：指定元素类别（如“所有按钮”），编号返回像素坐标框")
    parser.add_argument("--colors", nargs="?", const=8, type=int, default=None,
                        help="主色分析：提取图片主要颜色及占比（本地算法，无需 API；可选 top N）")
    parser.add_argument("--long-ocr", action="store_true",
                        help="长截图分块 OCR：超长截图切块逐块识别后合并全文")
    parser.add_argument("--no-tesseract", action="store_true",
                        help="配合 --long-ocr：禁用本地 tesseract 优先，直接走视觉模型")
    parser.add_argument("--tesseract-langs", default=None,
                        help="tesseract 语言包（默认取 TESSERACT_LANGS，缺省 chi_sim+eng）")
    parser.add_argument("--evidence-json", action="store_true",
                        help="结构化证据模式：返回 summary/ocr_full_text/layout/uncertainty JSON")
    parser.add_argument("--target-height", type=int, default=2000,
                        help="配合 --long-ocr：每块目标高度（像素，默认 2000）")
    parser.add_argument("--overlap", type=int, default=100,
                        help="配合 --long-ocr：相邻块重叠高度（像素，默认 100）")
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--no-resize", action="store_true", help="原图直发，不缩放")
    parser.add_argument("--save-crop", default=None, help="把实际发送的（裁切+缩放后）图片存到该路径")
    parser.add_argument("--check", action="store_true", help="自检配置/PIL/接口")
    parser.add_argument("--no-api", action="store_true", help="配合 --check：跳过接口连通测试")

    args = parser.parse_args(argv)

    _setup_io()
    if args.check:
        sys.exit(0 if check(no_api=args.no_api) else 1)

    if not args.image:
        parser.print_usage()
        print("用法: python vision.py <图片路径> [提示词] [选项]；python vision.py --check 自检", file=sys.stderr)
        sys.exit(2)

    crop = None
    if args.crop:
        parts = [int(v) for v in args.crop.replace("，", ",").split(",")]
        if len(parts) != 4:
            raise SystemExit("--crop 需要 4 个数字: x1,y1,x2,y2")
        crop = tuple(parts)

    if args.colors is not None:
        result = dominant_colors(args.image, region=args.crop, top=args.colors)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)

    if args.long_ocr:
        result = long_screenshot_ocr(
            args.image,
            target_height=args.target_height,
            overlap=args.overlap,
            budget=args.budget,
            temperature=args.temperature or 0.2,
            max_tokens=args.max_tokens or 4096,
            prompt=args.prompt_opt or args.prompt or None,
            tesseract_first=not args.no_tesseract,
            tesseract_langs=args.tesseract_langs,
        )
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)

    if args.detect:
        result = detect(
            args.image,
            category=args.detect,
            budget=args.budget,
            crop=crop,
            temperature=args.temperature or 0.2,
            max_tokens=args.max_tokens or 4096,
            return_img=bool(args.draw),
            save_path=args.draw,
        )
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)

    if args.evidence_json:
        paths = [args.image] + list(args.images)
        prompt = args.prompt_opt if args.prompt_opt is not None else (args.prompt or "")
        result = evidence_json(
            paths,
            prompt,
            budget=args.budget,
            crop=crop,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            no_resize=args.no_resize,
            save_crop=args.save_crop,
        )
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)

    if args.ground:
        result = ground(
            args.image,
            args.ground,
            budget=args.budget,
            crop=crop,
            temperature=args.temperature or 0.2,
            max_tokens=args.max_tokens or 2048,
            return_img=bool(args.draw),
            save_path=args.draw,
        )
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)

    paths = [args.image] + list(args.images)
    prompt = args.prompt_opt if args.prompt_opt is not None else (args.prompt or "")
    try:
        result = analyze(
            paths,
            prompt,
            mode=args.mode,
            budget=args.budget,
            crop=crop,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            no_resize=args.no_resize,
            save_crop=args.save_crop,
        )
        print(result)
    except Exception as e:
        # [spec-audit 2026-08-14] 诊断必须走 stderr：stdout 是结果通道，
        # 错误打到 stdout 会被插件 run() 的 stderr 收集吞掉，只剩 "Command failed" 空壳
        print(f"识图失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
