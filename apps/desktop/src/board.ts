import { invoke } from "@tauri-apps/api/core";
import { demoSnapshot } from "./demo";
import type {
  AgentRun,
  AgentDispatchRequest,
  AgentDispatchResult,
  BoardLoadResponse,
  BoardSnapshot,
  TaskOwner,
  TaskStatus,
  ViewPrefs,
} from "./types";

const ORDER_KEY = "taskboard:order";
const PINNED_KEY = "taskboard:pinned";
const browserDemoSnapshot = structuredClone(demoSnapshot);

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
    warning: "网页演示：未实际启动桌面 Agent。",
  };
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

export async function loadBoardSnapshot(): Promise<BoardLoadResponse> {
  if (!window.__TAURI_INTERNALS__) {
    return {
      snapshot: structuredClone(browserDemoSnapshot),
      source: "浏览器演示数据",
      viewPrefs: readBrowserViewPrefs(),
    };
  }
  return invoke<BoardLoadResponse>("load_board");
}

export async function saveTaskStatus(
  project: string,
  reference: number,
  status: TaskStatus,
): Promise<void> {
  if (!window.__TAURI_INTERNALS__) {
    throw new Error("浏览器演示数据不支持修改状态;运行 npm run tauri dev 后操作真实看板。");
  }
  await invoke("set_task_status", { project, reference, status });
}

export async function saveTaskOwner(
  project: string,
  reference: number,
  owner: TaskOwner,
): Promise<void> {
  if (!window.__TAURI_INTERNALS__) {
    throw new Error("浏览器演示数据不支持修改负责人;运行 npm run tauri dev 后操作真实看板。");
  }
  await invoke("set_task_owner", { project, reference, owner });
}

export async function dispatchTaskAgent(
  request: AgentDispatchRequest,
): Promise<AgentDispatchResult> {
  if (!window.__TAURI_INTERNALS__) {
    return simulateBrowserAgentDispatch(browserDemoSnapshot, request);
  }
  return invoke<AgentDispatchResult>("dispatch_task_agent", { request });
}

export async function saveBoardViewPrefs(prefs: ViewPrefs): Promise<ViewPrefs> {
  if (!window.__TAURI_INTERNALS__) {
    localStorage.setItem(ORDER_KEY, JSON.stringify(prefs.order));
    localStorage.setItem(PINNED_KEY, JSON.stringify(prefs.pinned));
    return prefs;
  }
  return invoke<ViewPrefs>("save_view_prefs", { prefs });
}
