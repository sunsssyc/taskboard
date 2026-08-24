<script setup lang="ts">
import { computed, reactive } from "vue";
import MarkdownBlock from "./MarkdownBlock.vue";
import type { BoardNote } from "../types";

const props = defineProps<{
  findings: BoardNote[];
  risks: BoardNote[];
  links: BoardNote[];
  query: string;
}>();

const openNotes = reactive(new Set<number>());
const collapsedSections = reactive<Record<string, boolean>>({
  finding: false,
  risk: false,
  link: false,
});

const sections = computed(() => [
  {
    key: "finding",
    title: "已定结论",
    hint: "后续决策以这些事实为准",
    notes: props.findings,
  },
  {
    key: "risk",
    title: "风险与尾巴",
    hint: "暂不阻塞主线，但不能遗忘",
    notes: props.risks,
  },
  {
    key: "link",
    title: "关键入口",
    hint: "交付文件与外部坐标",
    notes: props.links,
  },
]);

function categoryGroups(notes: BoardNote[]) {
  const groups = new Map<string, BoardNote[]>();
  for (const note of notes) {
    const category = note.category || "未分类";
    groups.set(category, [...(groups.get(category) ?? []), note]);
  }
  return [...groups.entries()].map(([category, items]) => ({ category, items }));
}

function isOpen(note: BoardNote): boolean {
  return Boolean(props.query.trim()) || openNotes.has(note.id);
}

function toggleNote(id: number) {
  if (openNotes.has(id)) openNotes.delete(id);
  else openNotes.add(id);
}
</script>

<template>
  <section v-if="findings.length || risks.length || links.length" class="notes-panel">
    <header class="panel-heading">
      <div>
        <span class="eyebrow">知识与交付</span>
        <h2>结论、风险和入口</h2>
      </div>
      <span class="panel-count">{{ findings.length + risks.length + links.length }} 条</span>
    </header>

    <div class="note-sections">
      <section
        v-for="section in sections"
        v-show="section.notes.length"
        :key="section.key"
        class="note-section"
        :class="`note-${section.key}`"
      >
        <button
          type="button"
          class="note-section-heading"
          :aria-expanded="!collapsedSections[section.key]"
          @click="collapsedSections[section.key] = !collapsedSections[section.key]"
        >
          <span class="disclosure" :class="{ open: !collapsedSections[section.key] }" aria-hidden="true"></span>
          <strong>{{ section.title }}</strong>
          <span class="group-count">{{ section.notes.length }}</span>
          <span class="group-hint">{{ section.hint }}</span>
        </button>

        <div v-if="!collapsedSections[section.key]" class="category-list">
          <div v-for="group in categoryGroups(section.notes)" :key="group.category" class="category-group">
            <h3>{{ group.category }} <span>{{ group.items.length }}</span></h3>
            <article
              v-for="note in group.items"
              :key="note.id"
              class="note-row"
              :class="{ open: isOpen(note), superseded: note.is_superseded }"
            >
              <button
                type="button"
                class="note-row-head"
                :aria-expanded="isOpen(note)"
                @click="toggleNote(note.id)"
              >
                <span class="disclosure" :class="{ open: isOpen(note) }" aria-hidden="true"></span>
                <span class="note-id">[{{ note.id }}]</span>
                <strong>{{ note.title }}</strong>
                <span v-if="note.metric" class="note-metric">{{ note.metric }}</span>
              </button>
              <div v-if="isOpen(note)" class="note-body">
                <MarkdownBlock v-if="note.body" :text="note.body" />
                <div v-if="note.supersedes.length" class="supersedes">
                  推翻了 {{ note.supersedes.map((id) => `[${id}]`).join("、") }}
                </div>
              </div>
            </article>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>
