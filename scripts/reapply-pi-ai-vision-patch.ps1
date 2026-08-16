# reapply-pi-ai-vision-patch.ps1
# [pi-ai vision + zen-ua patch] 幂等重打 dsh-llm-pi-ai 的两个补丁：
#   A) zen-ua patch：requestHeaders 放行用户显式配置的 User-Agent
#      （OpenCode Zen 免费层只认 opencode/<ver> UA，否则 429 FreeUsageLimitError）
#   B) 图片→路径占位符：纯文本模型（catalog input 不含 image）贴图不再拒绝
#      （UNSUPPORTED_CONTENT），image 块转成路径占位符文本，模型经 vision skill 读图
#      ——与 dsh-llm-deepseek 的 blockToText 补丁对齐。
# 用途：dsh 包升级/重装（覆盖 node_modules）后重跑恢复。运行后需重启 dsh web 宿主。
# 路径：link 依赖目标已从 .bun/install/global 迁移到 .dsh/profiles（shared store）。

$ErrorActionPreference = 'Stop'

$piAi = Join-Path $env:USERPROFILE '.dsh\profiles\node_modules\@deepseek-ai\dsh-llm-pi-ai\lib\index.js'

if (-not (Test-Path -LiteralPath $piAi)) {
    throw "FAIL : file not found: $piAi"
}

$raw = Get-Content -LiteralPath $piAi -Raw -Encoding UTF8

# ---------- A) zen-ua patch：requestHeaders 放行用户 UA ----------
if ($raw.Contains('[zen-ua patch 2026-08-14]')) {
    Write-Host "skip  zen-ua patch (already up to date)"
} else {
    $old = @'
/** Merge deployment headers while removing case-insensitive attribution collisions. */
function requestHeaders(headers) {
	const attribution = attributionHeaders();
	const reserved = new Set(Object.keys(attribution).map((name) => name.toLowerCase()));
	return {
		...Object.fromEntries(Object.entries(headers ?? {}).filter(([name]) => !reserved.has(name.toLowerCase()))),
		...attribution
	};
}
'@
    $new = @'
/** Merge deployment headers while removing case-insensitive attribution collisions.
 * [zen-ua patch 2026-08-14] OpenCode Zen 免费层只认 `opencode/<ver>` User-Agent，
 * 其他 UA（含 DSH attribution）返回 429 FreeUsageLimitError。补丁：用户显式配置了
 * `user-agent` 时优先保留用户的（放行），未配置才回退 attribution。 */
function requestHeaders(headers) {
	const attribution = attributionHeaders();
	const reserved = new Set(Object.keys(attribution).map((name) => name.toLowerCase()));
	const merged = {
		...Object.fromEntries(Object.entries(headers ?? {}).filter(([name]) => !reserved.has(name.toLowerCase()))),
		...attribution
	};
	// [zen-ua patch] 用户显式配置的 user-agent 优先（大小写不敏感匹配）
	for (const [name, value] of Object.entries(headers ?? {})) {
		if (name.toLowerCase() === "user-agent" && typeof value === "string" && value.trim() !== "") {
			merged["user-agent"] = value;
			break;
		}
	}
	return merged;
}
'@
    if (-not $raw.Contains($old)) {
        throw "FAIL : old requestHeaders not found (package version changed?)"
    }
    $raw = $raw.Replace($old, $new)
    Set-Content -LiteralPath $piAi -Value $raw -Encoding UTF8 -NoNewline
    Write-Host "patch zen-ua patch"
}

# ---------- B) 图片→路径占位符：纯文本模型贴图不拒绝 ----------
$raw = Get-Content -LiteralPath $piAi -Raw -Encoding UTF8
if ($raw.Contains('[vision-skill patch 2026-08-14]')) {
    Write-Host "skip  pi-ai image placeholder patch (already up to date)"
} else {
    # B1: import homedir/join
    $oldImport = "import { launchEnvironmentOf } from `"@deepseek-ai/dsh-launch-environment`";"
    $newImport = "import { launchEnvironmentOf } from `"@deepseek-ai/dsh-launch-environment`";`nimport { homedir } from `"node:os`";`nimport { join } from `"node:path`";"
    if ($raw.Contains($oldImport)) {
        $raw = $raw.Replace($oldImport, $newImport)
        Write-Host "patch import homedir/join"
    } else {
        throw "FAIL : import line not found (package version changed?)"
    }

    # B2: generate() 内拒绝改放行
    $oldGen = @'
				const containsImage = options.messages.some((message) => contentHasImage(message.content));
				if (containsImage && !model.input.includes("image")) throw new LlmError(`pi-ai model "${model.id}" does not support image input`, "UNSUPPORTED_CONTENT");
				const attachments = containsImage ? this.config.resolveAttachments?.() : void 0;
				if (containsImage && attachments === void 0) throw new LlmError("pi-ai image input requires the durable attachment service", "UNSUPPORTED_CONTENT");
				const context = attachments === void 0 ? toPiContext(options) : await toPiContext(options, attachments);
'@
    $newGen = @'
				const containsImage = options.messages.some((message) => contentHasImage(message.content));
				// [vision-skill patch 2026-08-14] 纯文本模型（catalog input 不含 "image"）贴图时，
				// 不再拒绝——改为「图片→路径占位符」模式：userContent 把 image 块转成
				// 路径占位符文本（与 dsh-llm-deepseek 的 blockToText 一致），模型拿到路径后
				// 经 vision skill 读图。多模态模型（input 含 image）保持 base64 原路径。
				const textOnlyImages = containsImage && !model.input.includes("image");
				const attachments = containsImage ? this.config.resolveAttachments?.() : void 0;
				if (containsImage && attachments === void 0) throw new LlmError("pi-ai image input requires the durable attachment service", "UNSUPPORTED_CONTENT");
				const context = attachments === void 0 ? toPiContext(options) : await toPiContext(options, attachments, textOnlyImages);
'@
    if ($raw.Contains($oldGen)) {
        $raw = $raw.Replace($oldGen, $newGen)
        Write-Host "patch generate() image gate"
    } else {
        throw "FAIL : generate() image gate not found (package version changed?)"
    }

    # B3: toPiContext / toPiContextWithImages 加 textOnlyImages 透传
    $oldCtx = @'
function toPiContext(options, attachments) {
	return attachments === void 0 ? textOnlyContext(options) : toPiContextWithImages(options, attachments);
}
async function toPiContextWithImages(options, attachments) {
'@
    $newCtx = @'
function toPiContext(options, attachments, textOnlyImages) {
	return attachments === void 0 ? textOnlyContext(options) : toPiContextWithImages(options, attachments, textOnlyImages);
}
async function toPiContextWithImages(options, attachments, textOnlyImages) {
'@
    if ($raw.Contains($oldCtx)) {
        $raw = $raw.Replace($oldCtx, $newCtx)
        Write-Host "patch toPiContext signature"
    } else {
        throw "FAIL : toPiContext signature not found (package version changed?)"
    }

    # B4: userContent 图片分支 → 占位符
    $oldUC = @'
async function userContent(blocks, attachments) {
	const content = [];
	for (const block of blocks) switch (block.type) {
		case "text":
			if (block.text.length > 0) content.push({
				type: "text",
				text: block.text
			});
			break;
		case "image": {
			const stored = await attachments.readImage(block.attachment);
			content.push({
				type: "image",
				data: Buffer.from(stored.data).toString("base64"),
				mimeType: stored.ref.mediaType
			});
			break;
		}
'@
    $newUC = @'
async function userContent(blocks, attachments, textOnlyImages) {
	const content = [];
	for (const block of blocks) switch (block.type) {
		case "text":
			if (block.text.length > 0) content.push({
				type: "text",
				text: block.text
			});
			break;
		case "image": {
			// [vision-skill patch 2026-08-14] 纯文本模型（textOnlyImages）贴图 →
			// 转路径占位符文本（与 dsh-llm-deepseek 的 blockToText 一致的格式），
			// 模型拿到本地路径后经 vision skill 读图；多模态模型保持 base64。
			if (textOnlyImages === true) {
				const ref = block.attachment;
				const id = typeof ref === "object" && ref !== null && typeof ref.attachmentId === "string" ? ref.attachmentId : "";
				const hex = id.startsWith("sha256:") ? id.slice(7) : "";
				const envHome = process.env.DSH_HOME;
				const home = typeof envHome === "string" && envHome.length > 0 ? envHome.replace(/[\\/]+$/, "") : join(homedir(), ".dsh");
				const path = hex !== "" ? `${home}/attachments/v1/objects/${hex.slice(0, 2)}/${hex}` : "(路径不可推导)";
				const name = typeof ref === "object" && ref !== null && typeof ref.name === "string" ? `，文件名 ${ref.name}` : "";
				const placeholder = `[图片附件 ${id}${name}，本地路径 ${path}，模型不支持直接读图，请用 vision skill 读取]`;
				if (content.length > 0 && content[content.length - 1].type === "text") {
					content[content.length - 1].text += placeholder;
				} else {
					content.push({ type: "text", text: placeholder });
				}
				break;
			}
			const stored = await attachments.readImage(block.attachment);
			content.push({
				type: "image",
				data: Buffer.from(stored.data).toString("base64"),
				mimeType: stored.ref.mediaType
			});
			break;
		}
'@
    if ($raw.Contains($oldUC)) {
        $raw = $raw.Replace($oldUC, $newUC)
        Write-Host "patch userContent image placeholder"
    } else {
        throw "FAIL : userContent image branch not found (package version changed?)"
    }

    # B5: userContent 递归调用透传 textOnlyImages
    $oldRec = @'
				const nested = await userContent(block.content, attachments);
'@
    $newRec = @'
				const nested = await userContent(block.content, attachments, textOnlyImages);
'@
    if ($raw.Contains($oldRec)) {
        $raw = $raw.Replace($oldRec, $newRec)
        Write-Host "patch userContent recursion"
    } else {
        throw "FAIL : userContent recursion not found (package version changed?)"
    }

    # B6: toPiContextWithImages 内 userContent 调用透传（两处）
    $oldCall1 = @'
		const content = await userContent(message.content.filter((block) => block.type !== "tool-result"), attachments);
'@
    $newCall1 = @'
		const content = await userContent(message.content.filter((block) => block.type !== "tool-result"), attachments, textOnlyImages);
'@
    if ($raw.Contains($oldCall1)) {
        $raw = $raw.Replace($oldCall1, $newCall1)
        Write-Host "patch toPiContextWithImages userContent call"
    } else {
        throw "FAIL : toPiContextWithImages userContent call not found (package version changed?)"
    }

    $oldCall2 = @'
			const resultContent = await userContent(result.content, attachments);
'@
    $newCall2 = @'
			const resultContent = await userContent(result.content, attachments, textOnlyImages);
'@
    if ($raw.Contains($oldCall2)) {
        $raw = $raw.Replace($oldCall2, $newCall2)
        Write-Host "patch toPiContextWithImages resultContent call"
    } else {
        throw "FAIL : toPiContextWithImages resultContent call not found (package version changed?)"
    }

    Set-Content -LiteralPath $piAi -Value $raw -Encoding UTF8 -NoNewline
    Write-Host "saved pi-ai lib"
}

# ---------- 校验 ----------
$check = Get-Content -LiteralPath $piAi -Raw -Encoding UTF8
$ok = $true
if (-not $check.Contains('merged["user-agent"] = value')) { Write-Host "verify FAIL : user-agent override missing"; $ok = $false }
if (-not $check.Contains('textOnlyImages')) { Write-Host "verify FAIL : textOnlyImages missing"; $ok = $false }
if (-not $check.Contains('请用 vision skill 读取')) { Write-Host "verify FAIL : placeholder missing"; $ok = $false }
if ($ok) { Write-Host "verify OK : all patches in place" } else { throw "verify FAIL" }

Write-Host "`nDone. 重启 dsh web 宿主后生效（重启命令需用户确认执行）。"
