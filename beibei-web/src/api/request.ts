import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

/** 与 Java 侧 Result<T> 对齐 */
export interface Result<T = unknown> {
  code: number
  msg: string
  data: T
  traceId?: string | null
}

export const CODE_OK = 0
export const CODE_AGENT_DOWN = 5031
export const CODE_ASR_UNAVAILABLE = 5032

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 120_000,
  // 刻意不设默认 Content-Type：
  // 一旦写死 application/json，上传 FormData 时浏览器就无法自动补上
  // multipart/form-data 的 boundary，后端会解析失败。交给 axios 按数据类型推断。
})

/**
 * 统一解包：
 *  - code === 0   返回 data
 *  - 其它 code    弹提示并 reject（5031/5032 用更友好的文案）
 */
function unwrap<T>(body: Result<T>): T {
  if (body && typeof body.code === 'number') {
    if (body.code === CODE_OK) {
      return body.data
    }
    const message =
      body.code === CODE_AGENT_DOWN
        ? '智能体未启动，请在 PyCharm 里运行 beibei-agent'
        : body.code === CODE_ASR_UNAVAILABLE
          // 把后端的**真实原因**透出来。
          // 以前这里固定显示「语音服务暂时不可用」，把讯飞的错误码
          // （10114 会话超时 / 11200 未授权 / 11201 额度用完…）全吃掉了，
          // 结果用户和开发者都只看到一个看不出所以然的提示，排查只能靠猜。
          ? (body.msg ? `语音识别失败：${body.msg}` : '语音服务暂时不可用，请手动输入')
          : body.msg || '请求失败'
    ElMessage.error(message)
    return Promise.reject(new Error(message)) as never
  }
  // 后端没走统一响应体（例如静态资源），原样返回
  return body as unknown as T
}

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    let message = '网络请求失败'
    if (status === 404) message = '接口不存在（404）'
    else if (status === 401) message = '未登录或登录已过期'
    else if (status === 500) message = '服务端异常（500）'
    else if (error?.code === 'ECONNABORTED') message = '请求超时'
    else if (error?.message?.includes('Network Error')) {
      message = '无法连接后端，请确认 beibei-server 已在 8080 端口启动'
    }
    ElMessage.error(message)
    return Promise.reject(error)
  },
)

export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const resp = await http.get<Result<T>>(url, { params })
  return unwrap(resp.data)
}

export async function post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const resp = await http.post<Result<T>>(url, data, config)
  return unwrap(resp.data)
}

export async function put<T>(url: string, data?: unknown): Promise<T> {
  const resp = await http.put<Result<T>>(url, data)
  return unwrap(resp.data)
}

export async function del<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const resp = await http.delete<Result<T>>(url, { params })
  return unwrap(resp.data)
}

export default http
