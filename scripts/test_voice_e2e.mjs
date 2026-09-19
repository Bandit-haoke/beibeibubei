/**
 * 真机驱动测试：语音识别结果到底有没有回填到输入框
 *
 * 为什么值得这么测：
 *   「录完音什么都不显示」这类问题，静态看代码看不出来 ——
 *   后端日志显示 200、返回了 56 个字的文本，组件里也有 emit('text', ...)，
 *   但界面上就是没东西。只有真的把浏览器跑起来、真的点一下按钮，
 *   才能确定断在哪一环。
 *
 * 做法：
 *   1. 用 puppeteer-core 驱动本机 Chrome（不下载 Chromium）
 *   2. 把 getUserMedia / MediaRecorder 打桩，让「点一下」就能产出一个假音频 Blob
 *   3. 拦截 /api/asr/transcribe，返回固定的成功响应
 *      —— 这样测的就纯粹是「前端拿到文本之后有没有显示」，与 ASR 质量无关
 *   4. 点按钮，读输入框的值，并收集控制台报错
 *
 * 用法：node scripts/test_voice_e2e.mjs [面试id]
 */

import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const requireFromWeb = createRequire(path.join(ROOT, 'beibei-web', 'package.json'))
const puppeteer = requireFromWeb('puppeteer-core')

const CHROME_CANDIDATES = [
  process.env.LOCALAPPDATA + '\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
]
const chromePath = CHROME_CANDIDATES.find((p) => p && fs.existsSync(p))
if (!chromePath) {
  console.error('找不到 Chrome/Edge，无法做真机测试')
  process.exit(2)
}

const BASE = 'http://127.0.0.1:8080'
const FAKE_TEXT = '这是一段用于验证回填的识别结果'

// 把浏览器里的录音 API 换成假的：一次点击就能产生 Blob，不需要真麦克风
const STUB_RECORDER = () => {
  class FakeMediaRecorder {
    constructor(stream, opts) {
      this.stream = stream
      this.state = 'inactive'
      this.ondataavailable = null
      this.onstop = null
      this._type = (opts && opts.mimeType) || 'audio/webm'
    }
    start() {
      this.state = 'recording'
      this._timer = setTimeout(() => {
        // 造一段大于组件里 2000 字节阈值的假音频
        if (this.ondataavailable) {
          this.ondataavailable({ data: new Blob([new Uint8Array(4096)], { type: this._type }) })
        }
      }, 300)
    }
    stop() {
      this.state = 'inactive'
      clearTimeout(this._timer)
      setTimeout(() => this.onstop && this.onstop(), 10)
    }
  }
  FakeMediaRecorder.isTypeSupported = () => true
  window.MediaRecorder = FakeMediaRecorder

  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: async () => ({
        getTracks: () => [{ stop() {} }],
      }),
    },
  })
}

async function main() {
  const interviewId = process.argv[2] || '17'
  const mode = process.argv[3] === 'toggle' ? 'toggle' : 'hold'
  const scenario = process.argv[4] || 'success'   // success | empty | error
  const url = `${BASE}/interview/${interviewId}/room`

  // 三种后端响应，用来确认「每种情况下用户都该看到点什么」。
  // 「什么都不显示」如果真的一点提示都没有，那就不是这三种里的任何一种。
  const RESPONSES = {
    success: {
      code: 0, msg: 'ok',
      data: { ok: true, text: FAKE_TEXT, rawText: FAKE_TEXT, hotwordFixes: [],
              durationMs: 3000, provider: 'xfyun', credentialSource: '测试桩',
              hotwordCount: 0, chunkCount: 1 },
    },
    empty: {
      code: 0, msg: 'ok',
      data: { ok: true, text: '', rawText: '', hotwordFixes: [],
              durationMs: 3000, provider: 'xfyun', credentialSource: '测试桩',
              hotwordCount: 0, chunkCount: 1 },
    },
    error: {
      code: 5032,
      msg: '讯飞返回错误 10114：session timeout（单次会话超过 60 秒上限，录音太长，请分段说）',
      data: { ok: false, asrUnavailable: true, permanent: false, text: '',
              error: '讯飞返回错误 10114：session timeout' },
    },
  }
  const canned = RESPONSES[scenario] || RESPONSES.success

  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1400,900'],
  })
  const page = await browser.newPage()

  const consoleErrors = []
  const pageErrors = []
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text())
  })
  page.on('pageerror', (e) => pageErrors.push(String(e)))

  // 拦截 ASR 请求，返回固定成功响应：只测前端回填，不受 ASR 质量影响
  let asrCalled = 0
  let asrRequestBody = ''
  await page.setRequestInterception(true)
  page.on('request', (req) => {
    if (req.url().includes('/api/asr/transcribe')) {
      asrCalled++
      asrRequestBody = req.postData() ? `(form-data ${req.postData().length} 字节)` : '(无 body)'
      req.respond({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(canned),
      })
      return
    }
    req.continue()
  })

  await page.evaluateOnNewDocument(STUB_RECORDER)
  // 预置模式：用户浏览器里可能选了点按模式，两种都要覆盖
  await page.evaluateOnNewDocument((m) => {
    window.localStorage.setItem('beibei.voice.mode', m)
  }, mode)

  console.log('='.repeat(74))
  console.log(`  真机测试：语音识别结果是否回填到输入框`)
  console.log('='.repeat(74))
  console.log(`  页面：${url}`)
  console.log(`  浏览器：${path.basename(chromePath)}   模式：${mode === 'toggle' ? '点按' : '长按'}   场景：${scenario}`)
  console.log()

  await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 })
  await new Promise((r) => setTimeout(r, 1500))

  // 找到语音按钮
  const buttonInfo = await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button'))
    const mic = btns.find((b) => /按住说话|点击说话|松开发送|点击结束|识别中/.test(b.textContent || ''))
    if (!mic) return null
    return {
      text: (mic.textContent || '').trim(),
      disabled: mic.disabled,
      title: mic.getAttribute('title') || '',
    }
  })
  if (!buttonInfo) {
    console.log('  ❌ 页面上找不到语音按钮')
    console.log('     可能这个面试的最后一轮是候选人回答，输入区被禁用了')
    await browser.close()
    return 1
  }
  console.log(`  找到语音按钮：「${buttonInfo.text}」 disabled=${buttonInfo.disabled}`)

  // 找到输入框
  const textareaSel = 'textarea'
  const before = await page.$eval(textareaSel, (el) => el.value).catch(() => null)
  console.log(`  点击前 textarea = ${JSON.stringify(before)}`)
  console.log()

  // 点它（长按模式要 mousedown+mouseup；点按模式点一下再点一下）
  const isToggle = buttonInfo.text.includes('点击说话')
  console.log(`  模式判定：${isToggle ? '点按模式' : '长按模式'}`)

  const micBox = await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button'))
    const mic = btns.find((b) => /按住说话|点击说话/.test(b.textContent || ''))
    const r = mic.getBoundingClientRect()
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 }
  })

  if (isToggle) {
    await page.mouse.click(micBox.x, micBox.y)
    await new Promise((r) => setTimeout(r, 900))
    const mid = await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll('button'))
        .find((x) => /松开|点击结束|识别中/.test(x.textContent || ''))
      return b ? b.textContent.trim() : '(没找到录音中的按钮)'
    })
    console.log(`  第 1 次点击后按钮文案：${mid}`)
    await page.mouse.click(micBox.x, micBox.y)
  } else {
    await page.mouse.move(micBox.x, micBox.y)
    await page.mouse.down()
    await new Promise((r) => setTimeout(r, 900))
    const mid = await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll('button'))
        .find((x) => /松开|点击结束|识别中/.test(x.textContent || ''))
      return b ? b.textContent.trim() : '(没找到录音中的按钮)'
    })
    console.log(`  按下后按钮文案：${mid}`)
    await page.mouse.up()
  }

  // 等识别回来并回填
  await new Promise((r) => setTimeout(r, 2500))

  const after = await page.$eval(textareaSel, (el) => el.value).catch(() => null)
  console.log()
  console.log('='.repeat(74))
  console.log('  结果')
  console.log('='.repeat(74))
  console.log(`  ASR 请求次数     : ${asrCalled}  ${asrRequestBody}`)
  console.log(`  点击前 textarea  : ${JSON.stringify(before)}`)
  console.log(`  点击后 textarea  : ${JSON.stringify(after)}`)

  const ok = after && after.includes(FAKE_TEXT)
  console.log(`  回填成功         : ${ok ? '✅ 是' : '❌ 否'}`)

  if (pageErrors.length) {
    console.log()
    console.log('  🔴 页面 JS 异常（这些通常就是「什么都不显示」的原因）：')
    pageErrors.forEach((e) => console.log(`     ${e.split('\n')[0]}`))
  }
  if (consoleErrors.length) {
    console.log()
    console.log('  控制台 error：')
    consoleErrors.slice(0, 10).forEach((e) => console.log(`     ${e.slice(0, 200)}`))
  }

  // 顺便看一眼页面上有没有 el-message 提示
  const toasts = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.el-message')).map((n) => (n.textContent || '').trim()))
  if (toasts.length) {
    console.log()
    console.log('  页面上的提示条：')
    toasts.forEach((t) => console.log(`     ${t}`))
  }

  await page.screenshot({ path: path.join(ROOT, 'beibei-web', 'node_modules', '.tmp', 'voice-e2e.png') })
  await browser.close()
  return ok ? 0 : 1
}

main().then((c) => process.exit(c)).catch((e) => {
  console.error('测试脚本异常：', e)
  process.exit(2)
})
