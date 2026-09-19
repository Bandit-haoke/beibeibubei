import { get } from '@/api/request'

export interface Overview {
  kbCount: number
  docCount: number
  chunkCount: number
  questionCount: number
  publishedCount: number
  draftCount: number
  mistakeCount: number
  masteredCount: number
  todayDueCount: number
  todayReviewedCount: number
  totalExams: number
  gradedExams: number
  avgScoreRate: number
  streakDays: number
  totalAnswered: number
}

export interface RadarItem {
  tagId: number
  name: string
  level: number
  answered: number
  correct: number
  scoreRate: number
}

export interface TrendPoint {
  date: string
  examCount: number
  answered: number
  avgScoreRate: number
}

export interface CostItem {
  date: string
  vendor: string
  model: string
  calls: number
  failedCalls: number
  promptTokens: number
  completionTokens: number
  cost: number
  avgLatencyMs: number
}

export interface CostSummary {
  totalCalls: number
  totalTokens: number
  totalCost: number
  avgLatencyMs: number
  items: CostItem[]
}

export interface KbMastery {
  kbId: number
  name: string
  questionCount: number
  answeredCount: number
  scoreRate: number
}

export function getOverview() {
  return get<Overview>('/stat/overview')
}

export function getRadar(kbId: number) {
  return get<RadarItem[]>('/stat/radar', { kbId })
}

export function getTrend(days = 30) {
  return get<TrendPoint[]>('/stat/trend', { days })
}

export function getCost(days = 30) {
  return get<CostSummary>('/stat/cost', { days })
}

export function getKbMastery() {
  return get<KbMastery[]>('/stat/kb-mastery')
}
