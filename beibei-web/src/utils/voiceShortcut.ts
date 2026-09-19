/**
 * 语音输入的空格快捷键 —— 判定逻辑。
 *
 * 为什么单独抽出来：
 * 这是本次改动里**风险最高**的行为。答题页和面试室都有输入框，
 * 中文输入法还用空格选候选词。一旦判错，用户会遇到
 * 「我想打空格，结果开始录音」或者「输入法选词时弹出录音」这种灾难性体验。
 *
 * 而这种判定恰恰**不需要浏览器**就能测：它只依赖几个原始字段
 * （标签名、input 的 type、是否 contenteditable、是否输入法组合中…）。
 * 所以把它做成纯函数，配一个 Node 单元测试，
 * 比"手工在浏览器里点一遍"可靠得多，也能防止以后改坏。
 */

/** 一次空格按键的全部判定依据 */
export interface SpaceContext {
  /** KeyboardEvent.key */
  key: string
  /** KeyboardEvent.code —— 用 code 判断更稳，不受键盘布局影响 */
  code: string
  /** 按住不放时的连续触发 */
  repeat: boolean
  /** 输入法正在组合（中文输入法用空格选候选词，绝不能抢） */
  isComposing: boolean
  /** 部分浏览器/输入法只给 keyCode 229 */
  keyCode: number
  /** 事件目标的标签名（大写，来自 tagName） */
  targetTag: string
  /** 事件目标若是 input，它的 type */
  targetType?: string
  /** 事件目标是否 contenteditable */
  targetContentEditable?: boolean
  /** 组件 disabled 状态（例如面试室还没轮到回答） */
  disabled: boolean
  /** 服务端已确认 ASR 不可用 */
  unavailable: boolean
  /** 是否启用了空格快捷键 */
  shortcutOn: boolean
  /** 本实例是否持有快捷键所有权（一页只应有一个响应） */
  isOwner: boolean
}

/** 判定结果 */
export interface SpaceDecision {
  /** 是否接管这个事件。接管就必须 preventDefault，否则空格会滚页面／点掉聚焦的按钮 */
  capture: boolean
  /** 是否真正执行「开始 / 切换录音」 */
  act: boolean
  /** 不接管或不动手的原因，便于排查，也方便测试断言 */
  reason: string
}

const IGNORE = (reason: string): SpaceDecision => ({ capture: false, act: false, reason })
const SWALLOW = (reason: string): SpaceDecision => ({ capture: true, act: false, reason })
const HANDLE = (reason: string): SpaceDecision => ({ capture: true, act: true, reason })

/** 不吃空格的 input type（这些元素上空格是「点击」而不是「输入空格」） */
const NON_TEXT_INPUT_TYPES = ['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'file']

/**
 * 这个元素会不会把空格当文本吃掉。
 * 只判断**文本输入类**元素 —— 按钮不算：
 * 在这两个页面上「空格 = 说话」优先级高于「空格激活聚焦的按钮」，
 * Tab 之后按回车依然可以激活按钮。
 */
export function isTextEntry(
  tagName: string,
  inputType?: string,
  contentEditable?: boolean,
): boolean {
  if (contentEditable) return true
  const tag = (tagName || '').toUpperCase()
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (tag === 'INPUT') {
    const type = (inputType || 'text').toLowerCase()
    return !NON_TEXT_INPUT_TYPES.includes(type)
  }
  return false
}

/** 空格键判定主函数（纯函数，可单测） */
export function decideSpace(c: SpaceContext): SpaceDecision {
  if (c.key !== ' ' && c.code !== 'Space') return IGNORE('not-space')

  // —— 以下顺序不能调换：先排除「绝对不能抢」的情况，再看组件状态 ——
  if (c.isComposing || c.keyCode === 229) return IGNORE('ime-composing')
  if (isTextEntry(c.targetTag, c.targetType, c.targetContentEditable)) {
    return IGNORE('text-entry')
  }

  // 到这里说明焦点不在输入框里，空格该由我们处理；
  // 但组件当前不可用时，仍然要把空格吞掉，否则它会滚页面
  if (!c.shortcutOn) return IGNORE('shortcut-off')
  if (!c.isOwner) return IGNORE('not-owner')
  if (c.disabled || c.unavailable) return SWALLOW('voice-unavailable')

  if (c.repeat) return SWALLOW('repeat')

  return HANDLE('ok')
}
