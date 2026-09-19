import { get, post, del } from '@/api/request'

/** 单个环境检查项 */
export interface HealthCheck {
  key: string
  name: string
  ok: boolean
  /** core = 核心（失败则主流程不可用）；optional = 可降级 */
  level: 'core' | 'optional' | string
  detail: string
  error: string
  hint: string
  extra: Record<string, unknown>
}

export interface JavaStatus {
  ok: boolean
  version: string
  vendor: string
  pid: number
  uptimeSeconds: number
  heapUsedMb: number
  heapMaxMb: number
  processors: number
  os: string
}

export interface AgentHealth {
  ok: boolean
  coreOk: boolean
  checkedAt: string
  checks: HealthCheck[]
  /** Java 调不通 Python 时为 true */
  unreachable?: boolean
  baseUrl?: string
  error?: string
  hint?: string
}

export interface SysHealth {
  checkedAt: string
  java: JavaStatus
  agent: AgentHealth
  allOk: boolean
}

export function getSysHealth(probeLlm = false): Promise<SysHealth> {
  return get<SysHealth>('/sys/health', { probeLlm })
}

export function getSysInfo(): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>('/sys/info')
}

// ============================== 备份 / 恢复 ==============================

export interface BackupResult {
  filename: string
  path: string
  sizeBytes: number
  tableCount: number
  rowCount: number
  fileCount: number
}

export interface BackupFile {
  filename: string
  path: string
  sizeBytes: number
  modifiedAt: string
}

export interface RestoreResult {
  tableCount: number
  rowCount: number
  fileCount: number
}

export function doBackup() {
  return post<BackupResult>('/sys/backup')
}

export function listBackups() {
  return get<BackupFile[]>('/sys/backup/list')
}

export function deleteBackup(filename: string) {
  return del<void>(`/sys/backup/${encodeURIComponent(filename)}`)
}

export function doRestore(filename: string) {
  return post<RestoreResult>('/sys/restore', undefined, { params: { filename } })
}

// ============================== 一致性 ------------

export interface ConsistencyReport {
  ok: boolean
  error?: string
  collection?: string
  mysqlChunks?: number
  milvusVectors?: number
  orphanCount?: number
  missingCount?: number
  misplacedCount?: number
  orphanPks?: number[]
  missingPks?: number[]
  misplaced?: Array<{ pk: number; actual: string; expected: string }>
  partitionErrors?: string[]
  healthy?: boolean
}

export function checkConsistency() {
  return get<ConsistencyReport>('/sys/consistency')
}

export function repairConsistency() {
  return post<{ ok: boolean; deleted: number; after?: ConsistencyReport }>('/sys/consistency/repair')
}
