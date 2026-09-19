import { post } from '@/api/request'

export interface SearchHit {
  pk: number
  text: string
  docId: number
  chunkIndex: number
  tagIds: number[]
  score: number
  source: string
  pageNo?: number
  sectionPath?: string
  fileName?: string
}

export interface SearchResult {
  ok: boolean
  error?: string
  hint?: string
  query?: string
  kbId?: number
  count: number
  source: string
  hits: SearchHit[]
}

export function search(payload: {
  kbId: number
  query: string
  topK?: number
  tagIds?: number[]
  docIds?: number[]
}) {
  return post<SearchResult>('/search', { topK: 8, enrich: true, ...payload })
}
