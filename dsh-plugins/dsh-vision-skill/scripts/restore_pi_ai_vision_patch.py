#!/usr/bin/env python3
"""Idempotently restore the pi-ai image->path patch (part B) applied by
reapply-pi-ai-vision-patch.ps1. The zen-ua patch (part A) is preserved.

Run after dsh upgrades or when paste-to-path has replaced the old adapter patch:
    python scripts/restore_pi_ai_vision_patch.py
Restarting the dsh web host afterwards is a user decision (see AGENTS.md).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def default_target() -> Path:
    home = os.environ.get("DSH_HOME")
    if home:
        base = Path(home)
    elif os.environ.get("USERPROFILE"):
        base = Path(os.environ["USERPROFILE"]) / ".dsh"
    else:
        base = Path.home() / ".dsh"
    return base / "profiles" / "node_modules" / "@deepseek-ai" / "dsh-llm-pi-ai" / "lib" / "index.js"


def restore(target: Path) -> bool:
    text = target.read_text(encoding="utf-8-sig")
    if "[vision-skill patch 2026-08-14]" not in text and "textOnlyImages" not in text:
        print("skip: vision placeholder patch already absent")
        return False

    # 1) import line
    text = text.replace(
        'import { launchEnvironmentOf } from "@deepseek-ai/dsh-launch-environment";\n'
        'import { homedir } from "node:os";\n'
        'import { join } from "node:path";\n',
        'import { launchEnvironmentOf } from "@deepseek-ai/dsh-launch-environment";\n',
    )

    # 2) generate() image gate
    start = text.index("const containsImage = options.messages.some((message) => contentHasImage(message.content));")
    end = text.index("const iterator = toStreamChunks(snapshot.models.streamSimple(model, context, {", start)
    old_gen = (
        "\t\t\t\tconst containsImage = options.messages.some((message) => contentHasImage(message.content));\n"
        "\t\t\t\tif (containsImage && !model.input.includes(\"image\")) throw new LlmError(`pi-ai model \"${model.id}\" does not support image input`, \"UNSUPPORTED_CONTENT\");\n"
        "\t\t\t\tconst attachments = containsImage ? this.config.resolveAttachments?.() : void 0;\n"
        "\t\t\t\tif (containsImage && attachments === void 0) throw new LlmError(\"pi-ai image input requires the durable attachment service\", \"UNSUPPORTED_CONTENT\");\n"
        "\t\t\t\tconst context = attachments === void 0 ? toPiContext(options) : await toPiContext(options, attachments);\n"
    )
    text = text[:start] + old_gen + text[end:]

    # 3) userContent image branch: drop the textOnlyImages branch
    img_start = text.index("\t\tcase \"image\": {")
    stored_idx = text.index("\t\t\tconst stored = await attachments.readImage(block.attachment);", img_start)
    after_stored = text[stored_idx + len("\t\t\tconst stored = await attachments.readImage(block.attachment);"):]
    text = text[:img_start] + "\t\tcase \"image\": {\n\t\t\tconst stored = await attachments.readImage(block.attachment);" + after_stored

    text = text.replace(
        "async function userContent(blocks, attachments, textOnlyImages) {",
        "async function userContent(blocks, attachments) {",
    )
    text = text.replace(
        "const nested = await userContent(block.content, attachments, textOnlyImages);",
        "const nested = await userContent(block.content, attachments);",
    )

    # 4) toPiContext signatures and call sites
    text = text.replace(
        "function toPiContext(options, attachments, textOnlyImages) {\n"
        "\treturn attachments === void 0 ? textOnlyContext(options) : toPiContextWithImages(options, attachments, textOnlyImages);\n"
        "}\n"
        "async function toPiContextWithImages(options, attachments, textOnlyImages) {",
        "function toPiContext(options, attachments) {\n"
        "\treturn attachments === void 0 ? textOnlyContext(options) : toPiContextWithImages(options, attachments);\n"
        "}\n"
        "async function toPiContextWithImages(options, attachments) {",
    )
    text = text.replace(
        "const content = await userContent(message.content.filter((block) => block.type !== \"tool-result\"), attachments, textOnlyImages);",
        "const content = await userContent(message.content.filter((block) => block.type !== \"tool-result\"), attachments);",
    )
    text = text.replace(
        "const resultContent = await userContent(result.content, attachments, textOnlyImages);",
        "const resultContent = await userContent(result.content, attachments);",
    )

    if "[vision-skill patch 2026-08-14]" in text or "textOnlyImages" in text or "请用 vision skill 读取" in text:
        raise SystemExit("verify FAIL: vision placeholder patch still present")
    if "[zen-ua patch 2026-08-14]" not in text:
        raise SystemExit("verify FAIL: zen-ua patch unexpectedly missing")

    backup = target.with_name(target.name + ".bak-restore-vision-" + "20260815")
    if not backup.exists():
        shutil.copy2(target, backup)
    target.write_text("\ufeff" + text, encoding="utf-8")
    return True


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default_target()
    if not target.is_file():
        raise SystemExit(f"FAIL: file not found: {target}")
    changed = restore(target)
    print("verify OK: vision placeholder patch restored; zen-ua patch preserved" if changed else "nothing to restore")
    print("Restart the dsh web host only after user confirmation.")
