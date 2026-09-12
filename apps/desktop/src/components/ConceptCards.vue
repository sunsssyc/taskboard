<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import ConceptCard from "./ConceptCard.vue";
import { groupConcepts } from "../concepts";
import type { BoardConcept } from "../types";

const props = defineProps<{
  projectKey: string;
  concepts: BoardConcept[];
  query: string;
}>();

const emit = defineEmits<{ focusTask: [ref: number] }>();

// 待对齐/需重新对齐默认展开(它们就是要人读的),记录的是"被收起";其余默认折叠,记录"被展开"
const collapsedPending = reactive(new Set<number>());
const openedOthers = reactive(new Set<number>());
const expandedGroups = reactive<Record<"aligned" | "rejected", boolean>>({
  aligned: false,
  rejected: false,
});

const groups = computed(() => groupConcepts(props.concepts));
const archiveGroups = computed(() => [
  { key: "aligned" as const, label: "已对齐", concepts: groups.value.aligned },
  { key: "rejected" as const, label: "已否决", concepts: groups.value.rejected },
]);

watch(
  () => props.query,
  (query) => {
    if (query.trim()) {
      expandedGroups.aligned = true;
      expandedGroups.rejected = true;
    }
  },
);

function isPending(concept: BoardConcept): boolean {
  return concept.state === "proposed" || concept.state === "stale";
}

function isOpen(concept: BoardConcept): boolean {
  if (isPending(concept)) return !collapsedPending.has(concept.id);
  return Boolean(props.query.trim()) || openedOthers.has(concept.id);
}

function toggle(concept: BoardConcept) {
  const set = isPending(concept) ? collapsedPending : openedOthers;
  if (set.has(concept.id)) set.delete(concept.id);
  else set.add(concept.id);
}

function groupOpen(key: "aligned" | "rejected"): boolean {
  return Boolean(props.query.trim()) || expandedGroups[key];
}
</script>

<template>
  <section v-if="concepts.length" class="concept-panel" :data-project="projectKey">
    <header class="panel-heading">
      <div>
        <h2>概念对齐</h2>
        <span class="eyebrow">
          待你确认 {{ groups.pending.length }} · 已对齐 {{ groups.aligned.length }}
          <template v-if="groups.rejected.length"> · 已否决 {{ groups.rejected.length }}</template>
        </span>
      </div>
      <span class="panel-count">{{ concepts.length }} 张</span>
    </header>

    <div class="concept-list">
      <ConceptCard
        v-for="concept in groups.pending"
        :key="concept.id"
        :concept="concept"
        :project-key="projectKey"
        :open="isOpen(concept)"
        @toggle="toggle(concept)"
        @focus-task="emit('focusTask', $event)"
      />
      <p v-if="!groups.pending.length" class="concept-empty">没有等你确认的概念。</p>

      <section
        v-for="group in archiveGroups"
        v-show="group.concepts.length"
        :key="group.key"
        class="archive-group concept-group"
      >
        <button
          type="button"
          class="archive-heading"
          :aria-expanded="groupOpen(group.key)"
          @click="expandedGroups[group.key] = !expandedGroups[group.key]"
        >
          <span class="disclosure" :class="{ open: groupOpen(group.key) }" aria-hidden="true"></span>
          <span>{{ group.label }} {{ group.concepts.length }} 张</span>
        </button>
        <div v-if="groupOpen(group.key)" class="archive-tasks">
          <ConceptCard
            v-for="concept in group.concepts"
            :key="concept.id"
            :concept="concept"
            :project-key="projectKey"
            :open="isOpen(concept)"
            @toggle="toggle(concept)"
            @focus-task="emit('focusTask', $event)"
          />
        </div>
      </section>
    </div>
  </section>
</template>
