<script setup lang="ts">
import { computed, ref, watch } from "vue";
import MarkdownBlock from "./MarkdownBlock.vue";
import type { BoardTask } from "../types";

const props = defineProps<{ task: BoardTask; query: string }>();
const expanded = ref(props.task.status === "active");

watch(
  () => props.query,
  (query) => {
    if (query.trim()) expanded.value = true;
  },
);

const statusLabel = computed(() => {
  if (props.task.status === "active") return "进行中";
  if (props.task.status === "waiting") return "等人工";
  if (props.task.status === "done") return "已完成";
  if (props.task.status === "dropped") return "已放弃";
  return props.task.actionable ? "可开工" : "被阻塞";
});

const hasDetails = computed(
  () =>
    Boolean(props.task.detail || props.task.accept || props.task.branch || props.task.pr) ||
    props.task.repositories.length > 0 ||
    props.task.open_blockers.length > 0,
);

function formatTime(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}
</script>

<template>
  <article class="task-row" :class="[`status-${task.status}`, { expanded }]">
    <button
      type="button"
      class="task-row-head"
      :disabled="!hasDetails"
      :aria-expanded="hasDetails ? expanded : undefined"
      @click="hasDetails && (expanded = !expanded)"
    >
      <span class="disclosure" :class="{ open: expanded, hidden: !hasDetails }" aria-hidden="true"></span>
      <span class="task-ref">#{{ task.ref }}</span>
      <span class="task-title">{{ task.title }}</span>
      <span v-if="task.gate" class="gate-chip">闸门</span>
      <span class="task-owner">{{ task.owner ? `@${task.owner}` : "未分配" }}</span>
      <span class="status-chip" :class="`status-${task.status}`">{{ statusLabel }}</span>
    </button>

    <div v-if="expanded && hasDetails" class="task-detail">
      <MarkdownBlock v-if="task.detail" :text="task.detail" />

      <dl class="task-facts">
        <div v-if="task.accept">
          <dt>验收</dt>
          <dd>{{ task.accept }}</dd>
        </div>
        <div v-if="task.repositories.length">
          <dt>仓库</dt>
          <dd>{{ task.repositories.map((repository) => repository.name).join(" · ") }}</dd>
        </div>
        <div v-if="task.branch">
          <dt>分支</dt>
          <dd><code>{{ task.branch }}</code></dd>
        </div>
        <div v-if="task.pr">
          <dt>PR</dt>
          <dd>#{{ task.pr }}</dd>
        </div>
        <div v-if="task.open_blockers.length">
          <dt>阻塞于</dt>
          <dd>{{ task.open_blockers.map((ref) => `#${ref}`).join("、") }}</dd>
        </div>
      </dl>

      <div class="task-timestamps">
        <span>创建 {{ formatTime(task.created_at) }}</span>
        <span v-if="task.first_started_at">开始 {{ formatTime(task.first_started_at) }}</span>
        <span>更新 {{ formatTime(task.updated_at) }}</span>
      </div>
    </div>
  </article>
</template>
