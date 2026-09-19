<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const title = computed(() => (route.meta.title as string) || '待开发')
const stage = computed(() => (route.meta.stage as string) || '')
const desc = computed(() => (route.meta.desc as string) || '')
const features = computed(() => (route.meta.features as string[]) || [])
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h2>{{ title }}</h2>
        <div class="sub">计划在 {{ stage }} 阶段实现</div>
      </div>
      <el-tag type="info" effect="plain">待开发</el-tag>
    </div>

    <el-card shadow="never">
      <el-result icon="info" :title="title" :sub-title="desc">
        <template #extra>
          <div style="text-align: left; max-width: 640px; margin: 0 auto">
            <div style="font-weight: 600; margin-bottom: 10px; color: #475569">这个页面将会包含：</div>
            <ul style="margin: 0; padding-left: 20px; color: #64748b; line-height: 2">
              <li v-for="f in features" :key="f">{{ f }}</li>
            </ul>
          </div>
        </template>
      </el-result>
    </el-card>
  </div>
</template>
