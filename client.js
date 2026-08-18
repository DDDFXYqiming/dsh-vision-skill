// dsh-vision-skill client half — paste-to-path with composer chips.
//
// 方案 2（参考 dsh-vision-toolkit 的 input-trigger reference 机制）：
//   1. capture 阶段截获剪贴板图片；
//   2. 用 input.insertReference() 在输入框插入一个 chip（📎 filename.png），
//      草稿文本只占一个占位符，不再是一长串路径；
//   3. 发送时 composer 调用 codec.serialize(ref, signal)，此刻才把图片 POST
//      到 /dsh-vision-skill/paste 落盘，并返回模型可读的路径文本。
//
// 兼容性：
//   - 同时注册 legacy `slash` 与新版 `inputTriggers` 两个 reference 注册表；
//   - 若 input.insertReference / 注册表不可用，自动回退为旧行为（立即上传 +
//     直接插入路径文本），保证粘贴功能永不失效；
//   - 不新增工具、不改 agent 目录，anchored-standard 首请求不受影响。

window.__ModuleLoader__.load({
  id: 'dsh-vision-skill',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' })

    const PASTE_ROUTE = '/dsh-vision-skill/paste'
    const SOURCE = 'dsh-vision-pasted-image'
    const MAX_IMAGE_BYTES = 10 * 1024 * 1024
    // sessionStorage 镜像前缀：发送时把 ref -> {label, absolutePath} 落一份，
    // 页面刷新/插件热重载导致内存 records 丢失时，serialize 可据此找回已落盘的图片。
    const MIRROR_KEY_PREFIX = 'dsh-vision-skill:paste:'
    // 撤销/重做会让 chip 短暂“离开”草稿（occurrences 里消失）随后又回来；
    // 这个窗口内不能清理记录，否则重做回来后 ref 失联，发送时必然报错。
    const PRUNE_GRACE_MS = 10 * 60 * 1000
    // records 内存兜底上限：单标签页最多保留 128 个粘贴记录，超出只清最老的死记录。
    const MAX_RECORDS = 128
    let fallbackId = 0

    function id() {
      if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
      fallbackId += 1
      return `paste-${Date.now()}-${fallbackId}`
    }

    function imageFiles(dataTransfer) {
      if (!dataTransfer) return []
      const itemFiles = Array.from(dataTransfer.items || [])
        .filter((item) => item.kind === 'file')
        .map((item) => item.getAsFile())
        .filter((file) => file !== null && file.type.toLowerCase().startsWith('image/'))
      if (itemFiles.length > 0) return itemFiles
      return Array.from(dataTransfer.files || []).filter((file) =>
        file.type.toLowerCase().startsWith('image/'))
    }

    function currentSessionId(ctx) {
      try {
        return ctx.sessions?.list?.getSnapshot?.().current
      } catch {
        return undefined
      }
    }

    function inputFor(ctx, sessionId) {
      try {
        const agentScope = ctx.sessions?.scope?.(sessionId)
        if (agentScope === undefined) return undefined
        return ctx.conversation?.input?.for?.(agentScope)
      } catch {
        return undefined
      }
    }

    function notify(input, message) {
      try {
        input?.notify?.('error', message)
      } catch {
        // 通知槽不可用时静默降级；上传错误可由浏览器控制台排查
      }
    }

    function fileBase(file) {
      const name = file.name?.trim()
      if (name) return name
      const ext = {
        'image/png': '.png',
        'image/jpeg': '.jpg',
        'image/gif': '.gif',
        'image/webp': '.webp',
      }[file.type] || '.img'
      return `clipboard-image${ext}`
    }

    function numberedLabel(base, n) {
      if (n <= 0) return base
      const dot = base.lastIndexOf('.')
      if (dot <= 0) return `${base}${n}`
      return `${base.slice(0, dot)}${n}${base.slice(dot)}`
    }

    /**
     * 为同一批粘贴图片生成不重复的 chip 标签：
     * - 同名图片出现多张时：image1.png / image2.png / ...
     * - 与输入框里已存在的 chip 冲突时继续递增
     * - 单张且无冲突时保持原始文件名
     */
    function labelsForFiles(files, snapshot) {
      const counts = new Map()
      for (const file of files) {
        const base = fileBase(file)
        counts.set(base, (counts.get(base) || 0) + 1)
      }
      const used = new Set(
        (snapshot?.occurrences ?? [])
          .filter((occurrence) => occurrence.source === SOURCE)
          .map((occurrence) => occurrence.label),
      )
      const reserved = new Set()
      return files.map((file) => {
        const base = fileBase(file)
        // 永远从 1 开始编号：第一个 image1.png，第二个 image2.png ...
        let n = 1
        while (used.has(numberedLabel(base, n)) || reserved.has(numberedLabel(base, n))) {
          n += 1
        }
        const label = numberedLabel(base, n)
        reserved.add(label)
        used.add(label)
        return label
      })
    }

    async function upload(file, sessionId, signal) {
      if (!file || file.size <= 0) throw new Error('pasted image is empty')
      if (file.size > MAX_IMAGE_BYTES) {
        throw new Error(`pasted image exceeds ${Math.round(MAX_IMAGE_BYTES / 1024 / 1024)} MB`)
      }
      const query = new URLSearchParams({
        sessionId: String(sessionId),
        name: file.name || 'clipboard-image',
        size: String(file.size),
      })
      const response = await fetch(`${PASTE_ROUTE}?${query.toString()}`, {
        method: 'POST',
        headers: { 'Content-Type': file.type },
        body: file,
        signal,
      })
      const body = await response.json().catch(() => ({
        ok: false,
        error: { message: `paste upload failed (${response.status})` },
      }))
      if (!response.ok || body.ok !== true) {
        throw new Error(body.error?.message || `paste upload failed (${response.status})`)
      }
      if (typeof body.value?.absolutePath !== 'string' || body.value.absolutePath === '') {
        throw new Error('paste upload returned no path')
      }
      return body.value.absolutePath
    }

    function serializeText(record) {
      const label = record.label || record.file?.name || 'image'
      return `[pasted image: ${label}] 请用 vision_analyze 读取: ${JSON.stringify(record.absolutePath)}`
    }

    function mirrorGet(ref) {
      try {
        const raw = globalThis.sessionStorage?.getItem(MIRROR_KEY_PREFIX + ref)
        if (!raw) return undefined
        const data = JSON.parse(raw)
        if (data && typeof data.label === 'string' && typeof data.absolutePath === 'string' && data.absolutePath !== '') {
          return data
        }
        return undefined
      } catch {
        return undefined
      }
    }

    function mirrorSave(ref, data) {
      try {
        globalThis.sessionStorage?.setItem(MIRROR_KEY_PREFIX + ref, JSON.stringify(data))
      } catch {
        // sessionStorage 不可用（隐私模式/测试环境）时静默降级
      }
    }

    function PasteImageController(ctx) {
      this.ctx = ctx
      this.records = new Map() // ref -> { file, sessionId, label, status, absolutePath, inflight, error }
      this.trackedInputs = new WeakSet()
      this.source = this.buildSource()
    }

    PasteImageController.prototype.buildSource = function buildSource() {
      const controller = this
      return {
        trigger: '@',
        name: SOURCE,
        order: 1000,
        candidates: () => Promise.resolve([]),
        onPick: () => undefined,
        codec: {
          clipboardText: (ref) => {
            const record = controller.records.get(ref) ?? mirrorGet(ref)
            const label = record?.label
            return `[pasted image: ${label || ref}]`
          },
          serialize: (ref, signal) => controller.serialize(ref, signal),
        },
      }
    }

    PasteImageController.prototype.ensureUploaded = function ensureUploaded(record, signal) {
      if (record.absolutePath !== undefined) return Promise.resolve(record.absolutePath)
      if (record.inflight !== undefined) return record.inflight
      record.status = 'copying'
      record.inflight = upload(record.file, record.sessionId, signal)
        .then((path) => {
          record.absolutePath = path
          record.status = 'copied'
          record.error = undefined
          return path
        })
        .catch((error) => {
          record.status = 'error'
          record.error = String(error?.message ?? error)
          throw error
        })
        .finally(() => {
          record.inflight = undefined
        })
      return record.inflight
    }

    PasteImageController.prototype.serialize = async function serialize(ref, signal) {
      let record = this.records.get(ref)
      if (record === undefined) record = this.restoreRecord(ref)
      if (record === undefined) {
        // 记录已不在（页面刷新/插件热重载清空了内存表，且该图从未上传成功）——
        // 原始字节只存在于此前的标签页内存里，无法找回，直接告诉用户怎么处理。
        throw new Error(
          '这张粘贴图片在当前浏览器标签页已失效：原始字节只存在于此前的页面内存里，无法找回。' +
          '请删除该图片并重新粘贴后再发送。',
        )
      }
      await this.ensureUploaded(record, signal)
      if (record.absolutePath !== undefined) {
        mirrorSave(ref, { label: record.label, absolutePath: record.absolutePath })
      }
      return serializeText(record)
    }

    /**
     * 从 sessionStorage 镜像恢复一个已落盘的粘贴记录。
     * 仅在镜像里已有 absolutePath（说明图片曾上传成功）时才算可恢复；
     * 只有 label 没有路径的镜像说明字节从未上传，无法重建。
     */
    PasteImageController.prototype.restoreRecord = function restoreRecord(ref) {
      const data = mirrorGet(ref)
      if (data === undefined) return undefined
      return {
        label: data.label,
        absolutePath: data.absolutePath,
        status: 'copied',
        file: undefined,
        sessionId: undefined,
        inflight: undefined,
        error: undefined,
        lastAlive: Date.now(),
      }
    }

    PasteImageController.prototype.trackInput = function trackInput(input) {
      if (!input || this.trackedInputs.has(input)) return
      this.trackedInputs.add(input)
      const controller = this
      if (typeof input.state?.subscribe === 'function') {
        input.state.subscribe(() => controller.prune(input))
      }
      this.prune(input)
    }

    PasteImageController.prototype.prune = function prune(input) {
      const snapshot = input.state?.getSnapshot?.()
      const alive = new Set(
        (snapshot?.occurrences ?? [])
          .filter((occurrence) => occurrence.source === SOURCE)
          .map((occurrence) => occurrence.ref),
      )
      const now = Date.now()
      // 当前还在草稿里的 chip：刷新“最后存活时间”。
      for (const ref of alive) {
        const record = this.records.get(ref)
        if (record !== undefined) record.lastAlive = now
      }
      // 回收确认死亡、且已消失超过宽限期的记录；宽限期保证 undo/redo 期间不误删。
      for (const [ref, record] of [...this.records.entries()]) {
        if (record.inflight !== undefined) continue
        if (alive.has(ref)) continue
        if (now - (record.lastAlive ?? now) < PRUNE_GRACE_MS) continue
        this.records.delete(ref)
      }
      // 硬上限兜底：只清“非存活且非上传中”的最老记录，绝不碰还在草稿里的 chip。
      if (this.records.size > MAX_RECORDS) {
        const stale = [...this.records.entries()]
          .filter(([ref, record]) => !alive.has(ref) && record.inflight === undefined)
          .sort((a, b) => (a[1].lastAlive ?? 0) - (b[1].lastAlive ?? 0))
        for (const [ref] of stale) {
          if (this.records.size <= MAX_RECORDS) break
          this.records.delete(ref)
        }
      }
    }

    PasteImageController.prototype.handlePaste = function handlePaste(event) {
      const files = imageFiles(event.clipboardData)
      if (files.length === 0) return false
      const target = event.target
      if (!(target instanceof HTMLTextAreaElement) || target.closest('[data-composer-card]') === null) {
        return false
      }
      event.preventDefault()
      event.stopPropagation()
      event.stopImmediatePropagation()

      const sessionId = currentSessionId(this.ctx)
      if (sessionId === undefined) return true
      const input = inputFor(this.ctx, String(sessionId))
      if (input === undefined) return true
      const snapshot = input.state?.getSnapshot?.()
      const draft = typeof snapshot?.draft === 'string' ? snapshot.draft : ''
      if (snapshot?.phase !== undefined && snapshot.phase !== 'plain') return true
      this.trackInput(input)

      const start = Math.max(0, Math.min(target.selectionStart ?? draft.length, draft.length))
      const end = Math.max(start, Math.min(target.selectionEnd ?? start, draft.length))
      const plainText = (event.clipboardData?.getData('text/plain') ?? '').replaceAll('\uFFFC', '')
      const draftBefore = draft

      // 旧版/异常环境兜底：没有 reference 能力时，立即上传并插入路径文本。
      if (typeof input.insertReference !== 'function') {
        ;(async () => {
          try {
            const paths = []
            for (const file of files) {
              paths.push(await upload(file, String(sessionId), new AbortController().signal))
            }
            const pathText = paths
              .map((path) => `[pasted image available at absolute path: ${JSON.stringify(path)}] 如需查看内容，请用 vision_analyze 读取该路径。`)
              .join(' ')
            const next = draft.slice(0, start) + plainText + pathText + draft.slice(end)
            input.setDraft?.(next)
            const cursor = start + plainText.length + pathText.length
            requestAnimationFrame(() => {
              target.focus({ preventScroll: true })
              target.setSelectionRange(cursor, cursor)
            })
          } catch (error) {
            notify(input, String(error?.message ?? error))
          }
        })()
        return true
      }

      let inserted = []
      try {
        let cursor = start
        if (plainText !== '') {
          const next = draft.slice(0, start) + plainText + draft.slice(end)
          input.setDraft?.(next)
          cursor = start + plainText.length
        }
        const labels = labelsForFiles(files, input.state.getSnapshot())
        for (const [index, file] of files.entries()) {
          const ref = id()
          const label = labels[index] || fileBase(file)
          const record = {
            file,
            sessionId: String(sessionId),
            label,
            status: 'ready',
            absolutePath: undefined,
            inflight: undefined,
            error: undefined,
            lastAlive: Date.now(),
          }
          this.records.set(ref, record)
          inserted.push(ref)
          // 每张图都重新读一次最新快照：composer 每插入一个 chip 都会让 draftRev +1，
          // 复用循环外抓的旧 draftRev 会让第二张及以后的插入 CAS 失败（ref 已入表但
          // chip 没插进去，发送时就会报 “pasted image is no longer available...”）。
          const snap = input.state.getSnapshot()
          const accepted = input.insertReference(
            { source: SOURCE, ref, label, clipboardText: `[pasted image: ${label}]` },
            { start: cursor, end: cursor, draftRev: snap.draftRev },
          )
          if (!accepted) throw new Error('The composer changed before pasted images could be inserted')
          cursor += 1
          const after = input.state.getSnapshot()
          const suffix = after.draft.slice(cursor)
          if (suffix !== '' && !/^\s/u.test(suffix)) {
            input.setDraft?.(`${after.draft.slice(0, cursor)} ${suffix}`)
          }
        }
        requestAnimationFrame(() => {
          target.focus({ preventScroll: true })
          target.setSelectionRange(cursor, cursor)
        })
      } catch (error) {
        // 只回滚/清理本次粘贴产生的引用，避免误删草稿里其它仍在用的 chip 记录
        input.setDraft?.(draftBefore)
        for (const ref of inserted) this.records.delete(ref)
        notify(input, String(error?.message ?? error))
      }
      return true
    }

    function registerReferenceSources(ctx, controller, disposers) {
      const registrations = new Map()
      const register = (registry) => {
        if (!registry || typeof registry.registerSource !== 'function') return undefined
        let registration = registrations.get(registry)
        if (registration === undefined) {
          registration = { dispose: registry.registerSource(controller.source), owners: 0 }
          registrations.set(registry, registration)
        }
        registration.owners += 1
        return () => {
          registration.owners -= 1
          if (registration.owners > 0) return
          registrations.delete(registry)
          try { registration.dispose() } catch { /* 忽略卸载清理错误 */ }
        }
      }
      if (typeof ctx.inject === 'function') {
        try {
          ctx.inject(['slash'], (scope) => {
            const dispose = register(scope?.slash)
            if (dispose) disposers.push(dispose)
          })
        } catch { /* 旧版客户端可能没有 slash */ }
        try {
          ctx.inject(['inputTriggers'], (scope) => {
            const dispose = register(scope?.inputTriggers)
            if (dispose) disposers.push(dispose)
          })
        } catch { /* 新版客户端可能没有 inputTriggers */ }
      }
    }

    function apply(ctx) {
      const controller = new PasteImageController(ctx)
      const disposers = []
      registerReferenceSources(ctx, controller, disposers)

      const onPaste = (event) => controller.handlePaste(event)
      document.addEventListener('paste', onPaste, true)

      return () => {
        document.removeEventListener('paste', onPaste, true)
        for (const dispose of [...disposers].reverse()) {
          try { dispose() } catch { /* 忽略清理错误 */ }
        }
        controller.records.clear()
      }
    }

    exports.name = 'dsh-vision-skill'
    exports.inject = ['sessions', 'conversation']
    exports.apply = apply
    return module.exports
  },
})
