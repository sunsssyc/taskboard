<script setup lang="ts">
import { computed } from "vue";
import { boardReferenceParts, type BoardReference } from "../references";

const props = withDefaults(defineProps<{
  text: string;
  taskRefs?: number[];
  noteRefs?: number[];
}>(), {
  taskRefs: () => [],
  noteRefs: () => [],
});

defineEmits<{ activate: [reference: BoardReference] }>();

const parts = computed(() => boardReferenceParts(props.text));
const availableTasks = computed(() => new Set(props.taskRefs));
const availableNotes = computed(() => new Set(props.noteRefs));

function isAvailable(reference: BoardReference): boolean {
  return reference.kind === "task"
    ? availableTasks.value.has(reference.id)
    : availableNotes.value.has(reference.id);
}
</script>

<template>
  <template v-for="(part, index) in parts" :key="index">
    <button
      v-if="part.kind === 'reference' && isAvailable(part.reference)"
      type="button"
      class="reference-link"
      :aria-label="part.reference.kind === 'task'
        ? `跳转到任务 ${part.text}`
        : `跳转到记录 ${part.text}`"
      @click="$emit('activate', part.reference)"
    >{{ part.text }}</button>
    <template v-else>{{ part.text }}</template>
  </template>
</template>
