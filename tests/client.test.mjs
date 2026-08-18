import assert from 'node:assert/strict'
import test from 'node:test'

const captured = []
globalThis.window = {
  __ModuleLoader__: {
    load(definition) {
      captured.push(definition)
    },
  },
}

await import('../client.js')

test('client bundle exports and registers reference source + paste listener', async () => {
  const definition = captured[0]
  assert.equal(definition.id, 'dsh-vision-skill')
  const exports = definition.factory(() => undefined)
  assert.equal(exports.name, 'dsh-vision-skill')
  assert.deepEqual(exports.inject, ['sessions', 'conversation'])

  const registry = {
    sources: [],
    registerSource(source) {
      this.sources.push(source)
      return () => {}
    },
  }
  const injectCalls = []
  const ctx = {
    sessions: { list: { getSnapshot: () => ({ current: 's1' }) }, scope: () => ({}) },
    conversation: { input: { for: () => ({}) } },
    inject(names, callback) {
      injectCalls.push(names)
      if (names[0] === 'slash') callback({ slash: registry })
      if (names[0] === 'inputTriggers') callback({ inputTriggers: registry })
    },
  }
  const listeners = []
  globalThis.document = {
    addEventListener(name, handler) { listeners.push({ name, handler }) },
    removeEventListener(name, handler) { /* noop */ },
  }
  const dispose = exports.apply(ctx)
  assert.equal(listeners.length, 1)
  assert.equal(listeners[0].name, 'paste')
  assert.equal(registry.sources.length, 1)
  assert.equal(registry.sources[0].name, 'dsh-vision-pasted-image')
  dispose()
})

test('paste inserts a chip reference and serialize returns the model-facing path', async () => {
  const definition = captured[0]
  const exports = definition.factory(() => undefined)

  class FakeTextArea {}
  globalThis.HTMLTextAreaElement = FakeTextArea
  globalThis.requestAnimationFrame = (callback) => callback()

  const target = new FakeTextArea()
  target.closest = () => ({})
  target.selectionStart = 0
  target.selectionEnd = 0
  target.focus = () => {}
  target.setSelectionRange = () => {}

  let draft = ''
  const occurrences = []
  const input = {
    state: {
      getSnapshot: () => ({ draft, draftRev: 1, phase: 'plain', occurrences }),
      subscribe: () => () => {},
    },
    setDraft(next) { draft = next },
    insertReference(payload, span) {
      occurrences.push({ ...payload, occurrenceId: occurrences.length + 1, offset: span.start })
      draft = draft.slice(0, span.start) + '\uFFFC' + draft.slice(span.end)
      return true
    },
    notify() {},
  }

  const registry = {
    sources: [],
    registerSource(source) {
      this.sources.push(source)
      return () => {}
    },
  }
  const ctx = {
    sessions: { list: { getSnapshot: () => ({ current: 's1' }) }, scope: () => ({}) },
    conversation: { input: { for: () => input } },
    inject(names, callback) {
      if (names[0] === 'slash') callback({ slash: registry })
      if (names[0] === 'inputTriggers') callback({ inputTriggers: registry })
    },
  }
  const listeners = []
  globalThis.document = {
    addEventListener(name, handler) { listeners.push({ name, handler }) },
    removeEventListener() {},
  }
  globalThis.fetch = async () => ({
    ok: true,
    status: 201,
    json: async () => ({ ok: true, value: { absolutePath: 'D:\\AI_Projects\\img.png', filename: 'img.png', bytes: 3 } }),
  })

  const dispose = exports.apply(ctx)
  const fileA = { name: 'img.png', type: 'image/png', size: 3 }
  const fileB = { name: 'img.png', type: 'image/png', size: 4 }
  const files = [fileA, fileB]
  const event = {
    clipboardData: {
      items: files.map((file) => ({ kind: 'file', getAsFile: () => file })),
      files,
      getData: () => '',
    },
    target,
    preventDefault() {},
    stopPropagation() {},
    stopImmediatePropagation() {},
  }
  listeners[0].handler(event)

  assert.equal(occurrences.length, 2)
  assert.equal(occurrences[0].source, 'dsh-vision-pasted-image')
  assert.equal(occurrences[0].label, 'img1.png')
  assert.equal(occurrences[1].label, 'img2.png')
  assert.equal(draft, '\uFFFC\uFFFC')

  const serialized = await registry.sources[0].codec.serialize(occurrences[0].ref, new AbortController().signal)
  assert.match(serialized, /vision_analyze/)
  assert.ok(serialized.includes('img1.png'))
  assert.equal(registry.sources[0].codec.clipboardText(occurrences[0].ref), '[pasted image: img1.png]')
  dispose()
})

test('single pasted image also starts numbering at image1.png', async () => {
  const definition = captured[0]
  const exports = definition.factory(() => undefined)

  class FakeTextArea {}
  globalThis.HTMLTextAreaElement = FakeTextArea
  globalThis.requestAnimationFrame = (callback) => callback()

  const target = new FakeTextArea()
  target.closest = () => ({})
  target.selectionStart = 0
  target.selectionEnd = 0
  target.focus = () => {}
  target.setSelectionRange = () => {}

  let draft = ''
  const occurrences = []
  const input = {
    state: {
      getSnapshot: () => ({ draft, draftRev: 1, phase: 'plain', occurrences }),
      subscribe: () => () => {},
    },
    setDraft(next) { draft = next },
    insertReference(payload, span) {
      occurrences.push({ ...payload, occurrenceId: occurrences.length + 1, offset: span.start })
      draft = draft.slice(0, span.start) + '\uFFFC' + draft.slice(span.end)
      return true
    },
    notify() {},
  }
  const registry = { sources: [], registerSource(source) { this.sources.push(source); return () => {} } }
  const ctx = {
    sessions: { list: { getSnapshot: () => ({ current: 's1' }) }, scope: () => ({}) },
    conversation: { input: { for: () => input } },
    inject(names, callback) {
      if (names[0] === 'slash') callback({ slash: registry })
      if (names[0] === 'inputTriggers') callback({ inputTriggers: registry })
    },
  }
  const listeners = []
  globalThis.document = { addEventListener(name, handler) { listeners.push({ name, handler }) }, removeEventListener() {} }
  const dispose = exports.apply(ctx)
  const file = { name: 'image.png', type: 'image/png', size: 3 }
  listeners[0].handler({
    clipboardData: { items: [{ kind: 'file', getAsFile: () => file }], files: [file], getData: () => '' },
    target,
    preventDefault() {},
    stopPropagation() {},
    stopImmediatePropagation() {},
  })
  assert.equal(occurrences.length, 1)
  assert.equal(occurrences[0].label, 'image1.png')
  dispose()
})

test('undo/redo keeps the paste record alive so serialize still works', async () => {
  const definition = captured[0]
  const exports = definition.factory(() => undefined)

  class FakeTextArea {}
  globalThis.HTMLTextAreaElement = FakeTextArea
  globalThis.requestAnimationFrame = (callback) => callback()

  const target = new FakeTextArea()
  target.closest = () => ({})
  target.selectionStart = 0
  target.selectionEnd = 0
  target.focus = () => {}
  target.setSelectionRange = () => {}

  let draft = ''
  let draftRev = 1
  const occurrences = []
  let onChange
  const input = {
    state: {
      getSnapshot: () => ({ draft, draftRev, phase: 'plain', occurrences }),
      subscribe(cb) { onChange = cb; return () => { onChange = undefined } },
    },
    setDraft(next) { draft = next },
    insertReference(payload, span) {
      occurrences.push({ ...payload, occurrenceId: occurrences.length + 1, offset: span.start })
      draft = draft.slice(0, span.start) + '\uFFFC' + draft.slice(span.end)
      return true
    },
    notify() {},
  }
  const registry = { sources: [], registerSource(source) { this.sources.push(source); return () => {} } }
  const ctx = {
    sessions: { list: { getSnapshot: () => ({ current: 's1' }) }, scope: () => ({}) },
    conversation: { input: { for: () => input } },
    inject(names, callback) {
      if (names[0] === 'slash') callback({ slash: registry })
      if (names[0] === 'inputTriggers') callback({ inputTriggers: registry })
    },
  }
  const listeners = []
  globalThis.document = { addEventListener(name, handler) { listeners.push({ name, handler }) }, removeEventListener() {} }
  globalThis.fetch = async () => ({
    ok: true,
    status: 201,
    json: async () => ({ ok: true, value: { absolutePath: 'D:\\AI_Projects\\undo.png', filename: 'undo.png', bytes: 3 } }),
  })
  const dispose = exports.apply(ctx)
  const file = { name: 'undo.png', type: 'image/png', size: 3 }
  listeners[0].handler({
    clipboardData: { items: [{ kind: 'file', getAsFile: () => file }], files: [file], getData: () => '' },
    target,
    preventDefault() {},
    stopPropagation() {},
    stopImmediatePropagation() {},
  })
  assert.equal(occurrences.length, 1)
  const ref = occurrences[0].ref
  const undoneOccurrence = occurrences[0]

  // 撤销：chip 暂时离开草稿 → prune 运行，但宽限期内记录必须保留
  occurrences.length = 0
  onChange()
  // 重做：同一个 ref 的 chip 又回来 → 发送必须仍然成功
  occurrences.push(undoneOccurrence)
  onChange()

  const text = await registry.sources[0].codec.serialize(ref, new AbortController().signal)
  assert.match(text, /undo\.png/)
  assert.match(text, /vision_analyze/)
  dispose()
})

test('multi-image paste re-reads draftRev per image so the composer CAS accepts all chips', async () => {
  const definition = captured[0]
  const exports = definition.factory(() => undefined)

  class FakeTextArea {}
  globalThis.HTMLTextAreaElement = FakeTextArea
  globalThis.requestAnimationFrame = (callback) => callback()

  const target = new FakeTextArea()
  target.closest = () => ({})
  target.selectionStart = 0
  target.selectionEnd = 0
  target.focus = () => {}
  target.setSelectionRange = () => {}

  let draft = ''
  let draftRev = 1
  const occurrences = []
  const input = {
    state: {
      getSnapshot: () => ({ draft, draftRev, phase: 'plain', occurrences }),
      subscribe: () => () => {},
    },
    setDraft(next) { draft = next },
    // 模拟真实 composer：span 必须携带当前 draftRev，插入成功会推进 draftRev
    insertReference(payload, span) {
      if (span.draftRev !== draftRev) return false
      occurrences.push({ ...payload, occurrenceId: occurrences.length + 1, offset: span.start })
      draft = draft.slice(0, span.start) + '\uFFFC' + draft.slice(span.end)
      draftRev += 1
      return true
    },
    notify() {},
  }
  const registry = { sources: [], registerSource(source) { this.sources.push(source); return () => {} } }
  const ctx = {
    sessions: { list: { getSnapshot: () => ({ current: 's1' }) }, scope: () => ({}) },
    conversation: { input: { for: () => input } },
    inject(names, callback) {
      if (names[0] === 'slash') callback({ slash: registry })
      if (names[0] === 'inputTriggers') callback({ inputTriggers: registry })
    },
  }
  const listeners = []
  globalThis.document = { addEventListener(name, handler) { listeners.push({ name, handler }) }, removeEventListener() {} }
  globalThis.fetch = async () => ({
    ok: true,
    status: 201,
    json: async () => ({ ok: true, value: { absolutePath: 'D:\\AI_Projects\\a.png', filename: 'a.png', bytes: 3 } }),
  })
  const dispose = exports.apply(ctx)
  const files = [
    { name: 'a.png', type: 'image/png', size: 3 },
    { name: 'b.png', type: 'image/png', size: 4 },
  ]
  listeners[0].handler({
    clipboardData: { items: files.map((f) => ({ kind: 'file', getAsFile: () => f })), files, getData: () => '' },
    target,
    preventDefault() {},
    stopPropagation() {},
    stopImmediatePropagation() {},
  })
  assert.equal(occurrences.length, 2)
  assert.equal(occurrences[0].label, 'a1.png')
  assert.equal(occurrences[1].label, 'b1.png')
  assert.equal(draft, '\uFFFC\uFFFC')
  // 两张都能发送成功
  const text = await registry.sources[0].codec.serialize(occurrences[1].ref, new AbortController().signal)
  assert.match(text, /b1\.png/)
  dispose()
})

test('serialize falls back to the sessionStorage mirror for already-uploaded refs after reload', async () => {
  const definition = captured[0]
  const exports = definition.factory(() => undefined)

  const storage = new Map()
  globalThis.sessionStorage = {
    getItem(key) { return storage.has(key) ? storage.get(key) : null },
    setItem(key, value) { storage.set(key, String(value)) },
  }
  storage.set(
    'dsh-vision-skill:paste:ref-restored',
    JSON.stringify({ label: 'old.png', absolutePath: 'D:\\AI_Projects\\old.png' }),
  )

  const registry = { sources: [], registerSource(source) { this.sources.push(source); return () => {} } }
  const ctx = {
    sessions: { list: { getSnapshot: () => ({ current: 's1' }) }, scope: () => ({}) },
    conversation: { input: { for: () => undefined } },
    inject(names, callback) {
      if (names[0] === 'slash') callback({ slash: registry })
      if (names[0] === 'inputTriggers') callback({ inputTriggers: registry })
    },
  }
  globalThis.document = { addEventListener() {}, removeEventListener() {} }
  let fetchCalls = 0
  globalThis.fetch = async () => {
    fetchCalls += 1
    return { ok: true, status: 201, json: async () => ({ ok: true, value: { absolutePath: 'x', filename: 'x', bytes: 1 } }) }
  }
  const dispose = exports.apply(ctx)

  const source = registry.sources[0]
  const text = await source.codec.serialize('ref-restored', new AbortController().signal)
  assert.equal(fetchCalls, 0, 'restored ref must not re-upload')
  assert.ok(text.includes('old.png'))
  assert.ok(text.includes(JSON.stringify('D:\\AI_Projects\\old.png')))
  assert.equal(source.codec.clipboardText('ref-restored'), '[pasted image: old.png]')

  delete globalThis.sessionStorage
  dispose()
})

test('serialize reports an actionable error when the ref is gone with no mirror', async () => {
  const definition = captured[0]
  const exports = definition.factory(() => undefined)
  delete globalThis.sessionStorage // 确保无镜像可恢复

  const registry = { sources: [], registerSource(source) { this.sources.push(source); return () => {} } }
  const ctx = {
    sessions: { list: { getSnapshot: () => ({ current: 's1' }) }, scope: () => ({}) },
    conversation: { input: { for: () => undefined } },
    inject(names, callback) {
      if (names[0] === 'slash') callback({ slash: registry })
      if (names[0] === 'inputTriggers') callback({ inputTriggers: registry })
    },
  }
  globalThis.document = { addEventListener() {}, removeEventListener() {} }
  globalThis.fetch = async () => { throw new Error('should not upload') }
  const dispose = exports.apply(ctx)

  await assert.rejects(
    registry.sources[0].codec.serialize('ref-gone', new AbortController().signal),
    /重新粘贴/,
  )
  dispose()
})
