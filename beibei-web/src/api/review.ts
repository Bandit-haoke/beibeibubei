import { get, post, del } from '@/api/request'
import type { TagBrief } from '@/api/doc'

export interface DueItem {
  mistakeId: number
  questionId: number
  kbId: number
  kbName: string
  qType: number
  qTypeName: string
  difficulty: number
  stem: string
  tags: TagBrief[]
  wrongCount: number
  rightStreak: number
  easeFactor: number
  intervalDays: number
  repetitions: number
  nextReviewAt: string
  overdueDays: number
}

export interface MistakeItem {
  id: number
  questionId: number
  kbId: number
  kbName: string
  qType: number
  qTypeName: string
  stem: string
  tags: TagBrief[]
  wrongCount: number
  rightStreak: number
  easeFactor: number
  intervalDays: number
  repetitions: number
  nextReviewAt: string
  lastWrongAt: string | null
  mastered: number
  stage: string
}

export interface StartReviewResult {
  paperId: number
  title: string
  count: number
  totalScore: number
  questionIds: number[]
}

export interface CalendarDay {
  date: string
  dueCount: number
  reviewedCount: number
}

export interface MistakePage {
  total: number
  list: MistakeItem[]
  pageNum: number
  pageSize: number
}

/** 掌握阶段 → 标签颜色 */
export const STAGE_TYPE: Record<string, 'danger' | 'warning' | 'primary' | 'success' | 'info'> = {
  新错题: 'danger',
  反复出错: 'danger',
  刚开始复习: 'warning',
  复习中: 'primary',
  接近掌握: 'success',
  已掌握: 'success',
}

export function getTodayDue(kbId?: number, limit = 50) {
  return get<DueItem[]>('/review/today', { kbId, limit })
}

export function startReview(kbId?: number, limit?: number) {
  return post<StartReviewResult>('/review/start', undefined, { params: { kbId, limit } })
}

export function getCalendar(pastDays = 60, futureDays = 14) {
  return get<CalendarDay[]>('/review/calendar', { pastDays, futureDays })
}

export function listMistakes(params: {
  kbId?: number
  mastered?: number
  tagId?: number
  pageNum?: number
  pageSize?: number
}) {
  return get<MistakePage>('/mistake/list', params as Record<string, unknown>)
}

export function markMastered(id: number, mastered = true) {
  return post<void>(`/mistake/${id}/mastered`, undefined, { params: { mastered } })
}

export function removeMistake(id: number) {
  return del<void>(`/mistake/${id}`)
}
