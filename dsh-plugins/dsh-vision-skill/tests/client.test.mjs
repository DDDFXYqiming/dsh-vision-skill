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
