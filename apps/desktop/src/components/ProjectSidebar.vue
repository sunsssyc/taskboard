<script setup lang="ts">
import { PanelLeft } from "@lucide/vue";
import { computed, onBeforeUnmount, ref } from "vue";
import type { BoardProject, BoardTask } from "../types";

const props = defineProps<{
  projects: BoardProject[];
  selectedKey: string;
  collapsed: boolean;
  pinnedKeys: string[];
  source: string;
  database: string | null;
  preferenceError: string;
}>();

const draggingKey = ref("");
const dropTargetKey = ref("");
const dropBefore = ref(true);
const dragPointerX = ref(0);
const dragPointerY = ref(0);
const dropConfirmedKey = ref("");
const dropNotice = ref("");
let dropNoticeTimer: number | undefined;
let pointerDrag: { key: string; startX: number; startY: number; active: boolean } | null = null;
let suppressClickKey = "";

const draggingProject = computed(() =>
  props.projects.find((project) => project.key === draggingKey.value),
);
const dropTargetProject = computed(() =>
  props.projects.find((project) => project.key === dropTargetKey.value),
);
const dragHint = computed(() => {
  if (!dropTargetProject.value) return "拖到目标需求的前方或后方";
  return `移到「${dropTargetProject.value.name}」${dropBefore.value ? "前方" : "后方"}`;
});

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

function isPinned(key: string): boolean {
  return props.pinnedKeys.includes(key);
}

function clearDragState() {
  document.body.classList.remove("project-drag-active");
  draggingKey.value = "";
  dropTargetKey.value = "";
  dropBefore.value = true;
  dragPointerX.value = 0;
  dragPointerY.value = 0;
}

function removePointerListeners() {
  window.removeEventListener("pointermove", onPointerMove);
  window.removeEventListener("pointerup", onPointerUp);
  window.removeEventListener("pointercancel", onPointerUp);
}

function onPointerDown(event: PointerEvent, key: string) {
  if (event.button !== 0 || event.pointerType !== "mouse") return;
  pointerDrag = { key, startX: event.clientX, startY: event.clientY, active: false };
  window.addEventListener("pointermove", onPointerMove, { passive: false });
  window.addEventListener("pointerup", onPointerUp, { once: true });
  window.addEventListener("pointercancel", onPointerUp, { once: true });
}

function onPointerMove(event: PointerEvent) {
  if (!pointerDrag) return;
  if (!pointerDrag.active) {
    const distance = Math.hypot(
      event.clientX - pointerDrag.startX,
      event.clientY - pointerDrag.startY,
    );
    if (distance < 6) return;
    pointerDrag.active = true;
    draggingKey.value = pointerDrag.key;
    document.body.classList.add("project-drag-active");
  }
  event.preventDefault();
  dragPointerX.value = event.clientX;
  dragPointerY.value = event.clientY;
  const target = document
    .elementFromPoint(event.clientX, event.clientY)
    ?.closest<HTMLElement>(".project-group");
  const targetKey = target?.dataset.projectKey ?? "";
  if (!target || !targetKey || targetKey === pointerDrag.key) {
    dropTargetKey.value = "";
    return;
  }
  const bounds = target.getBoundingClientRect();
  const list = target.closest<HTMLElement>(".project-list");
  const horizontal = list ? getComputedStyle(list).flexDirection === "row" : false;
  dropTargetKey.value = targetKey;
  dropBefore.value = horizontal
    ? event.clientX < bounds.left + bounds.width / 2
    : event.clientY < bounds.top + bounds.height / 2;
}

function onPointerUp() {
  if (pointerDrag?.active && dropTargetKey.value) {
    const target = dropTargetProject.value;
    const placement = dropBefore.value ? "前方" : "后方";
    emit("reorder", pointerDrag.key, dropTargetKey.value, dropBefore.value);
    dropConfirmedKey.value = dropTargetKey.value;
    dropNotice.value = target ? `已移到「${target.name}」${placement}` : "需求顺序已更新";
    window.clearTimeout(dropNoticeTimer);
    dropNoticeTimer = window.setTimeout(() => {
      dropConfirmedKey.value = "";
      dropNotice.value = "";
    }, 950);
    suppressClickKey = pointerDrag.key;
    window.setTimeout(() => { suppressClickKey = ""; }, 0);
  }
  pointerDrag = null;
  removePointerListeners();
  clearDragState();
}

function onProjectClick(key: string) {
  if (suppressClickKey === key) return;
  emit("select", key);
}

const emit = defineEmits<{
  select: [key: string];
  selectAll: [];
  toggleCollapse: [];
  focusTask: [ref: number];
  togglePin: [key: string];
  reorder: [draggedKey: string, targetKey: string, before: boolean];
}>();

onBeforeUnmount(() => {
  pointerDrag = null;
  window.clearTimeout(dropNoticeTimer);
  removePointerListeners();
  clearDragState();
});
</script>

<template>
  <aside class="navigator" :class="{ collapsed }">
    <div class="navigator-head">
      <span class="navigator-title">需求</span>
      <b class="navigator-count">{{ projects.length }}</b>
      <button
        type="button"
        class="navigator-toggle"
        :class="{ collapsed }"
        :title="collapsed ? '展开需求栏' : '收起需求栏'"
        :aria-label="collapsed ? '展开需求栏' : '收起需求栏'"
        :aria-expanded="!collapsed"
        aria-controls="project-navigation-list"
        @click="$emit('toggleCollapse')"
      >
        <PanelLeft :size="18" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </div>

    <nav id="project-navigation-list" class="project-list" aria-label="需求工作流">
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
        :data-project-key="project.key"
        :class="{
          selected: project.key === selectedKey,
          pinned: isPinned(project.key),
          dragging: draggingKey === project.key,
          'drop-before': dropTargetKey === project.key && dropBefore,
          'drop-after': dropTargetKey === project.key && !dropBefore,
          'drop-confirmed': dropConfirmedKey === project.key,
        }"
      >
        <button
          type="button"
          class="project-card"
          :aria-pressed="project.key === selectedKey"
          @pointerdown="onPointerDown($event, project.key)"
          @click="onProjectClick(project.key)"
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

        <button
          type="button"
          class="pin-button"
          :class="{ active: isPinned(project.key) }"
          :title="isPinned(project.key) ? '取消置顶' : '置顶'"
          :aria-label="`${isPinned(project.key) ? '取消置顶' : '置顶'} ${project.name}`"
          :aria-pressed="isPinned(project.key)"
          @click.stop="$emit('togglePin', project.key)"
        >
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <g transform="rotate(45 6 6)" fill="currentColor">
              <circle cx="6" cy="3.1" r="1.8"></circle>
              <rect x="5.3" y="4.2" width="1.4" height="5.6" rx=".7"></rect>
            </g>
          </svg>
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
        <strong :class="{ error: preferenceError }">
          {{ preferenceError || source || "正在连接…" }}
        </strong>
        <small :title="database ?? ''">{{ database || "数据库路径已隐藏" }}</small>
      </span>
    </footer>
  </aside>

  <Teleport to="body">
    <Transition name="drag-preview">
      <div
        v-if="draggingProject"
        class="project-drag-preview"
        :style="{ left: `${dragPointerX}px`, top: `${dragPointerY}px` }"
        aria-hidden="true"
      >
        <span class="drag-grip">⋮⋮</span>
        <span class="drag-preview-copy">
          <code>{{ draggingProject.key }}</code>
          <strong>{{ draggingProject.name }}</strong>
          <small>{{ dragHint }}</small>
        </span>
      </div>
    </Transition>
    <Transition name="drop-notice">
      <div v-if="dropNotice" class="project-drop-notice" aria-live="polite">
        <span aria-hidden="true">✓</span>{{ dropNotice }}
      </div>
    </Transition>
  </Teleport>
</template>
