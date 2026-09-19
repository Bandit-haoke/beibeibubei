import { del, get, post } from '@/api/request'

/**
 * AI 模拟面试接口。
 *
 * 两条链路：
 *  - 简历解析是异步的：上传 → 拿 taskId → 用 subscribeTask 订阅进度
 *  - 面试问答是同步的：一轮一次请求，后端调一次大模型
 */

// ---------------------------------------------------------------------------
//  简历库
// ---------------------------------------------------------------------------

export interface ResumeVO {
  id: number
  fileName: string
  fileType: string
  fileSize: number
  charCount: number
  targetPosition: string
  status: number
  errorMsg: string
  skillCount: number
  projectCount: number
  riskCount: number
  createdAt: string
  updatedAt: string
}

export interface ResumeProject {
  name: string
  role: string
  period: string
  techStack: string[]
  highlights: string[]
  evidence: string
}

export interface ResumeProfile {
  name: string
  years: number
  education: string
  school: string
  major: string
  currentCompany: string
  currentTitle: string
  targetPosition: string
  skills: string[]
  projects: ResumeProject[]
  workExperience: { company: string; title: string; period: string; duty: string }[]
  selfEvaluation: string
  highlights: string[]
  risks: string[]
}

export interface ResumeDetailVO {
  resume: ResumeVO
  profile: ResumeProfile
  rawText: string
}

export interface ResumeUploadResult {
  resumeId: number
  taskId: number
  fileName: string
  duplicated: boolean
  message: string
}

export const RESUME_STATUS = {
  0: { text: '待解析', type: 'info' as const },
  1: { text: '解析中', type: 'warning' as const },
  2: { text: '就绪', type: 'success' as const },
  3: { text: '解析失败', type: 'danger' as const },
}

export function listResumes() {
  return get<ResumeVO[]>('/resume/list')
}

export function getResume(id: number) {
  return get<ResumeDetailVO>(`/resume/${id}`)
}

export function deleteResume(id: number) {
  return del<void>(`/resume/${id}`)
}

export function reparseResume(id: number) {
  return post<number>(`/resume/${id}/reparse`)
}

export function pasteResume(data: {
  fileName?: string
  content: string
  targetPosition?: string
}) {
  return post<ResumeUploadResult>('/resume/paste', data)
}

/** 上传简历文件（multipart，字段名固定为 file） */
export function uploadResume(file: File) {
  const form = new FormData()
  form.append('file', file)
  return post<ResumeUploadResult>('/resume/upload', form, { timeout: 300_000 })
}

// ---------------------------------------------------------------------------
//  面试
// ---------------------------------------------------------------------------

export const QUESTION_TYPE = {
  INTRO: { text: '自我介绍', color: '#64748b' },
  PROJECT: { text: '项目深挖', color: '#4c7cf3' },
  TECH: { text: '原理考察', color: '#0ea5e9' },
  FOLLOWUP: { text: '追问', color: '#f59e0b' },
  SCENARIO: { text: '场景设计', color: '#8b5cf6' },
  BEHAVIOR: { text: '行为面', color: '#10b981' },
}

export const INTERVIEW_STATUS = {
  0: { text: '待开始', type: 'info' as const },
  1: { text: '进行中', type: 'warning' as const },
  2: { text: '已结束', type: 'success' as const },
  3: { text: '失败', type: 'danger' as const },
}

export const DIFFICULTY = {
  1: '初级',
  2: '中级',
  3: '高级',
}

export interface QuestionVO {
  question: string
  type: string
  basedOn: string
  expects: string[]
  turnNo: number
}

export interface EvaluationVO {
  score: number
  scores: Record<string, number>
  dimensionLabels: Record<string, string>
  goodPoints: string[]
  problems: string[]
  suggestion: string
  contradiction: string
  followUpNeeded: boolean
}

export interface StartVO {
  interviewId: number
  jobTitle: string
  difficulty: number
  maxTurns: number
  turnCount: number
  question: QuestionVO
}

export interface AnswerVO {
  interviewId: number
  turnCount: number
  maxTurns: number
  finished: boolean
  evaluation: EvaluationVO
  nextQuestion: QuestionVO | null
}

export interface TurnVO {
  id: number
  seq: number
  role: number
  content: string
  questionType: string
  basedOn: string
  expects: string[]
  score: number | null
  feedback: EvaluationVO | null
  createdAt: string
}

export interface InterviewVO {
  id: number
  resumeId: number
  resumeName: string
  kbId: number | null
  kbName: string
  jobTitle: string
  difficulty: number
  maxTurns: number
  turnCount: number
  status: number
  totalScore: number | null
  summary: string
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
}

export interface WeakPoint {
  skill: string
  level: string
  evidence: string
  suggestion: string
}

export interface InterviewReport {
  overallScore: number
  summary: string
  dimensions: { name: string; score: number; comment: string }[]
  strengths: string[]
  weakPoints: WeakPoint[]
  knowledgePoints: string[]
  nextSteps: string[]
  turnScores: { seq: number; score: number }[]
}

export interface InterviewDetailVO {
  interview: InterviewVO
  turns: TurnVO[]
  report: InterviewReport | Record<string, never>
}

export interface LinkageVO {
  paperId: number
  taskId: number
  kbId: number
  kbName: string
  matchedTags: string[]
  unmatchedPoints: string[]
  count: number
  message: string
}

export function listInterviews() {
  return get<InterviewVO[]>('/interview/list')
}

export function getInterview(id: number) {
  return get<InterviewDetailVO>(`/interview/${id}`)
}

export function startInterview(data: {
  resumeId: number
  jobTitle?: string
  kbId?: number | null
  difficulty?: number
  maxTurns?: number
}) {
  return post<StartVO>('/interview/start', data, { timeout: 180_000 })
}

export function answerInterview(id: number, answer: string) {
  return post<AnswerVO>(`/interview/${id}/answer`, { answer }, { timeout: 180_000 })
}

export function finishInterview(id: number) {
  return post<InterviewDetailVO>(`/interview/${id}/finish`, undefined, { timeout: 300_000 })
}

export function deleteInterview(id: number) {
  return del<void>(`/interview/${id}`)
}

/** 按报告里的薄弱知识点生成专项题卷 */
export function createLinkagePaper(
  id: number,
  data: { kbId?: number | null; tagIds?: number[]; count?: number; selfCheck?: boolean },
) {
  return post<LinkageVO>(`/interview/${id}/linkage-paper`, data, { timeout: 180_000 })
}
