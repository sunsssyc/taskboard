<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import MarkdownBlock from "./MarkdownBlock.vue";
import { useBoardStore } from "../stores/board";
import { OWNER_OPTIONS, ownerLabel } from "../owner";
import type { BoardTask, TaskOwner, TaskStatus } from "../types";

const props = defineProps<{ task: BoardTask; projectKey: string; query: string }>();
const board = useBoardStore();
const expanded = ref(props.task.status === "active");
const rootElement = ref<HTMLElement | null>(null);
const statusMenuOpen = ref(false);
const ownerMenuOpen = ref(false);
const confirmingDone = ref(false);

watch(
  () => props.query,
  (query) => {
    if (query.trim()) expanded.value = true;
  },
);

const statusOptions: { value: TaskStatus; label: string }[] = [
  { value: "todo", label: "待办" },
  { value: "active", label: "进行中" },
  { value: "waiting", label: "等人工" },
  { value: "done", label: "已完成" },
];

const switchableOptions = computed(() =>
  statusOptions.filter((option) => option.value !== props.task.status),
);

function closeMenus() {
  statusMenuOpen.value = false;
  ownerMenuOpen.value = false;
  confirmingDone.value = false;
}

function toggleStatusMenu() {
  const next = !statusMenuOpen.value;
  closeMenus();
  statusMenuOpen.value = next;
}

function toggleOwnerMenu() {
  const next = !ownerMenuOpen.value;
  closeMenus();
  ownerMenuOpen.value = next;
}

function chooseStatus(status: TaskStatus) {
  if (status === "done") {
    confirmingDone.value = true;
    return;
  }
  applyStatus(status);
}

function applyStatus(status: TaskStatus) {
  closeMenus();
  void board.setTaskStatus(props.projectKey, props.task.ref, status);
}

function applyOwner(owner: TaskOwner) {
  closeMenus();
  if ((props.task.owner ?? "") === owner) return;
  void board.setTaskOwner(props.projectKey, props.task.ref, owner);
}

function onDocumentPointerDown(event: MouseEvent) {
  if (!(event.target instanceof Node) || !rootElement.value?.contains(event.target)) {
    closeMenus();
  }
}

watch(() => statusMenuOpen.value || ownerMenuOpen.value, (open) => {
  if (open) document.addEventListener("mousedown", onDocumentPointerDown);
  else document.removeEventListener("mousedown", onDocumentPointerDown);
});

onBeforeUnmount(() => {
  document.removeEventListener("mousedown", onDocumentPointerDown);
});

const statusLabel = computed(() => {
  if (props.task.status === "active") return "进行中";
  if (props.task.status === "waiting") return "等人工";
  if (props.task.status === "done") return "已完成";
  if (props.task.status === "dropped") return "已放弃";
  return props.task.actionable ? "可开工" : "被阻塞";
});

const statusClass = computed(() => {
  if (props.task.status === "todo" && !props.task.actionable) return "status-blocked";
  return `status-${props.task.status}`;
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
  <article
    ref="rootElement"
    class="task-row"
    :class="[`status-${task.status}`, { expanded }]"
    :data-ref="task.ref"
  >
    <div class="task-row-head">
      <button
        type="button"
        class="task-row-summary"
        :class="{ static: !hasDetails }"
        :aria-expanded="hasDetails ? expanded : undefined"
        @click="hasDetails && (expanded = !expanded)"
      >
        <span class="disclosure" :class="{ open: expanded, hidden: !hasDetails }" aria-hidden="true"></span>
        <span class="task-ref">#{{ task.ref }}</span>
        <span class="task-title">{{ task.title }}</span>
        <span v-if="task.gate" class="gate-chip">闸门</span>
      </button>

      <div class="task-owner-control">
        <button
          type="button"
          class="task-owner task-owner-button"
          :class="{ unassigned: !task.owner }"
          aria-haspopup="menu"
          :aria-expanded="ownerMenuOpen"
          title="点击修改负责人"
          @click="toggleOwnerMenu"
        >
          <span>{{ task.owner ? `@${ownerLabel(task.owner)}` : "未分配" }}</span>
          <span class="owner-caret" aria-hidden="true"></span>
        </button>
        <div v-if="ownerMenuOpen" class="owner-menu" role="menu" aria-label="分配任务负责人">
          <button
            v-for="option in OWNER_OPTIONS"
            :key="option.value || 'unassigned'"
            type="button"
            role="menuitemradio"
            class="owner-menu-item"
            :aria-checked="(task.owner ?? '') === option.value"
            @click="applyOwner(option.value)"
          >
            <span class="owner-menu-mark" aria-hidden="true">
              {{ (task.owner ?? "") === option.value ? "✓" : "" }}
            </span>
            {{ option.label }}
          </button>
        </div>
      </div>

      <span v-if="task.repositories.length" class="task-repositories">
        <span v-for="repository in task.repositories" :key="repository.name">
          {{ repository.name }}
        </span>
      </span>
      <button
        type="button"
        class="status-chip status-chip-button"
        :class="statusClass"
        aria-haspopup="menu"
        :aria-expanded="statusMenuOpen"
        title="点击切换状态"
        @click="toggleStatusMenu"
      >{{ statusLabel }}</button>
    </div>

    <div v-if="statusMenuOpen" class="status-menu" role="menu" aria-label="切换任务状态">
      <template v-if="!confirmingDone">
        <button
          v-for="option in switchableOptions"
          :key="option.value"
          type="button"
          role="menuitem"
          class="status-menu-item"
          @click="chooseStatus(option.value)"
        >
          <span class="status-dot" :class="`status-${option.value}`" aria-hidden="true"></span>
          {{ option.label }}
        </button>
      </template>
      <div v-else class="status-confirm">
        <strong>确认完成 #{{ task.ref }}?</strong>
        <MarkdownBlock v-if="task.accept" :text="task.accept" />
        <span v-else class="status-confirm-hint">该任务没有登记验收条件。</span>
        <div class="status-confirm-actions">
          <button type="button" class="secondary-button" @click="closeMenus">取消</button>
          <button type="button" class="primary-button" @click="applyStatus('done')">确认完成</button>
        </div>
      </div>
    </div>

    <div v-if="expanded && hasDetails" class="task-detail">
      <MarkdownBlock v-if="task.detail" :text="task.detail" />

      <div v-if="task.accept && task.status !== 'done'" class="acceptance-block">
        <strong class="acceptance-label">验收</strong>
        <MarkdownBlock :text="task.accept" />
      </div>

      <dl class="task-facts">
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
