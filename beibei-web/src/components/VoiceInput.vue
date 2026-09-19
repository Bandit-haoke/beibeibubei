<script setup lang="ts">
/**
 * 语音输入：按住说话（或点按）→ 录音 → 上传转写 → 回填文本
 *
 * ── 空格快捷键的设计取舍（这是本组件最容易做错的地方）──────────────────
 * 答题页和面试室**都有输入框**，用户在输入框里按空格是「打一个空格」，
 * 而中文输入法更是拿空格**选候选词**。所以快捷键必须躲开这两种情况，
 * 否则就会出现「我想打字，结果开始录音」这种灾难性体验。
 *
 * 触发规则（三层防御）：
 *   1. 焦点在 input / textarea / select / contenteditable 里 → **完全不接管**，空格照常输入
 *   2. 输入法组合中（isComposing / keyCode 229）→ 不接管，让输入法去选词
 *   3. 其余情况（焦点在页面空白处、按钮上）→ 接管，并 preventDefault
 *      防止空格滚动页面或「点」到当前聚焦的按钮
 *
 * 代价：本组件挂载期间，空格不再能「激活」聚焦的按钮（Tab 之后按回车仍然可以）。
 * 在这两个页面上「空格=说话」才是用户预期，所以接受这个代价。
 *
 * ── 两种模式 ────────────────────────────────────────────────────────
 *   长按模式：按住空格/鼠标说话，松开即发送（微信那种手感）
 *   点按模式：按一下开始，再按一下结束（长回答更省力，不用一直按着）
 * 用按钮右侧的小标签切换，选择记在 localStorage 里，两个页面共用。
 *
 * 另外还有：
 *   - **快按竞态**：授权弹窗还没点完用户就松手了，此时不能再进入录音态（否则永远停不下来）
 *   - **Esc 取消**：录到一半发现说错了，按 Esc 直接丢弃，不发请求
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { transcribe } from '@/api/exam'
import { decideSpace, isTextEntry } from '@/utils/voiceShortcut'

const props = defineProps<{
  kbId: number
  disabled?: boolean
  maxSeconds?: number
  /** 是否启用空格快捷键（默认启用） */
  shortcut?: boolean
}>()

const emit = defineEmits<{
  (e: 'text', text: string): void
}>()

type VoiceMode = 'hold' | 'toggle'

const MODE_KEY = 'beibei.voice.mode'

// ---------------------------------------------------------------------------
//  状态
// ---------------------------------------------------------------------------

const recording = ref(false)
const uploading = ref(false)
/** 服务端确认 ASR 不可用后置为 true，按钮直接隐藏 */
const unavailable = ref(false)
const seconds = ref(0)
/** 快捷键当前是否处于「可触发」状态（焦点不在输入框里）——只用于界面提示 */
const armed = ref(true)

/**
 * 模式用**模块级**状态而不是组件内 ref：
 * 换页面时组件会重新挂载，模块级 state 能让选择在两个页面之间保持一致，
 * 不用等 localStorage 读回来。
 */
const mode = ref<VoiceMode>(
  (localStorage.getItem(MODE_KEY) as VoiceMode) === 'toggle' ? 'toggle' : 'hold',
)

/**
 * 空格键的归属者。
 * 一页只应该有一个实例响应快捷键；万一以后某页放了两个，
 * 也不会出现「按一次空格两个录音器同时启动」。
 */
let shortcutOwner: symbol | null = null
const instanceId = Symbol('voice-input')

function switchMode() {
  if (recording.value) stop()   // 切模式时正在录，先收尾，避免状态错乱
  mode.value = mode.value === 'hold' ? 'toggle' : 'hold'
  localStorage.setItem(MODE_KEY, mode.value)
  ElMessage.success(mode.value === 'hold' ? '已切换为长按模式' : '已切换为点按模式')
}

let mediaRecorder: MediaRecorder | null = null
let chunks: Blob[] = []
let timer: number | null = null
let cancelled = false
/**
 * 本次录音实际用的麦克风设备名。
 * 「录到静音」最常见的原因就是浏览器选了错误的设备（蓝牙耳机 / Stereo Mix / 虚拟声卡），
 * 把设备名一起传给后端，日志里就能直接看到，不用让用户自己去猜。
 */
let micLabel = ''
/**
 * 用户「还想录」的意图标记。
 *
 * 不加这个会有一个隐蔽的竞态：长按模式下一次很快的点按，
 * 权限弹窗还没处理完用户就松手了，stop() 时 mediaRecorder 还是 null 什么也没停，
 * 等 getUserMedia 的 Promise 回来又把 recording 置成 true —— 按钮就卡在录音态了。
 */
let wantRecording = false

const limit = computed(() => props.maxSeconds ?? 60)
const shortcutOn = computed(() => props.shortcut !== false)

const label = computed(() => {
  if (unavailable.value) return '语音不可用'
  if (uploading.value) return '识别中 ...'
  if (recording.value) {
    return mode.value === 'hold'
      ? `松开发送 ${seconds.value}s / ${limit.value}s`
      : `点击结束 ${seconds.value}s / ${limit.value}s`
  }
  return mode.value === 'hold' ? '按住说话' : '点击说话'
})

const keyHint = computed(() => (mode.value === 'hold' ? '按住空格' : '空格切换'))

function clearTimer() {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

/**
 * 焦点是否落在「会吃掉空格」的元素上。
 * 具体规则见 @/utils/voiceShortcut —— 抽成纯函数是为了能脱离浏览器做单元测试。
 */
function isTextEntryTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  return isTextEntry(el.tagName, (el as HTMLInputElement).type, el.isContentEditable)
}

/** 由真实事件 + 组件状态拼出判定上下文 */
function spaceContext(e: KeyboardEvent): Parameters<typeof decideSpace>[0] {
  const el = e.target instanceof HTMLElement ? e.target : null
  return {
    key: e.key,
    code: e.code,
    repeat: e.repeat,
    isComposing: e.isComposing,
    keyCode: e.keyCode,
    targetTag: el?.tagName ?? '',
    targetType: el instanceof HTMLInputElement ? el.type : undefined,
    targetContentEditable: el?.isContentEditable ?? false,
    disabled: !!props.disabled,
    unavailable: unavailable.value,
    shortcutOn: shortcutOn.value,
    isOwner: shortcutOwner === instanceId,
  }
}

function refreshArmed() {
  armed.value = !isTextEntryTarget(document.activeElement)
}

async function start() {
  if (props.disabled || uploading.value || unavailable.value || recording.value) return

  if (!navigator.mediaDevices?.getUserMedia) {
    unavailable.value = true
    ElMessage.warning('当前浏览器不支持录音，请手动输入')
    return
  }

  wantRecording = true

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    })

    // 授权期间用户已经松手/切走了，就别再进录音态
    if (!wantRecording) {
      stream.getTracks().forEach((t) => t.stop())
      return
    }

    // 记下设备名与轨道参数：排查「录到静音」时第一个要看的就是它
    const track = stream.getAudioTracks()[0]
    if (track) {
      const s = track.getSettings ? track.getSettings() : {}
      micLabel = track.label || '(无设备名)'
      console.info('[语音] 使用麦克风：%s  采样率=%s 声道=%s 自动增益=%s',
        micLabel, s.sampleRate, s.channelCount, s.autoGainControl)
    }

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm'
    mediaRecorder = new MediaRecorder(stream, { mimeType })
    chunks = []
    cancelled = false

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data)
    }
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop())
      clearTimer()
      recording.value = false

      if (cancelled || !chunks.length) return
      const blob = new Blob(chunks, { type: mimeType })
      if (blob.size < 2000) {
        ElMessage.warning('录音太短了')
        return
      }
      await upload(blob)
    }

    mediaRecorder.start(200)
    recording.value = true
    seconds.value = 0
    timer = window.setInterval(() => {
      seconds.value += 1
      if (seconds.value >= limit.value) stop()
    }, 1000)
  } catch (e) {
    wantRecording = false
    unavailable.value = true
    ElMessage.warning('无法访问麦克风（可能是浏览器权限或非安全上下文），请手动输入')
  }
}

function stop() {
  wantRecording = false
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
  }
  clearTimer()
  recording.value = false
}

function cancel() {
  cancelled = true
  stop()
  ElMessage.info('已取消录音')
}

/** 点按模式下的开/关 */
function toggle() {
  if (recording.value) stop()
  else void start()
}

/** 上传音频并回填识别结果（转写失败不阻塞用户，提示后仍可打字） */
async function upload(blob: Blob) {
  uploading.value = true
  try {
    const res = await transcribe(blob, props.kbId, 'answer.webm', micLabel)
    if (res?.asrUnavailable) {
      unavailable.value = true
      ElMessage.warning(res.hint || '语音服务不可用，请手动输入')
      return
    }
    const text = (res?.text || '').trim()
    if (!text) {
      ElMessage.warning('没有识别到内容，请靠近麦克风重试')
      return
    }
    emit('text', text)

    const fixes = res.hotwordFixes || []
    if (fixes.length) {
      ElMessage.success(`识别完成，已自动纠正 ${fixes.length} 处术语：` +
        fixes.map((f) => `${f.from}→${f.to}`).join('、'))
    } else {
      ElMessage.success('识别完成')
    }
  } catch {
    // request.ts 已经弹过提示
  } finally {
    uploading.value = false
  }
}

// ---------------------------------------------------------------------------
//  鼠标
// ---------------------------------------------------------------------------

function onPointerDown(e: MouseEvent) {
  if (e.button !== 0) return
  if (mode.value === 'hold') void start()
}

function onPointerUp() {
  if (mode.value === 'hold' && recording.value) stop()
}

function onPointerLeave() {
  // 长按途中把鼠标拖出按钮 = 放弃这一句
  if (mode.value === 'hold' && recording.value) stop()
}

function onButtonClick() {
  if (mode.value === 'toggle') toggle()
}

// ---------------------------------------------------------------------------
//  键盘
// ---------------------------------------------------------------------------

function onKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (recording.value) {
      e.preventDefault()
      cancel()
    }
    return
  }

  const decision = decideSpace(spaceContext(e))
  if (!decision.capture) return

  // 接管就要阻止默认行为：否则空格会滚动页面，或「点」掉当前聚焦的按钮
  e.preventDefault()
  if (!decision.act) return

  if (mode.value === 'hold') {
    void start()
  } else {
    toggle()
  }
}

function onKeyUp(e: KeyboardEvent) {
  if (e.code !== 'Space' && e.key !== ' ') return
  if (e.isComposing || e.keyCode === 229) return
  if (isTextEntryTarget(e.target)) return
  if (shortcutOwner !== instanceId) return

  // 松手也要拦：否则空格会在 keyup 时触发聚焦按钮的 click
  e.preventDefault()

  if (mode.value === 'hold' && recording.value) stop()
}

onMounted(() => {
  // 先挂载的实例拿到快捷键所有权
  shortcutOwner ??= instanceId
  document.addEventListener('keydown', onKeyDown)
  document.addEventListener('keyup', onKeyUp)
  document.addEventListener('focusin', refreshArmed)
  document.addEventListener('focusout', refreshArmed)
  refreshArmed()
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeyDown)
  document.removeEventListener('keyup', onKeyUp)
  document.removeEventListener('focusin', refreshArmed)
  document.removeEventListener('focusout', refreshArmed)
  if (shortcutOwner === instanceId) shortcutOwner = null
  cancelled = true
  stop()
})
</script>

<template>
  <div v-if="!unavailable" class="voice-input">
    <el-button
      :type="recording ? 'danger' : 'default'"
      :disabled="disabled || uploading"
      :loading="uploading"
      size="small"
      @mousedown.prevent="onPointerDown"
      @mouseup.prevent="onPointerUp"
      @mouseleave="onPointerLeave"
      @click="onButtonClick"
    >
      <el-icon style="margin-right: 4px"><Microphone /></el-icon>
      {{ label }}
    </el-button>

    <el-button v-if="recording" link size="small" @click="cancel">取消</el-button>

    <!-- 模式切换：两个页面共用一个选择 -->
    <el-tooltip
      :content="mode === 'hold'
        ? '长按说话：按住空格或鼠标，松开即发送。点这里切换为点按模式'
        : '点按说话：按一下空格开始，再按一下结束。点这里切换为长按模式'"
      placement="top"
    >
      <span class="mode-switch" @click="switchMode">
        {{ mode === 'hold' ? '长按' : '点按' }}
      </span>
    </el-tooltip>

    <!-- 快捷键提示：焦点在输入框里时变灰，说明此刻空格是打字用的 -->
    <el-tooltip
      v-if="shortcutOn"
      :content="armed
        ? `${keyHint} 说话；录音中按 Esc 取消`
        : '光标在输入框里时空格用于打字。点一下页面空白处，快捷键即可生效'"
      placement="top"
    >
      <kbd class="key-hint" :class="{ 'key-hint-off': !armed }">Space</kbd>
    </el-tooltip>
  </div>
  <span v-else class="voice-disabled">语音暂不可用，请手动输入</span>
</template>

<style scoped>
.voice-input {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.voice-disabled {
  font-size: 12px;
  color: #cbd5e1;
}

.mode-switch {
  font-size: 12px;
  color: #4c7cf3;
  cursor: pointer;
  padding: 1px 7px;
  border: 1px solid #c7d7fb;
  border-radius: 4px;
  background: #f2f6ff;
  user-select: none;
  line-height: 18px;
}

.mode-switch:hover {
  background: #e6eeff;
}

.key-hint {
  font-family: inherit;
  font-size: 11px;
  color: #475569;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-bottom-width: 2px;
  border-radius: 4px;
  padding: 1px 6px;
  user-select: none;
}

.key-hint-off {
  color: #cbd5e1;
  background: #f8fafc;
  border-color: #f1f5f9;
}
</style>
