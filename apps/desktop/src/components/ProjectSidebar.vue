<script setup lang="ts">
import type { BoardProject } from "../types";

defineProps<{
  projects: BoardProject[];
  selectedKey: string;
  source: string;
  database: string | null;
}>();

defineEmits<{
  select: [key: string];
}>();

function progress(project: BoardProject): number {
  const total = Object.values(project.counts).reduce((sum, count) => sum + count, 0);
  return total ? Math.round((project.counts.done / total) * 100) : 0;
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-brand">
      <div class="app-mark" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>
      <div>
        <strong>Taskboard</strong>
        <span>本地任务状态</span>
      </div>
    </div>

    <div class="sidebar-heading">
      <span>需求工作流</span>
      <span class="count-badge">{{ projects.length }}</span>
    </div>

    <nav class="project-list" aria-label="需求工作流">
      <button
        v-for="project in projects"
        :key="project.key"
        type="button"
        class="project-item"
        :class="{ selected: project.key === selectedKey }"
        :aria-current="project.key === selectedKey ? 'page' : undefined"
        @click="$emit('select', project.key)"
      >
        <span class="project-title-row">
          <strong>{{ project.name }}</strong>
          <span>{{ progress(project) }}%</span>
        </span>
        <span class="project-key">{{ project.key }}</span>
        <span class="progress-track" aria-hidden="true">
          <span :style="{ width: `${progress(project)}%` }"></span>
        </span>
        <span class="project-summary">
          {{ project.counts.active }} 进行 · {{ project.counts.todo }} 待办
          <template v-if="project.counts.waiting"> · {{ project.counts.waiting }} 等人工</template>
        </span>
      </button>
    </nav>

    <footer class="sidebar-footer">
      <span class="source-dot" :class="{ demo: source.includes('演示') }"></span>
      <span class="source-copy">
        <strong>{{ source || "正在连接…" }}</strong>
        <span :title="database ?? ''">{{ database || "数据库路径已隐藏" }}</span>
      </span>
    </footer>
  </aside>
</template>
