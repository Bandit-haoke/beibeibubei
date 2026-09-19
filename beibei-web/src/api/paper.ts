import { get, post, put, del } from '@/api/request'
import type { TagBrief } from '@/api/doc'

// ============================== 题卷 ==============================

export interface PaperVO {
  id: number
  kbId: number
  title: string
  source: number
  totalCount: number
  totalScore: number
  durationLimit: number
  status: number
  genSummary: Record<string, number | string> | null
  draftCount: number
  publishedCount: number
  createdAt: string
}

export interface PaperDetail {
  paper: PaperVO
  questions: QuestionVO[]
}

export interface GenerateReq {
  kbId: number
  title?: string
  count: number
  tagIds?: number[]
  includeChildTags?: boolean
  qTypeRatio?: Record<string, number>
  difficultyRatio?: Record<string, number>
  selfCheck?: boolean
}

export interface GenerateResult {
  paperId: number
  taskId: number
}

export const PAPER_STATUS: Record<number, { text: string; type: 'info' | 'warning' | 'success' | 'danger' }> = {
  0: { text: '生成中', type: 'warning' },
  1: { text: '待审核', type: 'warning' },
  2: { text: '可用', type: 'success' },
  3: { text: '生成失败', type: 'danger' },
}

export function generatePaper(data: GenerateReq) {
  return post<GenerateResult>('/paper/generate', data)
}

export function listPapers(kbId?: number) {
  return get<PaperVO[]>('/paper/list', kbId ? { kbId } : undefined)
}

export function getPaper(id: number) {
  return get<PaperDetail>(`/paper/${id}`)
}

export function getPaperReview(id: number) {
  return get<PaperDetail>(`/paper/${id}/review`)
}

export function approveAll(paperId: number) {
  return post<number>(`/paper/${paperId}/approve-all`)
}

export function regeneratePaper(paperId: number, count?: number) {
  return post<GenerateResult>(`/paper/${paperId}/regenerate`, undefined, {
    params: { count, selfCheck: true },
  })
}

export function deletePaper(paperId: number, withQuestions = true) {
  return del<void>(`/paper/${paperId}`, { withQuestions })
}

// ============================== 题目 ==============================

export interface OptionVO {
  id: number
  key: string
  content: string
  correct: boolean
}

export interface QuestionVO {
  id: number
  kbId: number
  qType: number
  qTypeName: string
  difficulty: number
  difficultyName: string
  stem: string
  answer: string
  analysis: string
  rubric: Array<{ point: string; score: number }> | null
  codeSnippet: string | null
  options: OptionVO[]
  tags: TagBrief[]
  sourceChunkIds: number[]
  status: number
  origin: number
  genBatchId: string
  qualityScore: number | null
  selfCheckMsg: string
  createdAt: string
}

export interface QuestionPage {
  total: number
  list: QuestionVO[]
  pageNum: number
  pageSize: number
}

export const Q_TYPE_OPTIONS = [
  { value: 1, label: '单选题' },
  { value: 2, label: '多选题' },
  { value: 3, label: '判断题' },
  { value: 4, label: '填空题' },
  { value: 5, label: '名词解释' },
  { value: 6, label: '简答题' },
  { value: 7, label: '论述题' },
  { value: 8, label: '代码题' },
  { value: 9, label: '对比辨析' },
]

export const QUESTION_STATUS: Record<number, { text: string; type: 'info' | 'success' | 'danger' }> = {
  0: { text: '待审', type: 'info' },
  1: { text: '已发布', type: 'success' },
  2: { text: '已停用', type: 'danger' },
}

export function listQuestions(params: {
  kbId?: number
  status?: number
  qType?: number
  difficulty?: number
  tagId?: number
  keyword?: string
  pageNum?: number
  pageSize?: number
}) {
  return get<QuestionPage>('/question/list', params as Record<string, unknown>)
}

/**
 * 更新题目。
 *
 * options 刻意**不含 id**：选项在服务端是整组重建的，前端提交时不带 id，
 * 所以这里不能直接用 Partial<QuestionVO>（那会要求每个选项都有 id，编译不过）。
 */
export function updateQuestion(
  id: number,
  data: Partial<Omit<QuestionVO, 'options'>> & {
    tagIds?: number[]
    options?: { key: string; content: string; correct: boolean }[]
  },
) {
  return put<void>(`/question/${id}`, data)
}

export function approveQuestions(questionIds: number[]) {
  return post<number>('/question/approve', { questionIds })
}

export function disableQuestion(id: number) {
  return post<void>(`/question/${id}/disable`)
}

export function deleteQuestion(id: number) {
  return del<void>(`/question/${id}`)
}
