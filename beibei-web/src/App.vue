<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activeMenu = computed(() => route.path)

/** 侧边栏菜单。todo 标记的会用「待开发」角标标出来，避免点进去白屏 */
const menus = [
  { path: '/', title: '首页看板', icon: 'HomeFilled' },
  { path: '/kb', title: '知识库', icon: 'Collection' },
  { path: '/paper', title: '题库总览', icon: 'EditPen', todo: true },
  { path: '/exam', title: '答题记录', icon: 'Tickets' },
  { path: '/interview', title: '模拟面试', icon: 'ChatDotRound' },
  { path: '/mistake', title: '错题本', icon: 'WarningFilled' },
  { path: '/review', title: '复习计划', icon: 'AlarmClock' },
  { path: '/stat', title: '学习统计', icon: 'TrendCharts' },
  { path: '/settings/ai', title: 'AI 配置', icon: 'MagicStick' },
  { path: '/settings/sys', title: '系统设置', icon: 'Setting' },
]
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="220px" class="app-aside">
      <div class="brand">
        <div class="brand-title">背备不悲</div>
        <div class="brand-sub">背得会 · 备得全 · 考不悲</div>
      </div>

      <el-menu :default-active="activeMenu" router class="app-menu">
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.title }}</span>
          <el-tag v-if="m.todo" size="small" type="info" effect="plain" class="todo-tag">待开发</el-tag>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="app-header">
        <span class="page-title">{{ route.meta.title || '背备不悲' }}</span>
        <span class="header-right">本地部署 · M6 模拟面试</span>
      </el-header>

      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-shell {
  height: 100vh;
}

.app-aside {
  background: #1e293b;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.brand {
  padding: 20px 18px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.brand-title {
  color: #fff;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 3px;
}

.brand-sub {
  color: #94a3b8;
  font-size: 11px;
  letter-spacing: 1.5px;
  margin-top: 5px;
}

.app-menu {
  flex: 1;
  border-right: none;
  background: transparent;
  padding-top: 8px;
}

.app-menu :deep(.el-menu-item) {
  color: #cbd5e1;
  height: 46px;
  line-height: 46px;
}

.app-menu :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}

.app-menu :deep(.el-menu-item.is-active) {
  background: #4c7cf3;
  color: #fff;
}

.todo-tag {
  margin-left: auto;
  transform: scale(0.82);
}

.app-header {
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
}

.page-title {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}

.header-right {
  font-size: 12.5px;
  color: #94a3b8;
}

.app-main {
  background: #f4f6fb;
  padding: 20px;
  overflow-y: auto;
}
</style>
