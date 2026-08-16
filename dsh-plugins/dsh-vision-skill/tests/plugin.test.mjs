import assert from 'node:assert/strict'
import test from 'node:test'
import { ImageMemoryCache, apply, imageMemoryKey } from '../lib/index.js'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

function mockCtx({ withAgents = true, withWebServer = false } = {}) {
  const registered = []
  const events = []
  const routes = []
  const ctx = {
    skills: {
      register(skill) {
        registered.push({ kind: 'skill', name: skill.name })
        return () => {}
      },
    },
    tools: {
      register(tool) {
        registered.push({ kind: 'tool', name: tool.name })
        return () => {}
      },
    },
    get(name) {
      if (name === 'agents' && withAgents) {
        return {
          get() {
            return undefined
          },
        }
      }
      return undefined
    },
    on(event, handler) {
      events.push(event)
      return () => {}
    },
    credentials: undefined,
    logger: { warn() {}, error() {}, info() {} },
  }
  if (withWebServer) {
    ctx.inject = (names, callback) => {
      assert.deepEqual(names, ['webServer'])
      callback({
        webServer: {
          register(entry) {
            routes.push(entry)
            return () => {}
          },
        },
      })
    }
  } else {
    ctx.inject = () => {}
  }
  return { ctx, registered, routes }
}

test('progressive mode registers only activation tool globally', async () => {
  const { ctx, registered } = mockCtx()
  const dispose = await apply(ctx, { progressive: true })
  const globalTools = registered.filter((entry) => entry.kind === 'tool')
  assert.equal(globalTools.length, 1)
  assert.equal(globalTools[0].name, 'vision_activate')
  assert.ok(registered.some((entry) => entry.kind === 'skill' && entry.name === 'vision'))
  dispose()
})

test('non-progressive fallback registers the full tool set globally', async () => {
  const { ctx, registered } = mockCtx({ withAgents: false })
  const dispose = await apply(ctx, { progressive: false })
  const names = registered.filter((entry) => entry.kind === 'tool').map((entry) => entry.name)
  assert.ok(names.includes('vision_analyze'))
  assert.ok(names.includes('vision_long_screenshot_ocr'))
  assert.ok(names.includes('vision_clipboard'))
  dispose()
})

test('web profile mounts paste route through optional webServer inject', async () => {
  const { ctx, routes } = mockCtx({ withWebServer: true })
  const dispose = await apply(ctx, { progressive: true, pasteMaxBytes: 10485760 })
  assert.equal(routes.length, 1)
  assert.equal(routes[0].path, '/dsh-vision-skill/paste')
  dispose()
})


test('image memory cache: TTL expiry and LRU eviction', () => {
  const cache = new ImageMemoryCache({ ttlSeconds: 60, maxEntries: 2 })
  cache.set('a', 1, 1000)
  assert.equal(cache.get('a', 2000), 1)
  assert.equal(cache.get('a', 1000 + 61 * 1000), undefined)
  cache.set('a', 1, 0)
  cache.set('b', 2, 0)
  cache.set('c', 3, 0)
  assert.equal(cache.get('a', 0), undefined)
  assert.equal(cache.get('b', 0), 2)
  assert.equal(cache.get('c', 0), 3)
})

test('image memory key: content hash plus recognition parameters', () => {
  const dir = mkdtempSync(join(tmpdir(), 'dsh-vision-test-'))
  const path = join(dir, 'a.png')
  writeFileSync(path, Buffer.from([1, 2, 3]))
  try {
    const base = imageMemoryKey(path, { mode: 'general', budget: 'normal' })
    assert.equal(base, imageMemoryKey(path, { mode: 'general', budget: 'normal' }))
    assert.notEqual(base, imageMemoryKey(path, { mode: 'evidence', budget: 'normal' }))
    assert.notEqual(base, imageMemoryKey(path, { mode: 'general', budget: 'large' }))
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
