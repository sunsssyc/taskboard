import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { loadBoardSnapshot } from "../board";
import type {
  BoardNote,
  BoardProject,
  BoardSnapshot,
  BoardTask,
  TaskStatus,
} from "../types";

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

export function projectMatches(project: BoardProject, query: string): boolean {
  const needle = normalized(query).trim();
  if (!needle) return false;
  return [
    project.key,
    project.name,
    project.summary,
    ...project.repositories.map((repository) => repository.name),
  ].some((value) => normalized(value).includes(needle));
}

export const useBoardStore = defineStore("board", () => {
  const snapshot = ref<BoardSnapshot | null>(null);
  const selectedProjectKey = ref("");
  const query = ref("");
  const statusFilter = ref<"" | TaskStatus>("");
  const ownerFilter = ref("");
  const source = ref("");
  const loading = ref(false);
  const error = ref("");

  const projects = computed(() => snapshot.value?.projects ?? []);
  const selectedProject = computed<BoardProject | null>(() => {
    if (!selectedProjectKey.value) return null;
    return projects.value.find((project) => project.key === selectedProjectKey.value) ?? null;
  });
  const visibleProjects = computed(() =>
    selectedProject.value ? [selectedProject.value] : projects.value,
  );
  const owners = computed(() => {
    const values = new Set<string>();
    for (const project of projects.value) {
      for (const task of project.tasks) {
        if (task.owner) values.add(task.owner);
      }
    }
    return [...values].sort((left, right) => left.localeCompare(right, "zh-CN"));
  });

  function filteredTasks(project: BoardProject): BoardTask[] {
    const wholeProjectMatches = projectMatches(project, query.value);
    return project.tasks.filter((task) => {
      if (statusFilter.value && task.status !== statusFilter.value) return false;
      if (ownerFilter.value && task.owner !== ownerFilter.value) return false;
      return wholeProjectMatches || taskMatches(task, query.value);
    });
  }

  function filteredNotes(project: BoardProject, notes: BoardNote[]): BoardNote[] {
    if (statusFilter.value || ownerFilter.value) return [];
    if (projectMatches(project, query.value)) return notes;
    return notes.filter((note) => noteMatches(note, query.value));
  }

  function filteredFindings(project: BoardProject): BoardNote[] {
    return filteredNotes(project, project.findings);
  }

  function filteredRisks(project: BoardProject): BoardNote[] {
    return filteredNotes(project, project.risks);
  }

  function filteredLinks(project: BoardProject): BoardNote[] {
    return filteredNotes(project, project.links);
  }

  function projectHasMatches(project: BoardProject): boolean {
    if (!query.value && !statusFilter.value && !ownerFilter.value) return true;
    return (
      filteredTasks(project).length > 0 ||
      filteredFindings(project).length > 0 ||
      filteredRisks(project).length > 0 ||
      filteredLinks(project).length > 0
    );
  }

  const displayProjects = computed(() => visibleProjects.value.filter(projectHasMatches));
  const matchingTasks = computed(() =>
    selectedProject.value ? filteredTasks(selectedProject.value) : [],
  );
  const matchingFindings = computed(() =>
    selectedProject.value ? filteredFindings(selectedProject.value) : [],
  );
  const matchingRisks = computed(() =>
    selectedProject.value ? filteredRisks(selectedProject.value) : [],
  );
  const matchingLinks = computed(() =>
    selectedProject.value ? filteredLinks(selectedProject.value) : [],
  );

  function selectProject(key: string) {
    selectedProjectKey.value = key;
  }

  function selectAllProjects() {
    selectedProjectKey.value = "";
  }

  async function load() {
    loading.value = true;
    error.value = "";
    try {
      const response = await loadBoardSnapshot();
      snapshot.value = response.snapshot;
      source.value = response.source;
      if (
        selectedProjectKey.value &&
        !response.snapshot.projects.some((project) => project.key === selectedProjectKey.value)
      ) {
        selectedProjectKey.value = "";
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
    statusFilter,
    ownerFilter,
    source,
    loading,
    error,
    projects,
    visibleProjects,
    displayProjects,
    selectedProject,
    owners,
    matchingTasks,
    matchingFindings,
    matchingRisks,
    matchingLinks,
    filteredTasks,
    filteredFindings,
    filteredRisks,
    filteredLinks,
    projectHasMatches,
    selectProject,
    selectAllProjects,
    load,
  };
});
