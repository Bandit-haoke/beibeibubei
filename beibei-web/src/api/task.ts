import { get } from '@/api/request'

export interface TaskVO {
  id: number
  taskType: string
  bizId: number
  status: number
  progress: number
  stage: string
  message: string
  resultJson: string | null
  errorMsg: string
  startedAt: string | null
  finishedAt: string | null
  createdAt: string
}

export const TASK_STATUS = {
  0: { text: '排队中', type: 'info' as const },
  1: { text: '运行中', type: 'warning' as const },
  2: { text: '已完成', type: 'success' as const },
  3: { text: '失败', type: 'danger' as const },
  4: { text: '已取消', type: 'info' as const },
}

export function getTask(id: number) {
  return get<TaskVO>(`/task/${id}`)
}

export interface TaskEvent {
  taskId: number
  taskType?: string
  bizId?: number
  status?: number
  progress?: number
  stage?: string
  errorMsg?: string
  result?: Record<string, unknown> | null
}

/**
 * 订阅任务进度的 SSE 流。
 *
 * 注意 EventSource 的坑：服务端发来的 `event: error` 和网络断开
 * 都会触发 'error' 监听器。区分办法是看事件对象有没有 data ——
 * 我们自己发的 error 事件带 data，传输层错误没有。
 */
export function subscribeTask(
  taskId: number,
  handlers: {
    onProgress?: (e: TaskEvent) => void
    onDone?: (e: TaskEvent) => void
    onError?: (e: TaskEvent) => void
  },
): () => void {
  const source = new EventSource(`/api/task/${taskId}/stream`)
  let closed = false

  const close = () => {
    if (!closed) {
      closed = true
      source.close()
    }
  }

  source.addEventListener('progress', (ev) => {
    handlers.onProgress?.(JSON.parse((ev as MessageEvent).data) as TaskEvent)
  })

  source.addEventListener('done', (ev) => {
    handlers.onDone?.(JSON.parse((ev as MessageEvent).data) as TaskEvent)
    close()
  })

  source.addEventListener('error', (ev) => {
    const data = (ev as MessageEvent).data
    if (data) {
      // 服务端主动推的业务错误
      handlers.onError?.(JSON.parse(data) as TaskEvent)
    } else {
      // 传输层问题（Java 重启、网络断）
      handlers.onError?.({ taskId, errorMsg: '进度连接中断，可刷新页面查看结果' })
    }
    close()
  })

  return close
}
