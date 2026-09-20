import { del, get, post, put } from '@/api/request'

/**
 * 面经接口。
 *
 * 与「模拟面试」的区别（很容易搞混，这里再写一遍）：
 *  - 模拟面试：本工具<扮演>面试官，跟用户对话，内容由 AI 生成；
 *  - 面经：用户上传<真实发生过>的面试录音，AI 只负责整理成文。
 *
 * 上传是异步的：拿 taskId 后用 subscribeTask 订阅「转写 → 分角色 → 清洗 → 成文」的进度。
 */

export interface NoteVO {
  id: number
  title: string
  company: string
  position: string
  fileName: string
  fileType: string
  fileSize: number
  durationMs: number
  /** LFASR = 讯飞语音转写（原生角色分离）；IAT = 语音听写降级 */
  engine: string
  /** LFASR = 引擎分离；LLM = 大模型推断 */
  roleSource: string
  status: number
  progress: number
  stage: string
  turnCount: number
  questionCount: number
  speakerCount: number
  summary: string
  errorMsg: string
  createdAt: string
}

export interface TurnVO {
  seq: number
  /** 1 面试官 2 我 */
  role: number
  startMs: number
  endMs: number
  /** 已清洗的文本（清洗后为空时后端会退回原文） */
  text: string
  /** 转写原文，用于对比 AI 洗掉了什么 */
  rawText: string
  removedWords: string
  questionType: string
}

export interface NoteQuestion {
  question: string
  answer: string
  category: string
}

export interface NoteDetailVO {
  note: NoteVO
  turns: TurnVO[]
  questions: NoteQuestion[]
  highlights: string[]
  content: string
}

export interface NoteUploadResult {
  noteId: number
  taskId: number
  fileName: string
  message: string
}

/** 0 待处理 1 转写中 2 转写完成 3 生成中 4 完成 9 失败 */
export const NOTE_STATUS = {
  0: { text: '排队中', type: 'info' as const },
  1: { text: '转写中', type: 'warning' as const },
  2: { text: '已转写', type: 'warning' as const },
  3: { text: '生成中', type: 'warning' as const },
  4: { text: '已完成', type: 'success' as const },
  9: { text: '失败', type: 'danger' as const },
}

export const ROLE_LABEL: Record<number, string> = {
  1: '面试官',
  2: '我',
}

export const QUESTION_CATEGORY_COLOR: Record<string, string> = {
  自我介绍: '#64748b',
  项目经历: '#4c7cf3',
  技术原理: '#0ea5e9',
  场景设计: '#8b5cf6',
  算法: '#f59e0b',
  反问环节: '#10b981',
  其他: '#94a3b8',
}

/** 上传面试录音（multipart，字段名固定为 file） */
export function uploadNote(file: File, company = '', position = '') {
  const form = new FormData()
  form.append('file', file)
  if (company) form.append('company', company)
  if (position) form.append('position', position)
  // 录音可能几十上百 MB，上传本身也要给足时间
  return post<NoteUploadResult>('/interview-note/upload', form, { timeout: 600_000 })
}

export function listNotes() {
  return get<NoteVO[]>('/interview-note/list')
}

export function getNote(id: number) {
  return get<NoteDetailVO>(`/interview-note/${id}`)
}

export function updateNote(id: number, data: { title?: string; company?: string; position?: string }) {
  return put<NoteVO>(`/interview-note/${id}`, data)
}

export function retryNote(id: number) {
  return post<number>(`/interview-note/${id}/retry`)
}

export function deleteNote(id: number) {
  return del<void>(`/interview-note/${id}`)
}

/** 毫秒 → 「12 分 34 秒」 */
export function durationText(ms: number): string {
  if (!ms || ms <= 0) return '-'
  const total = Math.round(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return m > 0 ? `${m} 分 ${s} 秒` : `${s} 秒`
}

/** 毫秒 → 「03:25」，用于逐句时间轴 */
export function stampText(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000))
  const m = String(Math.floor(total / 60)).padStart(2, '0')
  const s = String(total % 60).padStart(2, '0')
  return `${m}:${s}`
}
