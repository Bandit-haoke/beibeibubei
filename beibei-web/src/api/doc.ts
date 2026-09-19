import { get, post, del } from '@/api/request'

export interface DocumentItem {
  id: number
  kbId: number
  fileName: string
  fileType: string
  fileSize: number
  sourceType: number
  status: number
  chunkCount: number
  pageCount: number
  charCount: number
  errorMsg: string
  createdAt: string
}

export interface TagBrief {
  id: number
  name: string
  level: number
}

export interface ChunkItem {
  id: number
  chunkIndex: number
  content: string
  tokenCount: number
  pageNo: number
  sectionPath: string
  milvusPk: number
  tags: TagBrief[]
}

export interface DocDetail {
  doc: DocumentItem
  chunks: ChunkItem[]
  tags: TagBrief[]
}

export interface UploadResult {
  docId: number | null
  taskId: number | null
  fileName: string
  duplicated: boolean
  message: string
}

export interface PageResult<T> {
  total: number
  list: T[]
  pageNum: number
  pageSize: number
  pages: number
}

/** 文档状态 */
export const DOC_STATUS = {
  0: { text: '待处理', type: 'info' as const },
  1: { text: '解析中', type: 'warning' as const },
  2: { text: '已就绪', type: 'success' as const },
  3: { text: '解析失败', type: 'danger' as const },
}

export function listDocs(params: {
  kbId?: number
  status?: number
  keyword?: string
  pageNum?: number
  pageSize?: number
}) {
  return get<PageResult<DocumentItem>>('/doc/list', params as Record<string, unknown>)
}

export function getDocDetail(id: number, chunkLimit = 50) {
  return get<DocDetail>(`/doc/${id}`, { chunkLimit })
}

export function getDocChunks(id: number, pageNum = 1, pageSize = 20) {
  return get<PageResult<ChunkItem>>(`/doc/${id}/chunks`, { pageNum, pageSize })
}

export function deleteDoc(id: number) {
  return del<void>(`/doc/${id}`)
}

export function reindexDoc(id: number) {
  return post<number>(`/doc/${id}/reindex`)
}

export function pasteText(data: { kbId: number; title?: string; content: string }) {
  return post<UploadResult>('/doc/paste', data)
}

/** 上传（用 FormData，request.ts 的 post 支持传 config） */
export function uploadDocs(kbId: number, files: File[], imageMode = false) {
  const form = new FormData()
  form.append('kbId', String(kbId))
  files.forEach((f) => form.append('files', f))
  return post<UploadResult[]>(imageMode ? '/doc/upload-image' : '/doc/upload', form)
}
