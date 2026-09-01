<script setup lang="ts">
import { computed } from "vue";
import ReferenceText from "./ReferenceText.vue";
import type { BoardReference } from "../references";
import { parseMarkdownBlocks } from "../markdown";

const props = withDefaults(defineProps<{
  text: string;
  taskRefs?: number[];
  noteRefs?: number[];
}>(), {
  taskRefs: () => [],
  noteRefs: () => [],
});

defineEmits<{ reference: [reference: BoardReference] }>();
const blocks = computed(() => parseMarkdownBlocks(props.text));
</script>

<template>
  <div class="markdown-block">
    <template v-for="(block, index) in blocks" :key="index">
      <div v-if="block.kind === 'blank'" class="markdown-gap" aria-hidden="true"></div>
      <div v-else-if="block.kind === 'table'" class="markdown-table-scroll">
        <table class="markdown-table">
          <thead>
            <tr>
              <th
                v-for="(cell, cellIndex) in block.header"
                :key="cellIndex"
                scope="col"
                :class="`is-${block.alignments[cellIndex]}`"
              >
                <template v-for="(part, partIndex) in cell" :key="partIndex">
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
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
              <td
                v-for="(cell, cellIndex) in row"
                :key="cellIndex"
                :class="`is-${block.alignments[cellIndex]}`"
              >
                <template v-for="(part, partIndex) in cell" :key="partIndex">
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
              </td>
            </tr>
          </tbody>
        </table>
      </div>
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
