<script setup lang="ts">
import { computed, reactive } from "vue";
import TaskRow from "./TaskRow.vue";
import { sortTasksByPriority } from "../priority";
import type { BoardTask } from "../types";

const props = defineProps<{ tasks: BoardTask[]; projectKey: string; query: string }>();

const expandedGroups = reactive<Record<string, boolean>>({
  ready: false,
  blocked: false,
  dropped: false,
  done: false,
});

const actionableTasks = computed(() =>
  sortTasksByPriority(props.tasks.filter((task) => task.actionable)),
);

const shownActionableTasks = computed(() => actionableTasks.value.slice(0, 3));
const foldedActionableTasks = computed(() => actionableTasks.value.slice(3));

const contextTasks = computed(() =>
  sortTasksByPriority(props.tasks.filter(
    (task) => !task.actionable && (task.status === "active" || task.status === "waiting"),
  )),
);

const archiveGroups = computed(() => [
  {
    key: "blocked",
    title: "项被阻塞待办",
    prefix: "还有",
    tasks: props.tasks.filter((task) => task.status === "todo" && !task.actionable),
  },
  {
    key: "dropped",
    title: "项",
    prefix: "已放弃",
    tasks: props.tasks.filter((task) => task.status === "dropped"),
  },
  {
    key: "done",
    title: "项",
    prefix: "已完成",
    tasks: props.tasks.filter((task) => task.status === "done"),
  },
]);

function groupOpen(key: string): boolean {
  return Boolean(props.query.trim()) || expandedGroups[key];
}
</script>

<template>
  <div v-if="tasks.length" class="task-spine">
    <TaskRow
      v-for="(task, index) in shownActionableTasks"
      :key="`${task.ref}:${task.title}`"
      :task="task"
      :project-key="projectKey"
      :query="query"
      :initially-expanded="index === 0"
    />

    <section v-if="foldedActionableTasks.length" class="archive-group priority-overflow">
      <button
        type="button"
        class="archive-heading priority-overflow-heading"
        :aria-expanded="groupOpen('ready')"
        @click="expandedGroups.ready = !expandedGroups.ready"
      >
        <span class="disclosure" :class="{ open: groupOpen('ready') }" aria-hidden="true"></span>
        <span>还有 {{ foldedActionableTasks.length }} 项可开工</span>
        <small>按 P0 → P3 排序</small>
      </button>
      <div v-if="groupOpen('ready')" class="archive-tasks">
        <TaskRow
          v-for="task in foldedActionableTasks"
          :key="`${task.ref}:${task.title}`"
          :task="task"
          :project-key="projectKey"
          :query="query"
        />
      </div>
    </section>

    <TaskRow
      v-for="(task, index) in contextTasks"
      :key="`${task.ref}:${task.title}`"
      :task="task"
      :project-key="projectKey"
      :query="query"
      :initially-expanded="shownActionableTasks.length === 0 && index === 0"
    />

    <section
      v-for="group in archiveGroups"
      v-show="group.tasks.length"
      :key="group.key"
      class="archive-group"
    >
      <button
        type="button"
        class="archive-heading"
        :aria-expanded="groupOpen(group.key)"
        @click="expandedGroups[group.key] = !expandedGroups[group.key]"
      >
        <span class="disclosure" :class="{ open: groupOpen(group.key) }" aria-hidden="true"></span>
        <span>{{ group.prefix }} {{ group.tasks.length }} {{ group.title }}</span>
      </button>
      <div v-if="groupOpen(group.key)" class="archive-tasks">
        <TaskRow
          v-for="task in group.tasks"
          :key="`${task.ref}:${task.title}`"
          :task="task"
          :project-key="projectKey"
          :query="query"
        />
      </div>
    </section>
  </div>

  <div v-else class="empty-state compact">
    <span class="empty-icon" aria-hidden="true">⌕</span>
    <strong>没有匹配的任务</strong>
    <span>调整搜索或筛选条件后再试。</span>
  </div>
</template>
