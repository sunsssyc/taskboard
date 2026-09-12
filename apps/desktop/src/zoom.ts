import { getCurrentWebview } from "@tauri-apps/api/webview";

export const MIN_ZOOM = 0.75;
export const MAX_ZOOM = 1.75;
export const ZOOM_STEP = 0.1;
export const DEFAULT_ZOOM = 1;

const STORAGE_KEY = "taskboard:zoom";

export type ZoomAction = "in" | "out" | "reset";

type ShortcutEvent = Pick<KeyboardEvent, "key" | "metaKey" | "ctrlKey" | "altKey">;

export function zoomActionForShortcut(event: ShortcutEvent): ZoomAction | null {
  if ((!event.metaKey && !event.ctrlKey) || event.altKey) return null;
  if (event.key === "+" || event.key === "=") return "in";
  if (event.key === "-" || event.key === "_") return "out";
  if (event.key === "0") return "reset";
  return null;
}

export function clampZoom(scale: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(scale * 100) / 100));
}

export function zoomForAction(current: number, action: ZoomAction): number {
  if (action === "reset") return DEFAULT_ZOOM;
  const delta = action === "in" ? ZOOM_STEP : -ZOOM_STEP;
  return clampZoom(Math.round((current + delta) * 10) / 10);
}

export function readStoredZoom(): number {
  try {
    const stored = Number.parseFloat(localStorage.getItem(STORAGE_KEY) ?? "");
    return Number.isFinite(stored) ? clampZoom(stored) : DEFAULT_ZOOM;
  } catch {
    return DEFAULT_ZOOM;
  }
}

function rememberZoom(scale: number) {
  try {
    localStorage.setItem(STORAGE_KEY, String(scale));
  } catch {
    // 隐私模式或存储被禁用时保留当前会话缩放。
  }
}

export async function applyZoom(scale: number): Promise<number> {
  const normalized = clampZoom(scale);
  if (window.__TAURI_INTERNALS__) {
    await getCurrentWebview().setZoom(normalized);
  } else {
    document.documentElement.style.setProperty("zoom", String(normalized));
  }
  rememberZoom(normalized);
  return normalized;
}
