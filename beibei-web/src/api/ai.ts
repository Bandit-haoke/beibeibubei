import { get, post, put, del } from '@/api/request'

// ============================== 厂商 ==============================

export interface Provider {
  id: number
  name: string
  vendor: string
  protocol: string
  baseUrl: string
  model: string
  apiKeyMasked: string
  hasApiKey: boolean
  apiSecretMasked: string
  hasApiSecret: boolean
  appId: string
  capability: string
  extraParams: Record<string, unknown>
  enabled: number
  priority: number
  isActive: number
  locked: number
  lastTestAt: string | null
  lastTestOk: number
  lastTestMsg: string
  remark: string
}

export interface ProviderSaveReq {
  name?: string
  vendor?: string
  protocol?: string
  baseUrl?: string
  model?: string
  apiKey?: string
  apiSecret?: string
  appId?: string
  capability?: string
  extraParams?: Record<string, unknown>
  enabled?: number
  priority?: number
  remark?: string
}

export interface TestResult {
  ok: boolean
  message: string
  latencyMs: number
  model: string
  endpoint: string
}

/** 常见厂商预设，新建时一键填充 */
/**
 * 厂商预设。
 *
 * `capability` 决定这个厂商属于哪类能力：
 *   CHAT  → 出题 / 判分 / 分类（OpenAI 兼容协议）
 *   ASR   → 语音转文字
 *
 * ⚠️ 讯飞和别的厂商不一样：它要**三个**值（APPID / APIKey / APISecret），
 *    不是「一个 API Key」。表单里会对 xfyun 额外显示 APPID 与 APISecret 两栏。
 */
export const VENDOR_PRESETS = [
  { vendor: 'deepseek', name: 'DeepSeek', protocol: 'openai-compatible', baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat', capability: 'CHAT' },
  { vendor: 'qwen', name: '通义千问', protocol: 'openai-compatible', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus', capability: 'CHAT' },
  { vendor: 'zhipu', name: '智谱 GLM', protocol: 'openai-compatible', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-plus', capability: 'CHAT' },
  { vendor: 'moonshot', name: '月之暗面 Kimi', protocol: 'openai-compatible', baseUrl: 'https://api.moonshot.cn', model: 'moonshot-v1-8k', capability: 'CHAT' },
  { vendor: 'openai', name: 'OpenAI', protocol: 'openai-compatible', baseUrl: 'https://api.openai.com', model: 'gpt-4o-mini', capability: 'CHAT' },
  { vendor: 'ollama', name: '本地 Ollama', protocol: 'ollama', baseUrl: 'http://127.0.0.1:11434', model: 'qwen2.5:7b', capability: 'CHAT' },
  { vendor: 'xfyun', name: '讯飞语音听写', protocol: 'custom', baseUrl: 'wss://iat-api.xfyun.cn/v2/iat', model: 'iat', capability: 'ASR' },
  { vendor: 'aliyun', name: '阿里云智能语音', protocol: 'custom', baseUrl: 'https://nls-gateway-cn-shanghai.aliyuncs.com', model: 'nls', capability: 'ASR' },
]

export function listProviders() {
  return get<Provider[]>('/ai/provider/list')
}

export function createProvider(data: ProviderSaveReq) {
  return post<Provider>('/ai/provider', data)
}

export function updateProvider(id: number, data: ProviderSaveReq) {
  return put<Provider>(`/ai/provider/${id}`, data)
}

export function deleteProvider(id: number) {
  return del<void>(`/ai/provider/${id}`)
}

export function testProvider(id: number) {
  return post<TestResult>(`/ai/provider/${id}/test`)
}

export function activateProvider(id: number) {
  return post<void>(`/ai/provider/${id}/activate`)
}

// ============================== 任务路由 ==============================

export interface RouteItem {
  taskType: string
  taskName: string
  description: string
  providerId: number | null
  providerName: string
  fallbackProviderId: number | null
  fallbackProviderName: string
  remark: string
}

export function listRoutes() {
  return get<RouteItem[]>('/ai/route')
}

export function saveRoute(data: {
  taskType: string
  providerId?: number | null
  fallbackProviderId?: number | null
  remark?: string
}) {
  return put<void>('/ai/route', data)
}

// ============================== Prompt 模板 ==============================

export interface PromptVersion {
  id: number
  version: number
  isActive: number
  remark: string
  createdAt: string
  contentLength: number
}

export interface PromptGroup {
  code: string
  name: string
  remark: string
  activeVersion: number
  versionCount: number
  versions: PromptVersion[]
}

export interface PromptDetail {
  id: number
  code: string
  name: string
  content: string
  variables: string
  version: number
  isActive: number
  builtin: number
  remark: string
  createdAt: string
}

export function listPromptGroups() {
  return get<PromptGroup[]>('/ai/prompt/list')
}

export function getPrompt(id: number) {
  return get<PromptDetail>(`/ai/prompt/${id}`)
}

export function savePrompt(id: number, content: string, remark: string) {
  return put<PromptDetail>(`/ai/prompt/${id}`, { content, remark })
}

export function rollbackPrompt(versionId: number) {
  return post<PromptDetail>(`/ai/prompt/rollback/${versionId}`)
}
