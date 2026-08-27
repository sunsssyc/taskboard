import { computed, ref } from "vue";
import { defineStore } from "pinia";
import {
  dispatchTaskAgent,
  loadBoardSnapshot,
  saveBoardViewPrefs,
  saveTaskOwner,
  saveTaskPriority,
  saveTaskStatus,
} from "../board";
import type {
  AgentProvider,
  BoardNote,
  BoardProject,
  BoardSnapshot,
  BoardTask,
  TaskOwner,
  TaskPriority,
  TaskStatus,
  ViewPrefs,
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
    `P${task.priority}`,
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

export function sortProjectsByPrefs(
  projects: BoardProject[],
  prefs: ViewPrefs,
): BoardProject[] {
  const rank = new Map(prefs.order.map((key, index) => [key, index]));
  const pinned = new Set(prefs.pinned);
  const fallback = prefs.order.length;
  return projects
    .map((project, index) => ({ project, index }))
    .sort((left, right) => {
      const leftPinned = pinned.has(left.project.key);
      const rightPinned = pinned.has(right.project.key);
      if (leftPinned !== rightPinned) return leftPinned ? -1 : 1;
      const leftRank = rank.get(left.project.key) ?? fallback + left.index;
      const rightRank = rank.get(right.project.key) ?? fallback + right.index;
      return leftRank - rightRank;
    })
    .map(({ project }) => project);
}

export function moveProjectOrder(
  keys: string[],
  draggedKey: string,
  targetKey: string,
  before: boolean,
): string[] {
  if (draggedKey === targetKey || !keys.includes(draggedKey) || !keys.includes(targetKey)) {
    return [...keys];
  }
  const next = keys.filter((key) => key !== draggedKey);
  const targetIndex = next.indexOf(targetKey);
  next.splice(before ? targetIndex : targetIndex + 1, 0, draggedKey);
  return next;
}

export const useBoardStore = defineStore("board", () => {
  const snapshot = ref<BoardSnapshot | null>(null);
  const selectedProjectKey = ref("");
  const query = ref("");
  const statusFilter = ref<"" | TaskStatus>("");
  const ownerFilter = ref("");
  const viewPrefs = ref<ViewPrefs>({ order: [], pinned: [] });
  const preferenceError = ref("");
  const actionError = ref("");
  const actionNotice = ref("");
  const dispatchingTask = ref("");
  const source = ref("");
  const loading = ref(false);
  const error = ref("");

  const projects = computed(() => snapshot.value?.projects ?? []);
  const orderedProjects = computed(() => sortProjectsByPrefs(projects.value, viewPrefs.value));
  const selectedProject = computed<BoardProject | null>(() => {
    if (!selectedProjectKey.value) return null;
    return projects.value.find((project) => project.key === selectedProjectKey.value) ?? null;
  });
  const visibleProjects = computed(() =>
    selectedProject.value ? [selectedProject.value] : orderedProjects.value,
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

  let preferenceRevision = 0;
  let preferenceQueue = Promise.resolve();
  let pendingPreferenceSaves = 0;

  function persistViewPrefs() {
    const revision = ++preferenceRevision;
    const pending: ViewPrefs = {
      order: [...viewPrefs.value.order],
      pinned: [...viewPrefs.value.pinned],
    };
    preferenceError.value = "";
    pendingPreferenceSaves += 1;
    preferenceQueue = preferenceQueue
      .then(async () => {
        const saved = await saveBoardViewPrefs(pending);
        if (revision === preferenceRevision) viewPrefs.value = saved;
      })
      .catch((reason: unknown) => {
        if (revision === preferenceRevision) {
          preferenceError.value = reason instanceof Error ? reason.message : String(reason);
        }
      })
      .finally(() => {
        pendingPreferenceSaves -= 1;
      });
  }

  function togglePinned(key: string) {
    const pinned = [...viewPrefs.value.pinned];
    const index = pinned.indexOf(key);
    if (index === -1) pinned.push(key);
    else pinned.splice(index, 1);
    viewPrefs.value = {
      order: orderedProjects.value.map((project) => project.key),
      pinned,
    };
    persistViewPrefs();
  }

  function reorderProject(draggedKey: string, targetKey: string, before: boolean) {
    viewPrefs.value = {
      order: moveProjectOrder(
        orderedProjects.value.map((project) => project.key),
        draggedKey,
        targetKey,
        before,
      ),
      pinned: [...viewPrefs.value.pinned],
    };
    persistViewPrefs();
  }

  async function setTaskStatus(projectKey: string, reference: number, status: TaskStatus) {
    actionError.value = "";
    try {
      await saveTaskStatus(projectKey, reference, status);
      await load();
    } catch (reason) {
      actionError.value = reason instanceof Error ? reason.message : String(reason);
    }
  }

  async function setTaskOwner(projectKey: string, reference: number, owner: TaskOwner) {
    actionError.value = "";
    try {
      await saveTaskOwner(projectKey, reference, owner);
      await load();
    } catch (reason) {
      actionError.value = reason instanceof Error ? reason.message : String(reason);
    }
  }

  async function setTaskPriority(
    projectKey: string,
    reference: number,
    priority: TaskPriority,
  ) {
    actionError.value = "";
    try {
      await saveTaskPriority(projectKey, reference, priority);
      await load();
    } catch (reason) {
      actionError.value = reason instanceof Error ? reason.message : String(reason);
    }
  }

  async function dispatchTask(
    projectKey: string,
    task: BoardTask,
    provider: AgentProvider,
    repositoryPath: string,
  ) {
    const key = `${projectKey}:${task.ref}`;
    actionError.value = "";
    actionNotice.value = "";
    dispatchingTask.value = key;
    try {
      const result = await dispatchTaskAgent({
        provider,
        project: projectKey,
        reference: task.ref,
        title: task.title,
        detail: task.detail,
        accept: task.accept,
        repositoryPath,
      });
      if (result.warning?.startsWith("网页演示")) {
        const providerLabel = provider === "claude" ? "Claude" : "Codex";
        actionNotice.value = `网页演示：已模拟将 #${task.ref} 派发给 ${providerLabel}，未实际启动桌面 Agent。`;
      } else if (provider === "claude") {
        actionNotice.value = `Claude 已打开 #${task.ref}；请确认工作目录后发送预填任务。`;
      } else {
        const suffix = result.externalThreadId ? `（线程 ${result.externalThreadId.slice(0, 8)}…）` : "";
        actionNotice.value = `Codex 已接收 #${task.ref}${suffix}。`;
      }
      if (result.warning && !result.warning.startsWith("网页演示")) {
        actionNotice.value += ` ${result.warning}`;
      }
      await load();
    } catch (reason) {
      actionError.value = reason instanceof Error ? reason.message : String(reason);
    } finally {
      if (dispatchingTask.value === key) dispatchingTask.value = "";
    }
  }

  async function load() {
    loading.value = true;
    error.value = "";
    try {
      const response = await loadBoardSnapshot();
      snapshot.value = response.snapshot;
      source.value = response.source;
      // 保存在途时磁盘上的偏好可能落后于界面,不回灌以免刷新打回刚拖好的顺序。
      if (pendingPreferenceSaves === 0) viewPrefs.value = response.viewPrefs;
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
    viewPrefs,
    preferenceError,
    actionError,
    actionNotice,
    dispatchingTask,
    source,
    loading,
    error,
    projects,
    orderedProjects,
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
    togglePinned,
    reorderProject,
    setTaskOwner,
    setTaskPriority,
    setTaskStatus,
    dispatchTask,
    load,
  };
});
