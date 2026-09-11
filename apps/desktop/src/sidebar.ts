export const DEFAULT_SIDEBAR_WIDTH = 248;
export const MIN_SIDEBAR_WIDTH = 196;
export const MAX_SIDEBAR_WIDTH = 420;
export const SIDEBAR_WIDTH_STEP = 16;

export function clampSidebarWidth(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_SIDEBAR_WIDTH;
  return Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, Math.round(value)));
}

export function parseStoredSidebarWidth(value: string | null): number {
  if (!value?.trim()) return DEFAULT_SIDEBAR_WIDTH;
  return clampSidebarWidth(Number(value));
}
