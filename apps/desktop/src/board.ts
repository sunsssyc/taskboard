import { invoke } from "@tauri-apps/api/core";
import { demoSnapshot } from "./demo";
import type {
  AgentRun,
  AgentDispatchRequest,
  AgentDispatchResult,
  BoardConcept,
  BoardLoadResponse,
  BoardSnapshot,
  ConceptEdit,
  TaskOwner,
  TaskPriority,
  TaskStatus,
  ViewPrefs,
  WebContext,
} from "./types";

const ORDER_KEY = "taskboard:order";
const PINNED_KEY = "taskboard:pinned";
const browserDemoSnapshot = structuredClone(demoSnapshot);

/**
 * 三种数据后端,同一套界面:
 * - tauri:桌面端,经 Rust command 调 board CLI;
 * - web:board serve 托管的页面,经同源 HTTP API 读写,CSRF token 由页面注入;
 * - demo:浏览器直接打开 vite dev,只有内置演示数据。
 */
export type BoardBackend = "tauri" | "web" | "demo";

export function detectBackend(): BoardBackend {
  if (typeof window === "undefined") return "demo";
  if (window.__TAURI_INTERNALS__) return "tauri";
  if (window.__TASKBOARD_WEB__) return "web";
  return "demo";
}

export function normalizeSnapshot(snapshot: BoardSnapshot): BoardSnapshot {
  for (const project of snapshot.projects) {
    // 旧 CLI 导出的快照可能没有 concepts / priority,补齐后界面不用到处判空
    if (!Array.isArray(project.concepts)) project.concepts = [];
    for (const task of project.tasks) {
      const priority = (task as { priority?: number }).priority;
      if (priority !== 0 && priority !== 1 && priority !== 2 && priority !== 3) {
        task.priority = 2;
      }
    }
  }
  return snapshot;
}

/** 向后兼容旧名字:早期只补优先级。 */
export const normalizeTaskPriorities = normalizeSnapshot;

export function simulateBrowserAgentDispatch(
  snapshot: BoardSnapshot,
  request: AgentDispatchRequest,
  now = new Date(),
): AgentDispatchResult {
  const project = snapshot.projects.find((item) => item.key === request.project);
  const task = project?.tasks.find((item) => item.ref === request.reference);
  if (!task) throw new Error(`网页演示数据中找不到任务 #${request.reference}。`);

  const startedAt = now.toISOString();
  const suffix = `${now.getTime()}-${task.agent_runs.length + 1}`;
  const dispatchId = `demo-${request.provider}-${suffix}`;
  const externalThreadId = request.provider === "codex" ? `demo-thread-${suffix}` : null;
  const externalTurnId = request.provider === "codex" ? `demo-turn-${suffix}` : null;
  const status = request.provider === "codex" ? "submitted" : "opened";
  const run: AgentRun = {
    id: -now.getTime(),
    task_id: 0,
    provider: request.provider,
    dispatch_id: dispatchId,
    repository_path: request.repositoryPath,
    external_thread_id: externalThreadId,
    external_turn_id: externalTurnId,
    status,
    error: null,
    started_at: startedAt,
    updated_at: startedAt,
  };
  task.agent_runs.unshift(run);
  snapshot.generated_at = startedAt;

  return {
    provider: request.provider,
    dispatchId,
    repositoryPath: request.repositoryPath,
    status,
    externalThreadId,
    externalTurnId,
    startedAt,
    warning: "网页演示:未实际启动桌面 Agent。",
  };
}

/** 演示模式下就地改概念状态,让浏览器预览也能走完整交互。 */
export function simulateConceptAction(
  snapshot: BoardSnapshot,
  id: number,
  action: "align" | "reject" | "edit",
  payload: { reason?: string; edit?: ConceptEdit } = {},
  now = new Date(),
): BoardConcept {
  const concept = snapshot.projects
    .flatMap((project) => project.concepts)
    .find((item) => item.id === id);
  if (!concept) throw new Error(`网页演示数据中找不到概念 [${id}]。`);
  const stamp = now.toISOString();
  if (action === "align") {
    if (concept.state === "rejected") throw new Error(`概念 ${id} 已被否决,不能再对齐`);
    concept.state = "aligned";
    concept.aligned_at = stamp;
    concept.aligned_commit = concept.repository ? "demo1234" : null;
    concept.moved = [];
  } else if (action === "reject") {
    if (!payload.reason?.trim()) throw new Error("否决要给理由:是不算新概念,还是方案本身不对");
    concept.state = "rejected";
    concept.rejected_at = stamp;
    concept.aligned_at = null;
    concept.aligned_commit = null;
  } else {
    const edit = payload.edit ?? {};
    const changed = (edit.title !== undefined && edit.title !== concept.title)
      || (edit.body !== undefined && edit.body !== (concept.body ?? ""));
    if (!changed) throw new Error("没有要改的内容");
    if (edit.title !== undefined) concept.title = edit.title;
    if (edit.body !== undefined) concept.body = edit.body || null;
    if (concept.state === "aligned" && !edit.keepAligned) {
      concept.state = "proposed";
      concept.aligned_at = null;
      concept.aligned_commit = null;
    }
  }
  snapshot.generated_at = stamp;
  return structuredClone(concept);
}

function readBrowserList(key: string): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function readBrowserViewPrefs(): ViewPrefs {
  return {
    order: readBrowserList(ORDER_KEY),
    pinned: readBrowserList(PINNED_KEY),
  };
}

// ── board serve 的 HTTP 后端 ────────────────────────────────────────────
function webContext(): WebContext {
  const context = window.__TASKBOARD_WEB__;
  if (!context) throw new Error("页面缺少 board serve 注入的上下文。");
  return context;
}

async function webGet<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store" });
  const value = (await response.json()) as T & { ok?: boolean; error?: string };
  if (!response.ok || value.ok === false) {
    throw new Error(value.error || `请求 ${path} 失败(${response.status})`);
  }
  return value;
}

async function webPost<T>(path: string, body: unknown): Promise<T> {
  const context = webContext();
  if (!context.writeEnabled) throw new Error("当前监听地址只读:board serve 只在本机 loopback 上允许写入。");
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Taskboard-CSRF": context.csrf,
    },
    body: JSON.stringify(body),
  });
  const value = (await response.json().catch(() => ({}))) as T & { ok?: boolean; error?: string };
  if (!response.ok || value.ok === false) {
    throw new Error(value.error || `写入失败(${response.status})`);
  }
  return value;
}

interface WebBoardResponse {
  snapshot: BoardSnapshot;
  viewPrefs: ViewPrefs;
  source: string;
  writeEnabled: boolean;
  version: string;
}

// ── 对外 API:按后端分派 ─────────────────────────────────────────────────
export async function loadBoardSnapshot(): Promise<BoardLoadResponse> {
  const backend = detectBackend();
  if (backend === "demo") {
    return {
      snapshot: normalizeSnapshot(structuredClone(browserDemoSnapshot)),
      source: "浏览器演示数据",
      viewPrefs: readBrowserViewPrefs(),
    };
  }
  if (backend === "web") {
    const response = await webGet<WebBoardResponse>("/api/board");
    return {
      snapshot: normalizeSnapshot(response.snapshot),
      source: response.source,
      viewPrefs: response.viewPrefs,
      writeEnabled: response.writeEnabled,
    };
  }
  const response = await invoke<BoardLoadResponse>("load_board");
  response.snapshot = normalizeSnapshot(response.snapshot);
  return response;
}

export async function saveProjectArchived(project: string, archived: boolean): Promise<void> {
  const backend = detectBackend();
  if (backend === "demo") {
    const target = browserDemoSnapshot.projects.find((item) => item.key === project);
    if (!target) throw new Error(`网页演示数据中找不到需求 ${project}。`);
    target.archived = archived;
    browserDemoSnapshot.generated_at = new Date().toISOString();
    return;
  }
  if (backend === "web") {
    await webPost(`/api/projects/${encodeURIComponent(project)}/archived`, { archived });
    return;
  }
  await invoke("set_project_archived", { project, archived });
}

export async function saveTaskStatus(
  project: string,
  reference: number,
  status: TaskStatus,
): Promise<void> {
  const backend = detectBackend();
  if (backend === "demo") {
    throw new Error("浏览器演示数据不支持修改状态;运行 npm run tauri dev 或 board serve 后操作真实看板。");
  }
  if (backend === "web") {
    await webPost(`/api/tasks/${encodeURIComponent(project)}/${reference}/status`, { status });
    return;
  }
  await invoke("set_task_status", { project, reference, status });
}

export async function saveTaskOwner(
  project: string,
  reference: number,
  owner: TaskOwner,
): Promise<void> {
  const backend = detectBackend();
  if (backend === "demo") {
    throw new Error("浏览器演示数据不支持修改负责人;运行 npm run tauri dev 或 board serve 后操作真实看板。");
  }
  if (backend === "web") {
    await webPost(`/api/tasks/${encodeURIComponent(project)}/${reference}/owner`, { owner });
    return;
  }
  await invoke("set_task_owner", { project, reference, owner });
}

export async function saveTaskPriority(
  project: string,
  reference: number,
  priority: TaskPriority,
): Promise<void> {
  const backend = detectBackend();
  if (backend === "demo") {
    throw new Error("浏览器演示数据不支持修改优先级;运行 npm run tauri dev 或 board serve 后操作真实看板。");
  }
  if (backend === "web") {
    await webPost(`/api/tasks/${encodeURIComponent(project)}/${reference}/priority`, { priority });
    return;
  }
  await invoke("set_task_priority", { project, reference, priority });
}

export async function dispatchTaskAgent(
  request: AgentDispatchRequest,
): Promise<AgentDispatchResult> {
  const backend = detectBackend();
  if (backend === "demo") {
    return simulateBrowserAgentDispatch(browserDemoSnapshot, request);
  }
  if (backend === "web") {
    throw new Error("派发桌面 Agent 只在 Taskboard Desktop 里可用;网页版请用 board CLI 或桌面端。");
  }
  return invoke<AgentDispatchResult>("dispatch_task_agent", { request });
}

export async function saveBoardViewPrefs(prefs: ViewPrefs): Promise<ViewPrefs> {
  const backend = detectBackend();
  if (backend === "demo") {
    localStorage.setItem(ORDER_KEY, JSON.stringify(prefs.order));
    localStorage.setItem(PINNED_KEY, JSON.stringify(prefs.pinned));
    return prefs;
  }
  if (backend === "web") {
    const response = await webPost<{ view: ViewPrefs }>("/api/view", prefs);
    return response.view;
  }
  return invoke<ViewPrefs>("save_view_prefs", { prefs });
}

// ── 概念卡 ─────────────────────────────────────────────────────────────
export async function alignConcept(id: number, note?: string): Promise<BoardConcept> {
  const backend = detectBackend();
  if (backend === "demo") return simulateConceptAction(browserDemoSnapshot, id, "align");
  if (backend === "web") {
    const response = await webPost<{ concept: BoardConcept }>(`/api/concepts/${id}/align`, {
      note: note ?? "",
    });
    return response.concept;
  }
  return invoke<BoardConcept>("align_concept", { id, note: note ?? null });
}

export async function rejectConcept(id: number, reason: string): Promise<BoardConcept> {
  const backend = detectBackend();
  if (backend === "demo") {
    return simulateConceptAction(browserDemoSnapshot, id, "reject", { reason });
  }
  if (backend === "web") {
    const response = await webPost<{ concept: BoardConcept }>(`/api/concepts/${id}/reject`, {
      reason,
    });
    return response.concept;
  }
  return invoke<BoardConcept>("reject_concept", { id, reason });
}

export async function updateConcept(id: number, edit: ConceptEdit): Promise<BoardConcept> {
  const backend = detectBackend();
  if (backend === "demo") {
    return simulateConceptAction(browserDemoSnapshot, id, "edit", { edit });
  }
  if (backend === "web") {
    const response = await webPost<{ concept: BoardConcept }>(`/api/concepts/${id}`, {
      title: edit.title ?? "",
      body: edit.body ?? "",
      keep_aligned: Boolean(edit.keepAligned),
    });
    return response.concept;
  }
  return invoke<BoardConcept>("update_concept", {
    id,
    title: edit.title ?? null,
    body: edit.body ?? null,
    keepAligned: Boolean(edit.keepAligned),
  });
}

// ── 变更订阅:只有 board serve 需要轮询,CLI 一改 2 秒内刷新 ──────────────
export const CHANGE_POLL_INTERVAL_MS = 2_000;

export interface ChangeSubscriptionOptions {
  intervalMs?: number;
  fetchVersion?: () => Promise<{ board: string; page: string }>;
  reloadPage?: () => void;
}

/**
 * 轮询 /api/version:数据库变了就回调刷新数据;页面构建产物或服务端代码变了就整页重载。
 * 返回停止函数;非网页模式直接返回空操作。
 */
export function subscribeBoardChanges(
  onChange: () => void,
  options: ChangeSubscriptionOptions = {},
): () => void {
  if (detectBackend() !== "web") return () => {};
  const intervalMs = options.intervalMs ?? CHANGE_POLL_INTERVAL_MS;
  const fetchVersion = options.fetchVersion
    ?? (() => webGet<{ board: string; page: string }>("/api/version"));
  const reloadPage = options.reloadPage ?? (() => window.location.reload());
  let known: { board: string; page: string } | null = null;
  let inFlight = false;
  const timer = setInterval(async () => {
    if (inFlight || (typeof document !== "undefined" && document.hidden)) return;
    inFlight = true;
    try {
      const current = await fetchVersion();
      if (known && current.page !== known.page) {
        reloadPage();
      } else if (known && current.board !== known.board) {
        onChange();
      }
      known = current;
    } catch {
      // 服务暂时不可达时保持上一次数据,下一轮再试。
    } finally {
      inFlight = false;
    }
  }, intervalMs);
  return () => clearInterval(timer);
}
