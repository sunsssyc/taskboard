import { invoke } from "@tauri-apps/api/core";
import { demoSnapshot } from "./demo";
import type { BoardLoadResponse, TaskStatus, ViewPrefs } from "./types";

const ORDER_KEY = "taskboard:order";
const PINNED_KEY = "taskboard:pinned";

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
      snapshot: demoSnapshot,
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

export async function saveBoardViewPrefs(prefs: ViewPrefs): Promise<ViewPrefs> {
  if (!window.__TAURI_INTERNALS__) {
    localStorage.setItem(ORDER_KEY, JSON.stringify(prefs.order));
    localStorage.setItem(PINNED_KEY, JSON.stringify(prefs.pinned));
    return prefs;
  }
  return invoke<ViewPrefs>("save_view_prefs", { prefs });
}
