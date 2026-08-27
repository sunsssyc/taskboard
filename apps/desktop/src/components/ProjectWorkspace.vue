<script setup lang="ts">
import NoteGroups from "./NoteGroups.vue";
import TaskGroups from "./TaskGroups.vue";
import type { BoardNote, BoardProject, BoardTask } from "../types";

defineProps<{
  project: BoardProject;
  tasks: BoardTask[];
  findings: BoardNote[];
  risks: BoardNote[];
  links: BoardNote[];
  query: string;
  singleProject: boolean;
}>();

defineEmits<{ showAll: [] }>();
</script>

<template>
  <section class="project-workspace" :data-project="project.key">
    <div v-if="singleProject" class="filter-context">
      <span>只看 <code>{{ project.key }}</code></span>
      <button type="button" @click="$emit('showAll')">显示全部需求</button>
    </div>

    <header class="project-heading">
      <div class="project-heading-line">
        <h2>{{ project.name }}</h2>
        <code class="project-heading-key">{{ project.key }}</code>
        <span
          v-for="repository in project.repositories"
          v-show="repository.name !== project.key"
          :key="repository.name"
          class="repository-chip"
        >
          {{ repository.name }}
        </span>
      </div>
      <p>{{ project.summary || "持续保存目标、进度、结论和下一步。" }}</p>
    </header>

    <TaskGroups :tasks="tasks" :project-key="project.key" :query="query" />

    <NoteGroups
      :key="`${project.key}:notes`"
      :project-key="project.key"
      :findings="findings"
      :risks="risks"
      :links="links"
      :query="query"
    />
  </section>
</template>
