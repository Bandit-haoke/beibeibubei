import { get, post } from '@/api/request'
import type { OptionVO, QuestionVO } from '@/api/paper'
import type { TagBrief } from '@/api/doc'

// ============================== 答题 ==============================

export interface ExamQuestion {
  questionId: number
  qType: number
  qTypeName: string
  difficulty: number
  difficultyName: string
  stem: string
  codeSnippet: string | null
  options: OptionVO[]
  fullScore: number
  sortOrder: number
  savedAnswer: string
  savedInputMode: number
}

export interface StartResult {
  examId: number
  paperId: number
  kbId: number
  title: string
  examMode: number
  status: number
  durationLimit: number
  totalScore: number
  questionCount: number
  startedAt: string
  questions: ExamQuestion[]
}

export interface AnswerPayload {
  questionId: number
  userAnswer: string
  asrText?: string
  inputMode?: number
}

export function startExam(paperId: number, examMode = 2) {
  return post<StartResult>('/exam/start', { paperId, examMode, onlyPublished: true })
}

export function saveDraft(examId: number, answers: AnswerPayload[], durationSec: number) {
  return post<void>(`/exam/${examId}/save-draft`, { answers, durationSec })
}

export function submitExam(examId: number, answers: AnswerPayload[], durationSec: number) {
  return post<number>(`/exam/${examId}/submit`, { answers, durationSec })
}

// ============================== 判分结果 ==============================

export interface RubricPoint {
  point: string
  score?: number
  hint?: string
  correction?: string
}

export interface Citation {
  chunkId: number
  pageNo: number
  sectionPath: string
  quote: string
  snippet: string
}

export interface ItemResult {
  answerItemId: number
  questionId: number
  qType: number
  qTypeName: string
  stem: string
  codeSnippet: string | null
  options: OptionVO[]
  userAnswer: string
  asrText: string | null
  inputMode: number
  score: number
  fullScore: number
  hitPoints: RubricPoint[]
  missPoints: RubricPoint[]
  wrongPoints: RubricPoint[]
  citations: Citation[]
  aiFeedback: string
  gradeMethod: number
  gradeMethodName: string
  referenceAnswer: string | null
  analysis: string | null
  tags: TagBrief[]
  appealStatus: number
  appealReason: string
  appealScore: number | null
  appealResult: RubricPoint[]
}

export interface ExamResult {
  examId: number
  paperId: number
  kbId: number
  title: string
  status: number
  examMode: number
  totalScore: number
  gotScore: number
  scoreRate: number
  correctCount: number
  wrongCount: number
  durationSec: number
  startedAt: string
  submittedAt: string | null
  gradedAt: string | null
  items: ItemResult[]
}

export interface ExamListItem {
  id: number
  paperId: number
  kbId: number
  title: string
  status: number
  statusName: string
  examMode: number
  totalScore: number
  gotScore: number
  scoreRate: number
  correctCount: number
  wrongCount: number
  durationSec: number
  startedAt: string
  submittedAt: string | null
}

export function getExamResult(examId: number) {
  return get<ExamResult>(`/exam/${examId}/result`)
}

export function listExams(kbId?: number) {
  return get<ExamListItem[]>('/exam/list', kbId ? { kbId } : undefined)
}

export function appeal(answerItemId: number, reason: string) {
  return post<number>(`/answer/${answerItemId}/appeal`, { reason })
}

// ============================== 语音 ==============================

export interface AsrResult {
  ok: boolean
  text: string
  rawText?: string
  hotwordFixes?: Array<{ from: string; to: string; score: string }>
  durationMs?: number
  provider?: string
  asrUnavailable?: boolean
  error?: string
  hint?: string
}

export function transcribe(
  audio: Blob,
  kbId: number,
  filename = 'answer.webm',
  /** 麦克风设备名。上报给后端是为了排查「录到静音」——先要知道用的是哪个设备 */
  micLabel = '',
) {
  const form = new FormData()
  form.append('audio', audio, filename)
  form.append('kbId', String(kbId))
  if (micLabel) form.append('micLabel', micLabel)
  form.append('applyHotwords', 'true')
  return post<AsrResult>('/asr/transcribe', form)
}

export function correctHotwords(text: string, kbId: number) {
  return post<{
    original: string
    corrected: string
    fixes: Array<{ from: string; to: string; score: string }>
    hotwordCount: number
  }>('/asr/correct-hotwords', { text, kbId })
}
