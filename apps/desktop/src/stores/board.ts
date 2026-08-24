import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { loadBoardSnapshot } from "../board";
import type { BoardNote, BoardProject, BoardSnapshot, BoardTask } from "../types";

function normalized(value: string | null | undefined): string {
  return (value ?? "").toLocaleLowerCase();
}

export function taskMatches(task: BoardTask, query: string): boolean {
  const needle = normalized(query).trim();
  if (!needle) return true;
  return [
    task.title,
    task.detail,
    task.accept,
    task.owner,
    task.branch,
    task.pr,
    ...task.repositories.map((repository) => repository.name),
  ].some((value) => normalized(value).includes(needle));
}

export function noteMatches(note: BoardNote, query: string): boolean {
  const needle = normalized(query).trim();
  if (!needle) return true;
  return [note.title, note.body, note.metric, note.category].some((value) =>
    normalized(value).includes(needle),
  );
}

export const useBoardStore = defineStore("board", () => {
  const snapshot = ref<BoardSnapshot | null>(null);
  const selectedProjectKey = ref("");
  const query = ref("");
  const source = ref("");
  const loading = ref(false);
  const error = ref("");

  const projects = computed(() => snapshot.value?.projects ?? []);
  const selectedProject = computed<BoardProject | null>(() => {
    return (
      projects.value.find((project) => project.key === selectedProjectKey.value) ??
      projects.value[0] ??
      null
    );
  });
  const matchingTasks = computed(() =>
    (selectedProject.value?.tasks ?? []).filter((task) => taskMatches(task, query.value)),
  );
  const matchingFindings = computed(() =>
    (selectedProject.value?.findings ?? []).filter((note) => noteMatches(note, query.value)),
  );
  const matchingRisks = computed(() =>
    (selectedProject.value?.risks ?? []).filter((note) => noteMatches(note, query.value)),
  );
  const matchingLinks = computed(() =>
    (selectedProject.value?.links ?? []).filter((note) => noteMatches(note, query.value)),
  );

  function selectProject(key: string) {
    selectedProjectKey.value = key;
    query.value = "";
  }

  async function load() {
    loading.value = true;
    error.value = "";
    try {
      const response = await loadBoardSnapshot();
      snapshot.value = response.snapshot;
      source.value = response.source;
      if (!response.snapshot.projects.some((project) => project.key === selectedProjectKey.value)) {
        selectedProjectKey.value = response.snapshot.projects[0]?.key ?? "";
      }
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : String(reason);
    } finally {
      loading.value = false;
    }
  }

  return {
    snapshot,
    selectedProjectKey,
    query,
    source,
    loading,
    error,
    projects,
    selectedProject,
    matchingTasks,
    matchingFindings,
    matchingRisks,
    matchingLinks,
    selectProject,
    load,
  };
});
