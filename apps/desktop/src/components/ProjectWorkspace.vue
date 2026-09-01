<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import NoteGroups from "./NoteGroups.vue";
import ReferenceText from "./ReferenceText.vue";
import TaskGroups from "./TaskGroups.vue";
import { projectDisplayName } from "../projectName";
import type { BoardReference, BoardReferenceRequest } from "../references";
import type { BoardNote, BoardProject, BoardTask } from "../types";

const props = defineProps<{
  project: BoardProject;
  tasks: BoardTask[];
  findings: BoardNote[];
  risks: BoardNote[];
  links: BoardNote[];
  query: string;
  singleProject: boolean;
  focusReference: BoardReferenceRequest | null;
}>();

const emit = defineEmits<{
  showAll: [];
  reference: [reference: BoardReference];
}>();

const taskGroups = ref<InstanceType<typeof TaskGroups> | null>(null);
const noteGroups = ref<InstanceType<typeof NoteGroups> | null>(null);
const summaryElement = ref<HTMLElement | null>(null);
const summaryExpanded = ref(false);
const summaryCanExpand = ref(false);
const displayName = computed(() => projectDisplayName(props.project));
const summaryId = computed(() => `project-summary-${props.project.key}`);
const taskRefs = computed(() => props.project.tasks.map((task) => task.ref));
const noteRefs = computed(() => [
  ...props.project.findings,
  ...props.project.risks,
  ...props.project.links,
].map((note) => note.id));

let summaryResizeObserver: ResizeObserver | null = null;

function measureSummaryOverflow(): void {
  const element = summaryElement.value;
  if (!element || summaryExpanded.value) return;
  summaryCanExpand.value = element.scrollHeight > element.clientHeight + 1;
}

function toggleSummary(): void {
  summaryExpanded.value = !summaryExpanded.value;
  if (!summaryExpanded.value) void nextTick(measureSummaryOverflow);
}

async function revealReference(reference: BoardReference): Promise<boolean> {
  await nextTick();
  if (reference.kind === "task") return taskGroups.value?.revealTask(reference.id) ?? false;
  return noteGroups.value?.revealNote(reference.id) ?? false;
}

watch(
  () => props.focusReference,
  (request) => {
    if (request) void revealReference(request);
  },
);

watch(
  () => [props.project.key, props.project.summary],
  async () => {
    summaryExpanded.value = false;
    summaryCanExpand.value = false;
    await nextTick();
    measureSummaryOverflow();
  },
  { immediate: true },
);

onMounted(() => {
  if (typeof ResizeObserver !== "undefined") {
    summaryResizeObserver = new ResizeObserver(measureSummaryOverflow);
    if (summaryElement.value) summaryResizeObserver.observe(summaryElement.value);
  }
  void nextTick(measureSummaryOverflow);
});

onBeforeUnmount(() => summaryResizeObserver?.disconnect());
</script>

<template>
  <section class="project-workspace" :data-project="project.key">
    <div v-if="singleProject" class="filter-context">
      <span>只看 {{ displayName }}</span>
      <button type="button" @click="$emit('showAll')">显示全部需求</button>
    </div>

    <header class="project-heading">
      <div class="project-heading-copy">
        <div class="project-heading-line">
          <h2>{{ displayName }}</h2>
        </div>
      </div>

      <dl class="project-heading-meta" aria-label="需求概览">
        <div class="project-heading-stat">
          <dt>完成</dt>
          <dd>{{ project.counts.done }}</dd>
        </div>
        <div class="project-heading-stat">
          <dt>待办</dt>
          <dd>{{ project.counts.todo }}</dd>
        </div>
        <div class="project-heading-repositories">
          <dt>仓库</dt>
          <dd>
            <span
              v-for="repository in project.repositories"
              :key="repository.name"
              class="repository-chip"
            >
              {{ repository.name }}
            </span>
            <span v-if="!project.repositories.length" class="project-heading-empty">未关联</span>
          </dd>
        </div>
      </dl>

      <div class="project-heading-summary-block">
        <p
          :id="summaryId"
          ref="summaryElement"
          class="project-heading-summary"
          :class="{ expanded: summaryExpanded }"
        >
          <ReferenceText
            :text="project.summary || '持续保存目标、进度、结论和下一步。'"
            :task-refs="taskRefs"
            :note-refs="noteRefs"
            @activate="emit('reference', $event)"
          />
        </p>
        <button
          v-if="summaryCanExpand"
          type="button"
          class="project-heading-summary-control"
          :aria-controls="summaryId"
          :aria-expanded="summaryExpanded"
          @click="toggleSummary"
        >
          {{ summaryExpanded ? "收起简介" : "展开简介" }}
        </button>
      </div>
    </header>

    <TaskGroups
      ref="taskGroups"
      :tasks="tasks"
      :project-key="project.key"
      :query="query"
      :task-refs="taskRefs"
      :note-refs="noteRefs"
      @reference="emit('reference', $event)"
    />

    <NoteGroups
      ref="noteGroups"
      :key="`${project.key}:notes`"
      :project-key="project.key"
      :findings="findings"
      :risks="risks"
      :links="links"
      :query="query"
      :task-refs="taskRefs"
      :note-refs="noteRefs"
      @reference="emit('reference', $event)"
    />
  </section>
</template>
