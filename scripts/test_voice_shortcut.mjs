/**
 * 背备不悲 · 空格快捷键判定逻辑单元测试
 *
 * 为什么值得单独测：
 *   答题页和面试室都有输入框，中文输入法还用空格选候选词。
 *   一旦判定错了，用户会遇到「想打空格结果开始录音」这种灾难性体验，
 *   而这种错**只有在真实浏览器里手动操作才会暴露**，回归成本极高。
 *   把判定抽成纯函数后，这张真值表就能秒级跑完。
 *
 * 用法：node scripts/test_voice_shortcut.mjs
 *      （不需要浏览器、不需要服务、不需要凭据）
 */

import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

// typescript 装在 beibei-web/node_modules 里，从 scripts/ 目录解析不到，
// 所以用 createRequire 锚到 beibei-web 去加载它
const requireFromWeb = createRequire(path.join(ROOT, 'beibei-web', 'package.json'))
const ts = requireFromWeb('typescript')

const SRC = path.join(ROOT, 'beibei-web', 'src', 'utils', 'voiceShortcut.ts')

// 用 TypeScript 自带编译器把那个纯函数转成 ESM，避免为一个测试引入构建配置
const source = fs.readFileSync(SRC, 'utf-8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const tmp = path.join(ROOT, 'beibei-web', 'node_modules', '.tmp', 'voiceShortcut.test.mjs')
fs.mkdirSync(path.dirname(tmp), { recursive: true })
fs.writeFileSync(tmp, outputText, 'utf-8')

// 用 node:url 的 pathToFileURL —— 手工拼 'file:///' + 中文路径 容易踩编码坑
const { decideSpace, isTextEntry } = await import(pathToFileURL(tmp).href)

/** 默认上下文：焦点在页面空白处，一切正常 */
const base = {
  key: ' ',
  code: 'Space',
  repeat: false,
  isComposing: false,
  keyCode: 32,
  targetTag: 'BODY',
  targetType: undefined,
  targetContentEditable: false,
  disabled: false,
  unavailable: false,
  shortcutOn: true,
  isOwner: true,
}

const cases = [
  // ── 绝对不能抢的情况 ──────────────────────────────────────────────
  ['焦点在 textarea → 空格是打字', { targetTag: 'TEXTAREA' }, { capture: false, act: false }],
  ['焦点在 input[text] → 空格是打字', { targetTag: 'INPUT', targetType: 'text' }, { capture: false, act: false }],
  ['焦点在 input[search] → 空格是打字', { targetTag: 'INPUT', targetType: 'search' }, { capture: false, act: false }],
  ['焦点在 input[password]', { targetTag: 'INPUT', targetType: 'password' }, { capture: false, act: false }],
  ['焦点在 contenteditable', { targetTag: 'DIV', targetContentEditable: true }, { capture: false, act: false }],
  ['焦点在 select', { targetTag: 'SELECT' }, { capture: false, act: false }],
  ['中文输入法选词中（isComposing）', { isComposing: true }, { capture: false, act: false }],
  ['输入法只给 keyCode 229', { keyCode: 229 }, { capture: false, act: false }],
  ['输入法 + textarea 双重保险', { targetTag: 'TEXTAREA', isComposing: true }, { capture: false, act: false }],

  // ── 该抢并且要动手的情况 ──────────────────────────────────────────
  ['焦点在 body → 开始/切换录音', {}, { capture: true, act: true }],
  ['焦点在 div 空白处', { targetTag: 'DIV' }, { capture: true, act: true }],
  ['焦点在按钮上 → 也接管（本页空格优先给语音）', { targetTag: 'BUTTON' }, { capture: true, act: true }],
  ['input[checkbox] 不吃空格 → 接管', { targetTag: 'INPUT', targetType: 'checkbox' }, { capture: true, act: true }],

  // ── 该吞掉但不动手的情况 ──────────────────────────────────────────
  ['按住不放的连续触发 → 只 preventDefault', { repeat: true }, { capture: true, act: false }],
  ['录音功能 disabled → 吞掉空格防滚动', { disabled: true }, { capture: true, act: false }],
  ['ASR 不可用 → 吞掉空格防滚动', { unavailable: true }, { capture: true, act: false }],

  // ── 不归我们管的情况 ──────────────────────────────────────────────
  ['不是空格键', { key: 'a', code: 'KeyA' }, { capture: false, act: false }],
  ['快捷键被关掉', { shortcutOn: false }, { capture: false, act: false }],
  ['本实例不是键盘归属者（一页两个实例时）', { isOwner: false }, { capture: false, act: false }],

  // ── 顺序陷阱：输入框优先级必须高于「disabled」等状态判断 ────────────
  ['textarea + disabled → 空格仍然要打字，不能吞',
    { targetTag: 'TEXTAREA', disabled: true }, { capture: false, act: false }],
  ['textarea + shortcutOn=false → 空格仍然要打字',
    { targetTag: 'TEXTAREA', shortcutOn: false }, { capture: false, act: false }],
  ['输入法组合中 + repeat → 绝不能抢',
    { isComposing: true, repeat: true }, { capture: false, act: false }],
]

let failed = 0

console.log('='.repeat(78))
console.log('  背备不悲 · 空格快捷键判定 单元测试')
console.log('='.repeat(78))
console.log()

for (const [desc, patch, expect] of cases) {
  const decision = decideSpace({ ...base, ...patch })
  const ok = decision.capture === expect.capture && decision.act === expect.act
  if (!ok) failed++
  const got = `capture=${decision.capture} act=${decision.act}`
  const want = `capture=${expect.capture} act=${expect.act}`
  console.log(
    `  [${ok ? 'OK ' : 'FAIL'}] ${desc.padEnd(42)} ${got}` +
    (ok ? `  (${decision.reason})` : `   ← 期望 ${want}`),
  )
}

// isTextEntry 的直接断言（补充覆盖上面没走到的类型）
console.log()
console.log('  ── isTextEntry 补充断言 ──')
const entryCases = [
  ['TEXTAREA', undefined, false, true],
  ['INPUT', 'text', false, true],
  ['INPUT', 'number', false, true],
  ['INPUT', 'checkbox', false, false],
  ['INPUT', 'radio', false, false],
  ['INPUT', 'file', false, false],
  ['INPUT', 'range', false, false],
  ['DIV', undefined, true, true],
  ['DIV', undefined, false, false],
  ['BUTTON', undefined, false, false],
  ['BODY', undefined, false, false],
  ['', undefined, false, false],
]
for (const [tag, type, ce, expect] of entryCases) {
  const got = isTextEntry(tag, type, ce)
  const ok = got === expect
  if (!ok) failed++
  console.log(
    `  [${ok ? 'OK ' : 'FAIL'}] isTextEntry(${tag || "''"}, ${type ?? '-'}, ${ce}) = ${got}` +
    (ok ? '' : `   ← 期望 ${expect}`),
  )
}

console.log()
console.log('='.repeat(78))
console.log(
  failed === 0
    ? `  全部通过 ✅（${cases.length + entryCases.length} 条）`
    : `  有 ${failed} 条失败 ❌`,
)
console.log('='.repeat(78))

process.exit(failed === 0 ? 0 : 1)
