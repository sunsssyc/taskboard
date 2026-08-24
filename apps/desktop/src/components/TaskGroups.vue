<script setup lang="ts">
import { computed, reactive } from "vue";
import TaskRow from "./TaskRow.vue";
import type { BoardTask } from "../types";

const props = defineProps<{ tasks: BoardTask[]; query: string }>();

const expandedGroups = reactive<Record<string, boolean>>({
  blocked: false,
  dropped: false,
  done: false,
});

const focusTasks = computed(() =>
  props.tasks.filter(
    (task) =>
      task.status === "active" || task.status === "waiting" ||
      (task.status === "todo" && task.actionable),
  ),
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
      v-for="task in focusTasks"
      :key="`${task.ref}:${task.title}`"
      :task="task"
      :query="query"
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
