import { get, post, put, del } from '@/api/request'

export interface TagNode {
  id: number
  parentId: number
  name: string
  level: number
  sortOrder: number
  description: string
  origin: number
  chunkCount: number
  questionCount: number
  children: TagNode[]
}

export function getTagTree(kbId: number) {
  return get<TagNode[]>('/tag/tree', { kbId })
}

export function createTag(data: { kbId: number; parentId?: number; name: string; description?: string }) {
  return post<number>('/tag', data)
}

export function updateTag(id: number, data: { kbId: number; name?: string; description?: string; sortOrder?: number }) {
  return put<void>(`/tag/${id}`, data)
}

export function deleteTag(id: number) {
  return del<void>(`/tag/${id}`)
}

export function refreshTagCounts(kbId: number) {
  return post<void>('/tag/refresh', undefined, { params: { kbId } })
}
