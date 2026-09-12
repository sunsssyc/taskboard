import { computed, ref } from "vue";
import { acceptHMRUpdate, defineStore } from "pinia";
import {
  alignConcept as alignConceptRemote,
  dispatchTaskAgent,
  loadBoardSnapshot,
  rejectConcept as rejectConceptRemote,
  saveBoardViewPrefs,
  saveProjectArchived,
  saveTaskOwner,
  saveTaskPriority,
  saveTaskStatus,
  updateConcept as updateConceptRemote,
} from "../board";
import type {
  AgentProvider,
  BoardConcept,
  BoardNote,
  BoardProject,
  BoardSnapshot,
  BoardTask,
  ConceptEdit,
  TaskOwner,
  TaskPriority,
  TaskStatus,
  ViewPrefs,
} from "../types";

function normalized(value: string | null | undefined): string {
  return (value ?? "").toLocaleLowerCase();
}

export type BoardSearchQuery =
  | { kind: "text"; needle: string }
  | { kind: "task-id"; id: number }
  | { kind: "note-id"; id: number }
  | { kind: "any-id"; id: number; needle: string };

export function parseSearchQuery(query: string): BoardSearchQuery {
  const trimmed = query.trim();
  const taskId = trimmed.match(/^#(\d+)$/);
  if (taskId) return { kind: "task-id", id: Number(taskId[1]) };

  const noteId = trimmed.match(/^\[(\d+)\]$/);
  if (noteId) return { kind: "note-id", id: Number(noteId[1]) };

  if (/^\d+$/.test(trimmed)) {
    return { kind: "any-id", id: Number(trimmed), needle: normalized(trimmed) };
  }
  return { kind: "text", needle: normalized(trimmed) };
}

function asSearchQuery(query: string | BoardSearchQuery): BoardSearchQuery {
  return typeof query === "string" ? parseSearchQuery(query) : query;
}

export function resolveSearchQuery(
  query: string,
  _projects: BoardProject[],
): BoardSearchQuery {
  const parsed = parseSearchQuery(query);
  return parsed;
}

export function taskMatches(task: BoardTask, query: string | BoardSearchQuery): boolean {
  const parsed = asSearchQuery(query);
  if (parsed.kind === "task-id") return task.ref === parsed.id;
  if (parsed.kind === "note-id") return false;

  if (parsed.kind === "any-id" && task.ref === parsed.id) return true;

  const { needle } = parsed;
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

export function noteMatches(note: BoardNote, query: string | BoardSearchQuery): boolean {
  const parsed = asSearchQuery(query);
  if (parsed.kind === "note-id") return note.id === parsed.id;
  if (parsed.kind === "task-id") return false;

  if (parsed.kind === "any-id" && note.id === parsed.id) return true;

  const { needle } = parsed;
  if (!needle) return true;
  return [note.title, note.body, note.metric, note.category].some((value) =>
    normalized(value).includes(needle),
  );
}

export function conceptMatches(concept: BoardConcept, query: string | BoardSearchQuery): boolean {
  const parsed = asSearchQuery(query);
  if (parsed.kind !== "text") return true;

  const { needle } = parsed;
  if (!needle) return true;
  return [
    concept.title,
    concept.body,
    concept.category,
    concept.repository,
    `[${concept.id}]`,
    ...concept.files.map((anchor) => `${anchor.path}:${anchor.symbol}`),
  ].some((value) => normalized(value).includes(needle));
}

export function projectMatches(project: BoardProject, query: string | BoardSearchQuery): boolean {
  const parsed = asSearchQuery(query);
  if (parsed.kind !== "text") return false;

  const { needle } = parsed;
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
  const conceptBusy = ref<number | null>(null);
  const writeEnabled = ref(true);
  const source = ref("");
  const loading = ref(false);
  const error = ref("");
  let projectNoticeTimer: ReturnType<typeof setTimeout> | undefined;

  const allProjects = computed(() => snapshot.value?.projects ?? []);
  const effectiveSearchQuery = computed(() => resolveSearchQuery(query.value, allProjects.value));
  const projects = computed(() => allProjects.value.filter((project) => !project.archived));
  const archivedProjects = computed(() =>
    allProjects.value.filter((project) => project.archived),
  );
  const orderedProjects = computed(() => sortProjectsByPrefs(projects.value, viewPrefs.value));
  const pinnedProjects = computed(() => {
    const pinned = new Set(viewPrefs.value.pinned);
    return orderedProjects.value.filter((project) => pinned.has(project.key));
  });
  const regularProjects = computed(() => {
    const pinned = new Set(viewPrefs.value.pinned);
    return orderedProjects.value.filter((project) => !pinned.has(project.key));
  });
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
    const wholeProjectMatches = projectMatches(project, effectiveSearchQuery.value);
    const matches = project.tasks.filter((task) => {
      if (statusFilter.value && task.status !== statusFilter.value) return false;
      if (ownerFilter.value && task.owner !== ownerFilter.value) return false;
      return wholeProjectMatches || taskMatches(task, effectiveSearchQuery.value);
    });
    if (effectiveSearchQuery.value.kind === "any-id") {
      const { id } = effectiveSearchQuery.value;
      matches.sort((left, right) => Number(right.ref === id) - Number(left.ref === id));
    }
    return matches;
  }

  function filteredNotes(project: BoardProject, notes: BoardNote[]): BoardNote[] {
    if (statusFilter.value || ownerFilter.value) return [];
    if (projectMatches(project, effectiveSearchQuery.value)) return notes;
    const matches = notes.filter((note) => noteMatches(note, effectiveSearchQuery.value));
    if (effectiveSearchQuery.value.kind === "any-id") {
      const { id } = effectiveSearchQuery.value;
      matches.sort((left, right) => Number(right.id === id) - Number(left.id === id));
    }
    return matches;
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

  function filteredConcepts(project: BoardProject): BoardConcept[] {
    if (statusFilter.value || ownerFilter.value) return [];
    if (projectMatches(project, query.value)) return project.concepts;
    return project.concepts.filter((concept) => conceptMatches(concept, query.value));
  }

  function projectHasMatches(project: BoardProject): boolean {
    if (!query.value && !statusFilter.value && !ownerFilter.value) return true;
    return (
      filteredTasks(project).length > 0 ||
      filteredFindings(project).length > 0 ||
      filteredRisks(project).length > 0 ||
      filteredLinks(project).length > 0 ||
      filteredConcepts(project).length > 0
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
  const matchingConcepts = computed(() =>
    selectedProject.value ? filteredConcepts(selectedProject.value) : [],
  );
  /** 待人确认的概念数:待对齐 + 需重新对齐,跨需求去重(同仓库概念会在多个需求里出现)。 */
  const pendingConceptCount = computed(() => {
    const ids = new Set<number>();
    for (const project of projects.value) {
      for (const concept of project.concepts) {
        if (concept.state === "proposed" || concept.state === "stale") ids.add(concept.id);
      }
    }
    return ids.size;
  });

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

  function clearProjectNoticeTimer() {
    if (projectNoticeTimer !== undefined) clearTimeout(projectNoticeTimer);
    projectNoticeTimer = undefined;
  }

  function showProjectNotice(message: string) {
    clearProjectNoticeTimer();
    actionNotice.value = message;
    projectNoticeTimer = setTimeout(() => {
      if (actionNotice.value === message) actionNotice.value = "";
      projectNoticeTimer = undefined;
    }, 1400);
  }

  async function setProjectArchived(projectKey: string, archived: boolean) {
    actionError.value = "";
    clearProjectNoticeTimer();
    actionNotice.value = "";
    const project = projects.value.find((item) => item.key === projectKey);
    const unfinishedCount = project
      ? project.counts.todo + project.counts.active + project.counts.waiting
      : 0;
    try {
      await saveProjectArchived(projectKey, archived);
      if (archived && selectedProjectKey.value === projectKey) {
        selectedProjectKey.value = "";
      }
      await load();
      showProjectNotice(
        archived
          ? unfinishedCount > 0
            ? `需求已完成，仍有 ${unfinishedCount} 项未完成任务；可在“已完成需求”中恢复。`
            : "需求已移入“已完成需求”，可在左侧恢复。"
          : "需求已恢复到左侧工作列表。",
      );
    } catch (reason) {
      actionError.value = reason instanceof Error ? reason.message : String(reason);
    }
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
    clearProjectNoticeTimer();
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

  async function runConceptAction(
    id: number,
    action: () => Promise<BoardConcept>,
    notice: (concept: BoardConcept) => string,
  ): Promise<boolean> {
    actionError.value = "";
    clearProjectNoticeTimer();
    actionNotice.value = "";
    conceptBusy.value = id;
    try {
      const concept = await action();
      await load();
      showProjectNotice(notice(concept));
      return true;
    } catch (reason) {
      actionError.value = reason instanceof Error ? reason.message : String(reason);
      return false;
    } finally {
      if (conceptBusy.value === id) conceptBusy.value = null;
    }
  }

  function alignConcept(id: number, note?: string) {
    return runConceptAction(id, () => alignConceptRemote(id, note), (concept) =>
      concept.aligned_commit
        ? `已对齐 [${concept.id}],锚在 ${concept.aligned_commit};之后锚点文件动过会提示重新对齐。`
        : `已对齐 [${concept.id}]。`,
    );
  }

  function rejectConcept(id: number, reason: string) {
    return runConceptAction(id, () => rejectConceptRemote(id, reason), (concept) =>
      `已否决 [${concept.id}] ${concept.title}。`,
    );
  }

  function editConcept(id: number, edit: ConceptEdit) {
    return runConceptAction(id, () => updateConceptRemote(id, edit), (concept) =>
      (concept as BoardConcept & { alignment_reset?: boolean }).alignment_reset
        ? `[${concept.id}] 措辞变了,已退回待对齐——当初点头认的是旧那句话。`
        : `[${concept.id}] 已更新。`,
    );
  }

  async function load() {
    loading.value = true;
    error.value = "";
    try {
      const response = await loadBoardSnapshot();
      snapshot.value = response.snapshot;
      source.value = response.source;
      writeEnabled.value = response.writeEnabled ?? true;
      // 保存在途时磁盘上的偏好可能落后于界面,不回灌以免刷新打回刚拖好的顺序。
      if (pendingPreferenceSaves === 0) viewPrefs.value = response.viewPrefs;
      if (
        selectedProjectKey.value &&
        !response.snapshot.projects.some(
          (project) => project.key === selectedProjectKey.value && !project.archived,
        )
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
    conceptBusy,
    writeEnabled,
    source,
    loading,
    error,
    projects,
    archivedProjects,
    orderedProjects,
    pinnedProjects,
    regularProjects,
    visibleProjects,
    displayProjects,
    selectedProject,
    owners,
    matchingTasks,
    matchingFindings,
    matchingRisks,
    matchingLinks,
    matchingConcepts,
    pendingConceptCount,
    filteredTasks,
    filteredFindings,
    filteredRisks,
    filteredLinks,
    filteredConcepts,
    projectHasMatches,
    selectProject,
    selectAllProjects,
    togglePinned,
    reorderProject,
    setProjectArchived,
    setTaskOwner,
    setTaskPriority,
    setTaskStatus,
    dispatchTask,
    alignConcept,
    rejectConcept,
    editConcept,
    load,
  };
});

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useBoardStore, import.meta.hot));
}
