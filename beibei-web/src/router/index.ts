import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

/**
 * 路由表。
 *
 * M0/M1 已实现：首页看板、知识库、文档管理、知识点、检索调试。
 * 其余指向 PlaceholderView，说明「这个页面将来做什么」，避免点进去白屏。
 */
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: '首页看板' },
  },
  {
    path: '/kb',
    name: 'kb',
    component: () => import('@/views/KbListView.vue'),
    meta: { title: '知识库' },
  },
  {
    path: '/kb/:id/doc',
    name: 'kb-doc',
    component: () => import('@/views/DocView.vue'),
    meta: { title: '文档管理' },
  },
  {
    path: '/kb/:id/tag',
    name: 'kb-tag',
    component: () => import('@/views/TagView.vue'),
    meta: { title: '知识点' },
  },
  {
    path: '/kb/:id/search',
    name: 'kb-search',
    component: () => import('@/views/SearchDebugView.vue'),
    meta: { title: '检索调试' },
  },
  {
    path: '/kb/:id/generate',
    name: 'kb-generate',
    component: () => import('@/views/GenerateView.vue'),
    meta: { title: 'AI 出题' },
  },
  {
    path: '/paper/:id/review',
    name: 'paper-review',
    component: () => import('@/views/PaperReviewView.vue'),
    meta: { title: '题目审核' },
  },
  {
    path: '/exam/start/:paperId',
    name: 'exam-start',
    component: () => import('@/views/ExamView.vue'),
    meta: { title: '答题' },
  },
  {
    path: '/exam/:id/result',
    name: 'exam-result',
    component: () => import('@/views/ExamResultView.vue'),
    meta: { title: '判分结果' },
  },
  {
    path: '/exam',
    name: 'exam-history',
    component: () => import('@/views/ExamHistoryView.vue'),
    meta: { title: '答题记录' },
  },
  {
    path: '/resume',
    redirect: '/interview',
  },
  {
    path: '/interview',
    name: 'interview',
    component: () => import('@/views/InterviewHomeView.vue'),
    meta: { title: '模拟面试' },
  },
  {
    path: '/interview/:id/room',
    name: 'interview-room',
    component: () => import('@/views/InterviewRoomView.vue'),
    meta: { title: '面试进行中' },
  },
  {
    path: '/interview/:id/report',
    name: 'interview-report',
    component: () => import('@/views/InterviewReportView.vue'),
    meta: { title: '面试评估报告' },
  },
  {
    path: '/paper',
    name: 'paper',
    component: () => import('@/views/PlaceholderView.vue'),
    meta: {
      title: '题库总览',
      stage: 'M2',
      desc: '出题与审核已可用 — 请从知识库详情页点「AI 出题」进入。',
      features: [
        '知识库页 → AI 出题：选择题量、知识点范围、题型与难度配比',
        '生成后自动进审核页：通过 / 编辑 / 删除 / 重新出题',
        '跨批次查重：与已有题目向量相似度 > 0.92 直接丢弃',
        '待补充：跨知识库题库检索、Anki / Excel 导出',
      ],
    },
  },
  {
    path: '/mistake',
    name: 'mistake',
    component: () => import('@/views/MistakeView.vue'),
    meta: { title: '错题本' },
  },
  {
    path: '/review',
    name: 'review',
    component: () => import('@/views/ReviewView.vue'),
    meta: { title: '复习计划' },
  },
  {
    path: '/stat',
    name: 'stat',
    component: () => import('@/views/StatView.vue'),
    meta: { title: '学习统计' },
  },
  {
    path: '/settings/ai',
    name: 'ai',
    component: () => import('@/views/AiSettingsView.vue'),
    meta: { title: 'AI 配置' },
  },
  {
    path: '/settings/sys',
    name: 'sys',
    component: () => import('@/views/SysSettingsView.vue'),
    meta: { title: '系统设置' },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || '背备不悲'
  document.title = `${title} · 背备不悲`
})

export default router
