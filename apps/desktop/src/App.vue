<script setup lang="ts">
import { computed, onMounted } from "vue";
import { storeToRefs } from "pinia";
import ProjectSidebar from "./components/ProjectSidebar.vue";
import ProjectWorkspace from "./components/ProjectWorkspace.vue";
import { useBoardStore } from "./stores/board";
import type { TaskCounts, TaskStatus } from "./types";

const board = useBoardStore();
const {
  snapshot,
  selectedProjectKey,
  query,
  statusFilter,
  ownerFilter,
  source,
  loading,
  error,
  projects,
  orderedProjects,
  displayProjects,
  owners,
  viewPrefs,
  preferenceError,
} = storeToRefs(board);

const globalCounts = computed<TaskCounts>(() => {
  const counts: TaskCounts = { todo: 0, active: 0, waiting: 0, done: 0, dropped: 0 };
  for (const project of projects.value) {
    for (const status of Object.keys(counts) as TaskStatus[]) {
      counts[status] += project.counts[status];
    }
  }
  return counts;
});

const actionableCount = computed(() =>
  projects.value.reduce(
    (total, project) => total + project.tasks.filter((task) => task.actionable).length,
    0,
  ),
);

const gateCount = computed(() =>
  projects.value.reduce((total, project) => total + project.gates.length, 0),
);

const filterActive = computed(
  () => Boolean(query.value.trim() || statusFilter.value || ownerFilter.value),
);

function formatGeneratedAt(value: string | undefined): string {
  if (!value) return "尚未载入";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")} ${part("hour")}:${part("minute")} UTC+8`;
}

function resetFilters() {
  query.value = "";
  statusFilter.value = "";
  ownerFilter.value = "";
}

function focusTask(ref: number) {
  requestAnimationFrame(() => {
    const target = document.querySelector<HTMLElement>(`.task-row[data-ref="${ref}"]`);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.remove("flash");
    requestAnimationFrame(() => target.classList.add("flash"));
    window.setTimeout(() => target.classList.remove("flash"), 1250);
  });
}

onMounted(() => board.load());
</script>

<template>
  <div class="app-frame">
    <header class="masthead">
      <h1>任务看板</h1>
      <span class="masthead-subtitle">taskboard · 持久工作流</span>
      <div class="global-meta" aria-label="全局任务概览">
        <span>生成于 {{ formatGeneratedAt(snapshot?.generated_at) }}</span>
        <span>{{ projects.length }} 个需求</span>
        <span>完成 {{ globalCounts.done }}</span>
        <span>进行 {{ globalCounts.active }}</span>
        <span>等人工 {{ globalCounts.waiting }}</span>
        <span>待办 {{ globalCounts.todo }}</span>
        <span>可开工 {{ actionableCount }}</span>
        <span>闸门 {{ gateCount }}</span>
      </div>
    </header>

    <div class="toolbar" role="search">
      <label class="toolbar-search">
        <span class="sr-only">搜索任务、正文和结论</span>
        <input v-model="query" type="search" placeholder="搜索任务、正文、结论…" />
      </label>
      <label>
        <span class="sr-only">按状态筛选</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option value="todo">待办</option>
          <option value="active">进行中</option>
          <option value="waiting">等人工</option>
          <option value="done">已完成</option>
          <option value="dropped">已放弃</option>
        </select>
      </label>
      <label>
        <span class="sr-only">按负责人筛选</span>
        <select v-model="ownerFilter">
          <option value="">全部负责人</option>
          <option v-for="owner in owners" :key="owner" :value="owner">{{ owner }}</option>
        </select>
      </label>
      <button
        type="button"
        class="refresh-button"
        :disabled="loading"
        aria-label="刷新看板"
        @click="board.load"
      >
        <svg viewBox="0 0 20 20" aria-hidden="true" :class="{ rotating: loading }">
          <path d="M15.8 7.1A6.3 6.3 0 1 0 16 12"></path>
          <path d="M12.4 4.8h3.7v3.7"></path>
        </svg>
      </button>
    </div>

    <div class="dashboard">
      <ProjectSidebar
        :projects="orderedProjects"
        :selected-key="selectedProjectKey"
        :pinned-keys="viewPrefs.pinned"
        :source="source"
        :database="snapshot?.db ?? null"
        :preference-error="preferenceError"
        @select="board.selectProject"
        @select-all="board.selectAllProjects"
        @focus-task="focusTask"
        @toggle-pin="board.togglePinned"
        @reorder="board.reorderProject"
      />

      <main class="content">
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

        <template v-else>
          <div v-if="source.includes('演示')" class="demo-banner">
            当前为浏览器演示数据；运行 <code>npm run tauri dev</code> 后读取真实本地看板。
          </div>
          <div v-else-if="error" class="inline-error" role="alert">
            刷新失败，继续显示上一次数据：{{ error }}
          </div>

          <div v-if="filterActive" class="active-filter-note">
            <span>当前筛选显示 {{ displayProjects.length }} 个需求</span>
            <button type="button" @click="resetFilters">清除筛选</button>
          </div>

          <ProjectWorkspace
            v-for="project in displayProjects"
            :key="project.key"
            :project="project"
            :tasks="board.filteredTasks(project)"
            :findings="board.filteredFindings(project)"
            :risks="board.filteredRisks(project)"
            :links="board.filteredLinks(project)"
            :query="query"
            :single-project="Boolean(selectedProjectKey)"
            @show-all="board.selectAllProjects"
          />

          <div v-if="!displayProjects.length" class="center-state compact-empty">
            <span class="state-symbol quiet" aria-hidden="true">⌕</span>
            <strong>没有匹配的内容</strong>
            <button type="button" class="secondary-button" @click="resetFilters">清除筛选</button>
          </div>
        </template>
      </main>
    </div>
  </div>
</template>
