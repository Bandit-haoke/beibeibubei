import { get, post, put, del } from '@/api/request'

export interface KnowledgeBase {
  id: number
  name: string
  description: string
  coverColor: string
  embeddingModel: string
  milvusCollection: string
  chunkSize: number
  chunkOverlap: number
  docCount: number
  chunkCount: number
  questionCount: number
  status: number
  createdAt: string
  updatedAt: string
}

export interface KbStat {
  kbId: number
  docCount: number
  chunkCount: number
  questionCount: number
  tagCount: number
  examCount: number
  avgScoreRate: number
  tagMastery: Array<{ tagId: number; name: string; chunkCount: number; questionCount: number; scoreRate: number }>
}

export function listKb(keyword?: string) {
  return get<KnowledgeBase[]>('/kb/list', keyword ? { keyword } : undefined)
}

export function getKb(id: number) {
  return get<KnowledgeBase>(`/kb/${id}`)
}

export function createKb(data: { name: string; description?: string; coverColor?: string }) {
  return post<KnowledgeBase>('/kb', data)
}

export function updateKb(id: number, data: Partial<KnowledgeBase>) {
  return put<KnowledgeBase>(`/kb/${id}`, data)
}

export function deleteKb(id: number) {
  return del<void>(`/kb/${id}`)
}

export function getKbStat(id: number) {
  return get<KbStat>(`/kb/${id}/stat`)
}

export function refreshKbCounters(id: number) {
  return post<void>(`/kb/${id}/refresh`)
}
