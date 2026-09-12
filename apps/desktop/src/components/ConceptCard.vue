<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import MarkdownBlock from "./MarkdownBlock.vue";
import { useBoardStore } from "../stores/board";
import { CONCEPT_STATE_LABEL } from "../concepts";
import type { BoardConcept, ConceptEdit } from "../types";

const props = defineProps<{
  concept: BoardConcept;
  projectKey: string;
  open: boolean;
}>();

const emit = defineEmits<{ toggle: []; focusTask: [ref: number] }>();
const board = useBoardStore();

const rejecting = ref(false);
const rejectReason = ref("");
const editing = ref(false);
const editDraft = reactive({ title: "", body: "", keepAligned: false });

const pending = computed(() => props.concept.state === "proposed" || props.concept.state === "stale");
const busy = computed(() => board.conceptBusy === props.concept.id);
const scopeLabel = computed(() => props.concept.repository ?? "需求概念");
const editChanged = computed(
  () =>
    editDraft.title.trim() !== props.concept.title
    || editDraft.body.trim() !== (props.concept.body ?? ""),
);

function anchorLabel(anchor: { path: string; symbol: string }): string {
  return anchor.symbol ? `${anchor.path}:${anchor.symbol}` : anchor.path;
}

function formatTime(value: string | null): string {
  if (!value) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function cancelForms() {
  rejecting.value = false;
  rejectReason.value = "";
  editing.value = false;
}

async function align() {
  cancelForms();
  await board.alignConcept(props.concept.id);
}

function startReject() {
  cancelForms();
  rejecting.value = true;
}

async function confirmReject() {
  const reason = rejectReason.value.trim();
  if (!reason) return;
  if (await board.rejectConcept(props.concept.id, reason)) cancelForms();
}

function startEdit() {
  cancelForms();
  editing.value = true;
  editDraft.title = props.concept.title;
  editDraft.body = props.concept.body ?? "";
  editDraft.keepAligned = false;
}

async function confirmEdit() {
  if (!editChanged.value || !editDraft.title.trim()) return;
  const edit: ConceptEdit = {};
  if (editDraft.title.trim() !== props.concept.title) edit.title = editDraft.title.trim();
  if (editDraft.body.trim() !== (props.concept.body ?? "")) edit.body = editDraft.body.trim();
  if (props.concept.state === "aligned" && editDraft.keepAligned) edit.keepAligned = true;
  if (await board.editConcept(props.concept.id, edit)) cancelForms();
}
</script>

<template>
  <article
    class="concept-card"
    :class="[`concept-${concept.state}`, { open, busy }]"
    :data-concept="concept.id"
  >
    <button type="button" class="concept-card-head" :aria-expanded="open" @click="emit('toggle')">
      <span class="disclosure" :class="{ open }" aria-hidden="true"></span>
      <span class="note-id">[{{ concept.id }}]</span>
      <strong>{{ concept.title }}</strong>
      <span class="concept-scope" :class="{ methodology: !concept.repository }">{{ scopeLabel }}</span>
      <span class="concept-state" :class="`state-${concept.state}`">
        {{ CONCEPT_STATE_LABEL[concept.state] }}
      </span>
    </button>

    <div v-if="open" class="concept-body">
      <form v-if="editing" class="concept-edit" @submit.prevent="confirmEdit">
        <label>
          <span>一句话标题(60 字内)</span>
          <input v-model="editDraft.title" type="text" maxlength="60" required />
        </label>
        <label>
          <span>为什么选它、替代方案为何不用(400 字内)</span>
          <textarea v-model="editDraft.body" rows="4" maxlength="400"></textarea>
        </label>
        <label v-if="concept.state === 'aligned'" class="concept-edit-keep">
          <input v-model="editDraft.keepAligned" type="checkbox" />
          <span>只是改说法、意思没变,保留已对齐</span>
        </label>
        <div class="concept-actions">
          <button type="button" class="secondary-button" @click="cancelForms">取消</button>
          <button type="submit" class="primary-button" :disabled="!editChanged || busy">保存</button>
        </div>
      </form>

      <template v-else>
        <MarkdownBlock v-if="concept.body" :text="concept.body" />
        <ul v-if="concept.files.length" class="concept-anchors" aria-label="代码锚点">
          <li v-for="anchor in concept.files" :key="`${anchor.path}:${anchor.symbol}`">
            <code :class="{ moved: concept.moved.includes(anchorLabel(anchor)) }">
              {{ anchorLabel(anchor) }}
            </code>
          </li>
        </ul>
        <p v-if="concept.state === 'stale'" class="concept-hint stale">
          对齐于 <code>{{ concept.aligned_commit }}</code>,之后
          {{ concept.moved.join("、") || "锚点" }} 变过——只需重看这处。
        </p>
        <p v-else-if="concept.state === 'aligned'" class="concept-hint">
          已对齐 {{ formatTime(concept.aligned_at) }}
          <template v-if="concept.aligned_commit">· 锚在 <code>{{ concept.aligned_commit }}</code></template>
        </p>
        <p v-else-if="concept.state === 'rejected'" class="concept-hint">
          已否决 {{ formatTime(concept.rejected_at) }}
        </p>

        <div class="concept-meta">
          <button
            v-if="concept.task_ref !== null && concept.task_project === projectKey"
            type="button"
            class="concept-task-link"
            @click="emit('focusTask', concept.task_ref)"
          >
            由 #{{ concept.task_ref }} 引入
          </button>
          <span v-else-if="concept.task_ref !== null">
            由 {{ concept.task_project }} #{{ concept.task_ref }} 引入
          </span>
          <span v-if="concept.project !== projectKey">出处 {{ concept.project }}</span>
          <span v-if="concept.category">{{ concept.category }}</span>
        </div>

        <div v-if="rejecting" class="concept-reject">
          <label>
            <span>否决理由:不算新概念,还是方案本身不对</span>
            <input
              v-model="rejectReason"
              type="text"
              maxlength="200"
              @keydown.enter.prevent="confirmReject"
            />
          </label>
          <div class="concept-actions">
            <button type="button" class="secondary-button" @click="cancelForms">取消</button>
            <button
              type="button"
              class="danger-button"
              :disabled="!rejectReason.trim() || busy"
              @click="confirmReject"
            >确认否决</button>
          </div>
        </div>
        <div v-else-if="concept.state !== 'rejected'" class="concept-actions">
          <button
            v-if="pending"
            type="button"
            class="primary-button"
            :disabled="busy"
            @click="align"
          >{{ concept.state === "stale" ? "重新对齐" : "对齐" }}</button>
          <button type="button" class="secondary-button" :disabled="busy" @click="startEdit">改措辞</button>
          <button type="button" class="secondary-button quiet" :disabled="busy" @click="startReject">否决</button>
        </div>
      </template>
    </div>
  </article>
</template>
