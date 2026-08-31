<script setup lang="ts">
import { computed } from "vue";
import ReferenceText from "./ReferenceText.vue";
import type { BoardReference } from "../references";

type InlinePart = { kind: "text" | "strong" | "code"; text: string };
type Block = {
  kind: "blank" | "heading" | "bullet" | "number" | "quote" | "paragraph";
  marker?: string;
  parts: InlinePart[];
};

const props = withDefaults(defineProps<{
  text: string;
  taskRefs?: number[];
  noteRefs?: number[];
}>(), {
  taskRefs: () => [],
  noteRefs: () => [],
});

defineEmits<{ reference: [reference: BoardReference] }>();

function inlineParts(value: string): InlinePart[] {
  const parts: InlinePart[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let cursor = 0;
  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push({ kind: "text", text: value.slice(cursor, index) });
    const token = match[0];
    if (token.startsWith("`")) {
      parts.push({ kind: "code", text: token.slice(1, -1) });
    } else {
      parts.push({ kind: "strong", text: token.slice(2, -2) });
    }
    cursor = index + token.length;
  }
  if (cursor < value.length) parts.push({ kind: "text", text: value.slice(cursor) });
  return parts.length ? parts : [{ kind: "text", text: value }];
}

function parseLine(line: string): Block {
  if (!line.trim()) return { kind: "blank", parts: [] };
  const heading = line.match(/^#{1,4}\s+(.+)$/);
  if (heading) return { kind: "heading", parts: inlineParts(heading[1]) };
  const bullet = line.match(/^\s*[-*]\s+(.+)$/);
  if (bullet) return { kind: "bullet", marker: "•", parts: inlineParts(bullet[1]) };
  const number = line.match(/^\s*(\d+[.)])\s+(.+)$/);
  if (number) return { kind: "number", marker: number[1], parts: inlineParts(number[2]) };
  const quote = line.match(/^>\s?(.+)$/);
  if (quote) return { kind: "quote", parts: inlineParts(quote[1]) };
  return { kind: "paragraph", parts: inlineParts(line) };
}

const blocks = computed(() => props.text.split("\n").map(parseLine));
</script>

<template>
  <div class="markdown-block">
    <template v-for="(block, index) in blocks" :key="index">
      <div v-if="block.kind === 'blank'" class="markdown-gap" aria-hidden="true"></div>
      <div v-else class="markdown-line" :class="`is-${block.kind}`">
        <span v-if="block.marker" class="markdown-marker">{{ block.marker }}</span>
        <span>
          <template v-for="(part, partIndex) in block.parts" :key="partIndex">
            <strong v-if="part.kind === 'strong'">
              <ReferenceText
                :text="part.text"
                :task-refs="taskRefs"
                :note-refs="noteRefs"
                @activate="$emit('reference', $event)"
              />
            </strong>
            <code v-else-if="part.kind === 'code'">{{ part.text }}</code>
            <ReferenceText
              v-else
              :text="part.text"
              :task-refs="taskRefs"
              :note-refs="noteRefs"
              @activate="$emit('reference', $event)"
            />
          </template>
        </span>
      </div>
    </template>
  </div>
</template>
