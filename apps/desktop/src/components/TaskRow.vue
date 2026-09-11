<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { Send } from "@lucide/vue";
import MarkdownBlock from "./MarkdownBlock.vue";
import { useBoardStore } from "../stores/board";
import { OWNER_OPTIONS, ownerLabel } from "../owner";
import { PRIORITY_OPTIONS } from "../priority";
import type { BoardReference } from "../references";
import type { AgentProvider, BoardTask, TaskOwner, TaskPriority, TaskStatus } from "../types";

const props = withDefaults(defineProps<{
  task: BoardTask;
  projectKey: string;
  query: string;
  initiallyExpanded?: boolean;
  focusRequested?: boolean;
  taskRefs?: number[];
  noteRefs?: number[];
}>(), {
  initiallyExpanded: false,
  focusRequested: false,
  taskRefs: () => [],
  noteRefs: () => [],
});

defineEmits<{ reference: [reference: BoardReference] }>();

const board = useBoardStore();
const expanded = ref(props.initiallyExpanded);
const rootElement = ref<HTMLElement | null>(null);
const statusMenuOpen = ref(false);
const ownerMenuOpen = ref(false);
const priorityMenuOpen = ref(false);
const agentMenuOpen = ref(false);
const confirmingDone = ref(false);

const hasDetails = computed(
  () =>
    Boolean(props.task.detail || props.task.accept || props.task.branch || props.task.pr) ||
    props.task.repositories.length > 0 ||
    props.task.agent_runs.length > 0 ||
    props.task.open_blockers.length > 0,
);

watch(
  () => props.query,
  (query) => {
    if (query.trim()) expanded.value = true;
  },
);

watch(
  () => props.focusRequested,
  (requested) => {
    if (requested && hasDetails.value) expanded.value = true;
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

const agentOptions: { value: AgentProvider; label: string; hint: string }[] = [
  { value: "codex", label: "Codex", hint: "创建线程并立即提交" },
  { value: "claude", label: "Claude", hint: "打开桌面端并预填" },
];
const dispatchRepositories = computed(() =>
  props.task.repositories.filter(
    (repository): repository is typeof repository & { path: string } => Boolean(repository.path),
  ),
);
const latestAgentRun = computed(() => props.task.agent_runs[0] ?? null);
const dispatching = computed(
  () => board.dispatchingTask === `${props.projectKey}:${props.task.ref}`,
);

function closeMenus() {
  statusMenuOpen.value = false;
  ownerMenuOpen.value = false;
  priorityMenuOpen.value = false;
  agentMenuOpen.value = false;
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

function togglePriorityMenu() {
  const next = !priorityMenuOpen.value;
  closeMenus();
  priorityMenuOpen.value = next;
}

function toggleAgentMenu() {
  if (dispatching.value) return;
  const next = !agentMenuOpen.value;
  closeMenus();
  agentMenuOpen.value = next;
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

function applyPriority(priority: TaskPriority) {
  closeMenus();
  if (props.task.priority === priority) return;
  void board.setTaskPriority(props.projectKey, props.task.ref, priority);
}

function applyDispatch(provider: AgentProvider, repositoryPath: string) {
  closeMenus();
  void board.dispatchTask(
    props.projectKey,
    props.task,
    provider,
    repositoryPath,
  );
}

function onDocumentPointerDown(event: MouseEvent) {
  if (!(event.target instanceof Node) || !rootElement.value?.contains(event.target)) {
    closeMenus();
  }
}

watch(
  () => statusMenuOpen.value || ownerMenuOpen.value || priorityMenuOpen.value || agentMenuOpen.value,
  (open) => {
    if (open) document.addEventListener("mousedown", onDocumentPointerDown);
    else document.removeEventListener("mousedown", onDocumentPointerDown);
  },
);

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


function agentProviderLabel(provider: AgentProvider): string {
  return provider === "codex" ? "Codex" : "Claude";
}

function agentRunLabel(): string {
  if (!latestAgentRun.value) return "";
  if (latestAgentRun.value.status === "submitted") return "已提交";
  if (latestAgentRun.value.status === "opened") return "待确认发送";
  return "失败";
}

function shortIdentifier(value: string): string {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value;
}
</script>

<template>
  <article
    ref="rootElement"
    class="task-row"
    :class="[`status-${task.status}`, { expanded, 'menu-open': statusMenuOpen || ownerMenuOpen || priorityMenuOpen || agentMenuOpen }]"
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

      <div class="task-priority-control">
        <button
          type="button"
          class="priority-chip"
          :class="`priority-${task.priority}`"
          aria-haspopup="menu"
          :aria-expanded="priorityMenuOpen"
          :title="`当前 P${task.priority}，点击调整优先级`"
          @click="togglePriorityMenu"
        >P{{ task.priority }}</button>
        <div v-if="priorityMenuOpen" class="priority-menu" role="menu" aria-label="调整任务优先级">
          <button
            v-for="option in PRIORITY_OPTIONS"
            :key="option.value"
            type="button"
            role="menuitemradio"
            class="priority-menu-item"
            :aria-checked="task.priority === option.value"
            @click="applyPriority(option.value)"
          >
            <span class="priority-menu-mark" aria-hidden="true">
              {{ task.priority === option.value ? "✓" : "" }}
            </span>
            <strong>{{ option.label }}</strong>
            <small>{{ option.hint }}</small>
          </button>
        </div>
      </div>

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

      <div class="task-agent-control">
        <button
          type="button"
          class="agent-dispatch-button"
          :class="{ busy: dispatching }"
          :disabled="dispatching"
          aria-haspopup="menu"
          :aria-expanded="agentMenuOpen"
          title="派发给本地桌面 Agent"
          @click="toggleAgentMenu"
        >
          <Send :size="13" :stroke-width="1.8" aria-hidden="true" />
          <span>{{ dispatching ? "派发中" : "派发" }}</span>
        </button>
        <div v-if="agentMenuOpen" class="agent-menu" role="menu" aria-label="派发给桌面 Agent">
          <div class="agent-menu-heading">选择 Agent 与工作目录</div>
          <template v-if="dispatchRepositories.length">
            <template v-for="agent in agentOptions" :key="agent.value">
              <button
                v-for="repository in dispatchRepositories"
                :key="`${agent.value}:${repository.path}`"
                type="button"
                role="menuitem"
                class="agent-menu-item"
                @click="applyDispatch(agent.value, repository.path)"
              >
                <span class="agent-menu-provider">{{ agent.label }}</span>
                <span class="agent-menu-meta">
                  {{ agent.hint }}
                  <small>{{ repository.name }}</small>
                </span>
              </button>
            </template>
          </template>
          <div v-else class="agent-menu-empty">任务没有可用的本地仓库路径，无法派发。</div>
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
        <MarkdownBlock
          v-if="task.accept"
          :text="task.accept"
          :task-refs="taskRefs"
          :note-refs="noteRefs"
          @reference="$emit('reference', $event)"
        />
        <span v-else class="status-confirm-hint">该任务没有登记验收条件。</span>
        <div class="status-confirm-actions">
          <button type="button" class="secondary-button" @click="closeMenus">取消</button>
          <button type="button" class="primary-button" @click="applyStatus('done')">确认完成</button>
        </div>
      </div>
    </div>

    <div v-if="expanded && hasDetails" class="task-detail">
      <MarkdownBlock
        v-if="task.detail"
        :text="task.detail"
        :task-refs="taskRefs"
        :note-refs="noteRefs"
        @reference="$emit('reference', $event)"
      />

      <div v-if="task.accept && task.status !== 'done'" class="acceptance-block">
        <strong class="acceptance-label">验收</strong>
        <MarkdownBlock
          :text="task.accept"
          :task-refs="taskRefs"
          :note-refs="noteRefs"
          @reference="$emit('reference', $event)"
        />
      </div>

      <dl class="task-facts">
        <div v-if="latestAgentRun">
          <dt>Agent</dt>
          <dd class="agent-run-fact">
            <strong>{{ agentProviderLabel(latestAgentRun.provider) }} {{ agentRunLabel() }}</strong>
            <code>
              {{ shortIdentifier(latestAgentRun.external_thread_id || latestAgentRun.dispatch_id) }}
            </code>
            <span>{{ formatTime(latestAgentRun.started_at) }}</span>
          </dd>
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
