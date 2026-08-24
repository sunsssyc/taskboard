<script setup lang="ts">
import { computed, reactive } from "vue";
import TaskRow from "./TaskRow.vue";
import type { BoardTask } from "../types";

const props = defineProps<{ tasks: BoardTask[]; query: string }>();

const collapsed = reactive<Record<string, boolean>>({
  active: false,
  next: false,
  waiting: false,
  blocked: false,
  done: true,
});

const groups = computed(() => [
  {
    key: "active",
    title: "进行中",
    hint: "当前正在推进",
    tasks: props.tasks.filter((task) => task.status === "active"),
  },
  {
    key: "next",
    title: "下一步",
    hint: "没有未完成前置",
    tasks: props.tasks.filter((task) => task.status === "todo" && task.actionable),
  },
  {
    key: "waiting",
    title: "等人工",
    hint: "等待确认或外部动作",
    tasks: props.tasks.filter((task) => task.status === "waiting"),
  },
  {
    key: "blocked",
    title: "依赖阻塞",
    hint: "前置完成后自动解锁",
    tasks: props.tasks.filter((task) => task.status === "todo" && !task.actionable),
  },
  {
    key: "done",
    title: "已收尾",
    hint: "已完成或放弃",
    tasks: props.tasks.filter((task) => task.status === "done" || task.status === "dropped"),
  },
]);

function isCollapsed(key: string): boolean {
  return props.query.trim() ? false : collapsed[key];
}
</script>

<template>
  <div class="task-groups">
    <section v-for="group in groups" v-show="group.tasks.length" :key="group.key" class="task-group">
      <button
        type="button"
        class="group-heading"
        :aria-expanded="!isCollapsed(group.key)"
        @click="collapsed[group.key] = !collapsed[group.key]"
      >
        <span class="disclosure" :class="{ open: !isCollapsed(group.key) }" aria-hidden="true"></span>
        <strong>{{ group.title }}</strong>
        <span class="group-count">{{ group.tasks.length }}</span>
        <span class="group-hint">{{ group.hint }}</span>
      </button>
      <div v-if="!isCollapsed(group.key)" class="task-list">
        <TaskRow
          v-for="task in group.tasks"
          :key="`${task.ref}:${task.title}`"
          :task="task"
          :query="query"
        />
      </div>
    </section>

    <div v-if="!tasks.length" class="empty-state compact">
      <span class="empty-icon" aria-hidden="true">⌕</span>
      <strong>没有匹配的任务</strong>
      <span>试试更短的关键词，或切换其他需求。</span>
    </div>
  </div>
</template>
