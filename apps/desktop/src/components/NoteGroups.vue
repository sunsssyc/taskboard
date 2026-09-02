<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import MarkdownBlock from "./MarkdownBlock.vue";
import ReferenceText from "./ReferenceText.vue";
import { buildNoteSheets, countSettled } from "../noteSheets";
import type { BoardReference } from "../references";
import type { BoardNote, NoteKind } from "../types";

const props = defineProps<{
  projectKey: string;
  findings: BoardNote[];
  risks: BoardNote[];
  links: BoardNote[];
  query: string;
  taskRefs: number[];
  noteRefs: number[];
}>();

defineEmits<{ reference: [reference: BoardReference] }>();

const openNotes = reactive(new Set<number>());
const activeSheetId = ref("");
const sheetTabs = ref<HTMLElement | null>(null);
const rootElement = ref<HTMLElement | null>(null);
let resizeObserver: ResizeObserver | null = null;
let layoutFrame = 0;
const showSettled = ref(false);
const settledCount = computed(() => countSettled(props.findings, props.risks, props.links));
const sheets = computed(() =>
  buildNoteSheets(props.findings, props.risks, props.links, showSettled.value),
);
const activeSheet = computed(
  () => sheets.value.find((sheet) => sheet.id === activeSheetId.value) ?? sheets.value[0],
);
const activeSheetIndex = computed(() =>
  Math.max(0, sheets.value.findIndex((sheet) => sheet.id === activeSheet.value?.id)),
);

watch(
  sheets,
  (nextSheets) => {
    if (!nextSheets.some((sheet) => sheet.id === activeSheetId.value)) {
      activeSheetId.value = nextSheets[0]?.id ?? "";
    }
  },
  { immediate: true },
);

function revealActiveSheet(reset = false) {
  const element = sheetTabs.value;
  if (!element) return;
  if (reset) element.scrollLeft = 0;
  const active = element.querySelector<HTMLElement>(".sheet-tab.active");
  if (active) {
    const visibleLeft = element.scrollLeft;
    const visibleRight = element.scrollLeft + element.clientWidth;
    const tabLeft = active.offsetLeft;
    const tabRight = tabLeft + active.offsetWidth;
    if (tabLeft < visibleLeft) {
      element.scrollLeft = Math.max(0, tabLeft);
    } else if (tabRight > visibleRight) {
      element.scrollLeft = tabRight - element.clientWidth;
    }
  }
}

function settleSheetLayout(reset = false) {
  window.cancelAnimationFrame(layoutFrame);
  layoutFrame = window.requestAnimationFrame(() => {
    revealActiveSheet(reset);
    layoutFrame = window.requestAnimationFrame(() => revealActiveSheet(false));
  });
}

watch(
  () => props.projectKey,
  async () => {
    await nextTick();
    settleSheetLayout(true);
  },
  { immediate: true },
);

watch(activeSheetId, async () => {
  await nextTick();
  settleSheetLayout(false);
});

onMounted(() => {
  resizeObserver = new ResizeObserver(() => settleSheetLayout(false));
  if (sheetTabs.value) resizeObserver.observe(sheetTabs.value);
  settleSheetLayout(true);
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  window.cancelAnimationFrame(layoutFrame);
});

function isOpen(note: BoardNote): boolean {
  return Boolean(props.query.trim()) || openNotes.has(note.id);
}

function toggleNote(id: number) {
  if (openNotes.has(id)) openNotes.delete(id);
  else openNotes.add(id);
}

function noteKindLabel(kind: NoteKind): string {
  return { finding: "结论", risk: "风险", link: "入口" }[kind];
}

async function selectAdjacentSheet(event: KeyboardEvent, index: number) {
  const buttons = (event.currentTarget as HTMLElement)
    .closest<HTMLElement>(".sheet-tabs")
    ?.querySelectorAll<HTMLButtonElement>(".sheet-tab");
  const target = buttons?.[index];
  if (!target) return;
  activeSheetId.value = sheets.value[index].id;
  await nextTick();
  target.focus();
}

function moveSheet(event: KeyboardEvent, currentIndex: number, delta: number) {
  const length = sheets.value.length;
  if (!length) return;
  const nextIndex = (currentIndex + delta + length) % length;
  void selectAdjacentSheet(event, nextIndex);
}

function flashTarget(target: HTMLElement) {
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.remove("flash");
  window.requestAnimationFrame(() => target.classList.add("flash"));
  window.setTimeout(() => target.classList.remove("flash"), 1250);
}

async function revealNote(id: number): Promise<boolean> {
  const sheet = sheets.value.find((item) => item.notes.some((note) => note.id === id));
  if (!sheet) return false;

  activeSheetId.value = sheet.id;
  openNotes.add(id);
  await nextTick();

  const target = rootElement.value?.querySelector<HTMLElement>(`.note-row[data-note-id="${id}"]`);
  if (!target) return false;
  flashTarget(target);
  return true;
}

defineExpose({ revealNote });
</script>

<template>
  <section v-if="sheets.length" ref="rootElement" class="notes-panel">
    <div class="sheet-tab-bar">
      <div
        ref="sheetTabs"
        class="sheet-tabs"
        role="tablist"
        aria-label="结论主题"
      >
        <button
          v-for="(sheet, index) in sheets"
          :id="`note-sheet-tab-${index}`"
          :key="sheet.id"
          type="button"
          class="sheet-tab"
          :class="{ active: sheet.id === activeSheet?.id }"
          role="tab"
          :aria-selected="sheet.id === activeSheet?.id"
          :aria-controls="`note-sheet-panel-${index}`"
          :tabindex="sheet.id === activeSheet?.id ? 0 : -1"
          @click="activeSheetId = sheet.id"
          @keydown.left.prevent="moveSheet($event, index, -1)"
          @keydown.right.prevent="moveSheet($event, index, 1)"
          @keydown.home.prevent="selectAdjacentSheet($event, 0)"
          @keydown.end.prevent="selectAdjacentSheet($event, sheets.length - 1)"
        >
          <span>{{ sheet.label }}</span>
          <b>{{ sheet.notes.length }}</b>
        </button>
      </div>
    </div>

    <div class="sheet-workbook">
      <header class="panel-heading">
        <div>
          <h2>主题记录</h2>
          <span class="eyebrow">结论、风险与入口按主题归档</span>
        </div>
        <span class="panel-count">
          <button
            v-if="settledCount > 0"
            type="button"
            class="settled-toggle"
            :class="{ active: showSettled }"
            @click="showSettled = !showSettled"
          >{{ showSettled ? '隐藏' : '显示' }} {{ settledCount }} 条已沉淀</button>
          <span v-else>{{ findings.length + risks.length + links.length }} 条</span>
        </span>
      </header>

      <div
        v-if="activeSheet"
        :id="`note-sheet-panel-${activeSheetIndex}`"
        class="sheet-panel"
        role="tabpanel"
        :aria-labelledby="`note-sheet-tab-${activeSheetIndex}`"
        tabindex="0"
      >
        <article
          v-for="note in activeSheet.notes"
          :key="note.id"
          class="note-row"
          :class="[`note-kind-${note.kind}`, { open: isOpen(note), superseded: note.is_superseded, settled: note.is_settled }]"
          :data-note-id="note.id"
        >
          <button
            type="button"
            class="note-row-head"
            :aria-expanded="isOpen(note)"
            @click="toggleNote(note.id)"
          >
            <span class="disclosure" :class="{ open: isOpen(note) }" aria-hidden="true"></span>
            <span class="note-id">[{{ note.id }}]</span>
            <span class="note-kind-badge" :class="`kind-${note.kind}`">{{ noteKindLabel(note.kind) }}</span>
            <strong>{{ note.title }}</strong>
            <span v-if="note.metric" class="note-metric">{{ note.metric }}</span>
          </button>
          <div v-if="isOpen(note)" class="note-body">
            <MarkdownBlock
              v-if="note.body"
              :text="note.body"
              :task-refs="taskRefs"
              :note-refs="noteRefs"
              @reference="$emit('reference', $event)"
            />
            <div v-if="note.supersedes.length" class="supersedes">
              推翻了
              <ReferenceText
                :text="note.supersedes.map((id) => `[${id}]`).join('、')"
                :task-refs="taskRefs"
                :note-refs="noteRefs"
                @activate="$emit('reference', $event)"
              />
            </div>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>
