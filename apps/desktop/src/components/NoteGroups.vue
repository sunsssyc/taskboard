<script setup lang="ts">
import { IconChevronLeft, IconChevronRight } from "@tabler/icons-vue";
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
import { buildNoteSheets } from "../noteSheets";
import type { BoardNote } from "../types";

const SHEET_EDGE_CONTROL_WIDTH = 26;

const props = defineProps<{
  projectKey: string;
  findings: BoardNote[];
  risks: BoardNote[];
  links: BoardNote[];
  query: string;
}>();

const openNotes = reactive(new Set<number>());
const activeSheetId = ref("");
const sheetTabs = ref<HTMLElement | null>(null);
const canScrollLeft = ref(false);
const canScrollRight = ref(false);
let resizeObserver: ResizeObserver | null = null;
let layoutFrame = 0;
const sheets = computed(() => buildNoteSheets(props.findings, props.risks, props.links));
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

function updateSheetScrollState() {
  const element = sheetTabs.value;
  if (!element) return;
  const maxScrollLeft = Math.max(0, element.scrollWidth - element.clientWidth);
  canScrollLeft.value = element.scrollLeft > 1;
  canScrollRight.value = element.scrollLeft < maxScrollLeft - 1;
}

function revealActiveSheet(reset = false) {
  const element = sheetTabs.value;
  if (!element) return;
  if (reset) element.scrollLeft = 0;
  const active = element.querySelector<HTMLElement>(".sheet-tab.active");
  if (active) {
    const visibleLeft = element.scrollLeft + SHEET_EDGE_CONTROL_WIDTH;
    const visibleRight = element.scrollLeft + element.clientWidth - SHEET_EDGE_CONTROL_WIDTH;
    const tabLeft = active.offsetLeft;
    const tabRight = tabLeft + active.offsetWidth;
    if (tabLeft < visibleLeft) {
      element.scrollLeft = Math.max(0, tabLeft - SHEET_EDGE_CONTROL_WIDTH);
    } else if (tabRight > visibleRight) {
      element.scrollLeft = tabRight - element.clientWidth + SHEET_EDGE_CONTROL_WIDTH;
    }
  }
  updateSheetScrollState();
}

function settleSheetLayout(reset = false) {
  window.cancelAnimationFrame(layoutFrame);
  layoutFrame = window.requestAnimationFrame(() => {
    revealActiveSheet(reset);
    layoutFrame = window.requestAnimationFrame(() => revealActiveSheet(false));
  });
}

function scrollSheets(direction: -1 | 1) {
  const element = sheetTabs.value;
  if (!element) return;
  element.scrollBy({
    left: direction * Math.max(180, element.clientWidth * 0.7),
    behavior: "smooth",
  });
  window.setTimeout(updateSheetScrollState, 220);
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
</script>

<template>
  <section v-if="sheets.length" class="notes-panel">
    <div class="sheet-tab-bar">
      <button
        type="button"
        class="sheet-scroll-button"
        :disabled="!canScrollLeft"
        aria-label="向左查看更多结论 Sheet"
        @click="scrollSheets(-1)"
      >
        <IconChevronLeft :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <div
        ref="sheetTabs"
        class="sheet-tabs"
        role="tablist"
        aria-label="结论主题"
        @scroll="updateSheetScrollState"
      >
        <button
          v-for="(sheet, index) in sheets"
          :id="`note-sheet-tab-${index}`"
          :key="sheet.id"
          type="button"
          class="sheet-tab"
          :class="[`sheet-${sheet.kind}`, { active: sheet.id === activeSheet?.id }]"
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
      <button
        type="button"
        class="sheet-scroll-button"
        :disabled="!canScrollRight"
        aria-label="向右查看更多结论 Sheet"
        @click="scrollSheets(1)"
      >
        <IconChevronRight :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </div>

    <div class="sheet-workbook">
      <header class="panel-heading">
        <div>
          <h2>约束性结论</h2>
          <span class="eyebrow">按主题切换，后续决策以当前事实为准</span>
        </div>
        <span class="panel-count">{{ findings.length + risks.length + links.length }} 条</span>
      </header>

      <div
        v-if="activeSheet"
        :id="`note-sheet-panel-${activeSheetIndex}`"
        class="sheet-panel"
        :class="`sheet-panel-${activeSheet.kind}`"
        role="tabpanel"
        :aria-labelledby="`note-sheet-tab-${activeSheetIndex}`"
        tabindex="0"
      >
        <article
          v-for="note in activeSheet.notes"
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
</template>
