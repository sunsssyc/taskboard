<script setup lang="ts">
import { computed, onMounted } from "vue";
import { storeToRefs } from "pinia";
import NoteGroups from "./components/NoteGroups.vue";
import ProjectSidebar from "./components/ProjectSidebar.vue";
import TaskGroups from "./components/TaskGroups.vue";
import { useBoardStore } from "./stores/board";

const board = useBoardStore();
const {
  snapshot,
  selectedProjectKey,
  query,
  source,
  loading,
  error,
  projects,
  selectedProject,
  matchingTasks,
  matchingFindings,
  matchingRisks,
  matchingLinks,
} = storeToRefs(board);

const totalTasks = computed(() => {
  const counts = selectedProject.value?.counts;
  return counts ? Object.values(counts).reduce((sum, count) => sum + count, 0) : 0;
});

const completion = computed(() => {
  if (!selectedProject.value || !totalTasks.value) return 0;
  return Math.round((selectedProject.value.counts.done / totalTasks.value) * 100);
});

const resultCount = computed(
  () =>
    matchingTasks.value.length +
    matchingFindings.value.length +
    matchingRisks.value.length +
    matchingLinks.value.length,
);

function formatGeneratedAt(value: string | undefined): string {
  if (!value) return "尚未载入";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

onMounted(() => board.load());
</script>

<template>
  <div class="app-shell">
    <ProjectSidebar
      :projects="projects"
      :selected-key="selectedProjectKey"
      :source="source"
      :database="snapshot?.db ?? null"
      @select="board.selectProject"
    />

    <main class="workspace">
      <div v-if="loading && !snapshot" class="center-state" aria-live="polite">
        <span class="spinner" aria-hidden="true"></span>
        <strong>正在读取任务状态</strong>
        <span>通过只读 board export 加载本地数据库…</span>
      </div>

      <div v-else-if="error && !snapshot" class="center-state error-state" role="alert">
        <span class="state-symbol" aria-hidden="true">!</span>
        <strong>无法载入任务看板</strong>
        <span>{{ error }}</span>
        <button type="button" class="primary-button" @click="board.load">重试</button>
      </div>

      <template v-else-if="selectedProject">
        <header class="workspace-header">
          <div class="title-block">
            <span class="eyebrow">{{ selectedProject.key }}</span>
            <h1>{{ selectedProject.name }}</h1>
            <p>{{ selectedProject.summary || "持续保存进度、结论与下一步。" }}</p>
            <div v-if="selectedProject.repositories.length" class="repo-list" aria-label="关联仓库">
              <span v-for="repository in selectedProject.repositories" :key="repository.name">
                {{ repository.name }}
              </span>
            </div>
          </div>

          <div class="header-tools">
            <label class="search-box">
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <circle cx="8.5" cy="8.5" r="5.25"></circle>
                <path d="m12.5 12.5 4 4"></path>
              </svg>
              <span class="sr-only">搜索当前需求</span>
              <input v-model="query" type="search" placeholder="搜索任务、结论、仓库…" />
              <span v-if="query" class="search-count">{{ resultCount }}</span>
            </label>
            <button type="button" class="icon-button" :disabled="loading" aria-label="刷新看板" @click="board.load">
              <svg viewBox="0 0 20 20" aria-hidden="true" :class="{ rotating: loading }">
                <path d="M15.8 7.1A6.3 6.3 0 1 0 16 12"></path>
                <path d="M12.4 4.8h3.7v3.7"></path>
              </svg>
            </button>
          </div>
        </header>

        <div v-if="source.includes('演示')" class="demo-banner">
          当前为浏览器演示数据；运行 <code>npm run tauri dev</code> 后会读取真实本地看板。
        </div>
        <div v-else-if="error" class="inline-error" role="alert">
          刷新失败，继续显示上一次数据：{{ error }}
        </div>

        <section class="metric-strip" aria-label="需求进度">
          <div class="progress-metric">
            <span class="metric-label">整体进度</span>
            <strong>{{ completion }}%</strong>
            <span class="metric-progress"><span :style="{ width: `${completion}%` }"></span></span>
          </div>
          <div>
            <span class="metric-label">进行中</span>
            <strong>{{ selectedProject.counts.active }}</strong>
          </div>
          <div>
            <span class="metric-label">待办</span>
            <strong>{{ selectedProject.counts.todo }}</strong>
          </div>
          <div>
            <span class="metric-label">等人工</span>
            <strong>{{ selectedProject.counts.waiting }}</strong>
          </div>
          <div>
            <span class="metric-label">已完成</span>
            <strong>{{ selectedProject.counts.done }}</strong>
          </div>
          <div class="generated-at">
            <span class="metric-label">数据生成</span>
            <strong>{{ formatGeneratedAt(snapshot?.generated_at) }}</strong>
          </div>
        </section>

        <div class="content-stack">
          <section class="tasks-panel">
            <header class="panel-heading">
              <div>
                <span class="eyebrow">执行路径</span>
                <h2>任务</h2>
              </div>
              <span class="panel-count">{{ matchingTasks.length }} 项</span>
            </header>
            <TaskGroups :tasks="matchingTasks" :query="query" />
          </section>

          <NoteGroups
            :findings="matchingFindings"
            :risks="matchingRisks"
            :links="matchingLinks"
            :query="query"
          />
        </div>
      </template>

      <div v-else class="center-state">
        <span class="state-symbol quiet" aria-hidden="true">+</span>
        <strong>还没有需求</strong>
        <span>先运行 <code>board init &lt;key&gt; --name "…" --repo .</code></span>
      </div>
    </main>
  </div>
</template>
