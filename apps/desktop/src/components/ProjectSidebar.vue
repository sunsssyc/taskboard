<script setup lang="ts">
import type { BoardProject, BoardTask } from "../types";

const props = defineProps<{
  projects: BoardProject[];
  selectedKey: string;
  source: string;
  database: string | null;
}>();

defineEmits<{
  select: [key: string];
  selectAll: [];
  focusTask: [ref: number];
}>();

function total(project: BoardProject): number {
  return Object.values(project.counts).reduce((sum, count) => sum + count, 0);
}

function percentage(project: BoardProject, count: number): number {
  return total(project) ? (count / total(project)) * 100 : 0;
}

function outlineTasks(project: BoardProject): BoardTask[] {
  return project.tasks
    .filter(
      (task) =>
        task.status === "active" || task.status === "waiting" ||
        (task.status === "todo" && task.actionable),
    )
    .slice(0, 3);
}

function nextTask(project: BoardProject): BoardTask | undefined {
  return outlineTasks(project)[0];
}

function taskDot(task: BoardTask): string {
  if (task.status === "active") return "active";
  if (task.status === "waiting") return "waiting";
  return "todo";
}
</script>

<template>
  <aside class="navigator">
    <div class="navigator-head">
      <span>需求</span>
      <b>{{ projects.length }}</b>
    </div>

    <nav class="project-list" aria-label="需求工作流">
      <button
        type="button"
        class="all-projects-button"
        :aria-pressed="!selectedKey"
        @click="$emit('selectAll')"
      >
        <strong>全部需求</strong>
        <span>{{ projects.length }} 个需求</span>
      </button>

      <div
        v-for="project in projects"
        :key="project.key"
        class="project-group"
        :class="{ selected: project.key === selectedKey }"
      >
        <button
          type="button"
          class="project-card"
          :aria-pressed="project.key === selectedKey"
          @click="$emit('select', project.key)"
        >
          <span class="project-key">{{ project.key }}</span>
          <strong>{{ project.name }}</strong>
          <span v-if="project.repositories.length" class="project-repositories">
            <span
              v-for="repository in project.repositories"
              v-show="repository.name !== project.key"
              :key="repository.name"
            >
              {{ repository.name }}
            </span>
          </span>
          <span class="project-progress" aria-hidden="true">
            <span
              class="done"
              :style="{ width: `${percentage(project, project.counts.done)}%` }"
            ></span>
            <span
              class="active"
              :style="{ width: `${percentage(project, project.counts.active)}%` }"
            ></span>
          </span>
          <span class="project-counts">
            <span>完成 <b>{{ project.counts.done }}</b></span>
            <span>进行 <b>{{ project.counts.active }}</b></span>
            <span>待办 <b>{{ project.counts.todo }}</b></span>
          </span>
          <span class="project-next">
            <template v-if="nextTask(project)">
              <b>下一步</b> #{{ nextTask(project)?.ref }} {{ nextTask(project)?.title }}
            </template>
            <template v-else>没有可动的任务</template>
          </span>
          <span v-if="project.gates.length" class="project-gate">
            闸门 #{{ project.gates.join("、#") }}
          </span>
        </button>

        <div v-if="project.key === selectedKey" class="project-outline">
          <button
            v-for="task in outlineTasks(project)"
            :key="task.ref"
            type="button"
            class="outline-task"
            @click="$emit('focusTask', task.ref)"
          >
            <span class="outline-dot" :class="taskDot(task)" aria-hidden="true"></span>
            <span class="outline-ref">#{{ task.ref }}</span>
            <span class="outline-title">{{ task.title }}</span>
          </button>
        </div>
      </div>
    </nav>

    <footer class="navigator-footer">
      <span class="source-dot" :class="{ demo: source.includes('演示') }"></span>
      <span>
        <strong>{{ source || "正在连接…" }}</strong>
        <small :title="database ?? ''">{{ database || "数据库路径已隐藏" }}</small>
      </span>
    </footer>
  </aside>
</template>
