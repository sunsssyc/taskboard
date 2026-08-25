export const AUTO_REFRESH_INTERVAL_MS = 60_000;

export interface AutoRefreshOptions {
  intervalMs?: number;
  isHidden?: () => boolean;
  isBusy?: () => boolean;
}

export interface AutoRefreshHandle {
  start(): void;
  stop(): void;
  onVisible(): void;
}

export function createAutoRefresh(
  refresh: () => void,
  options: AutoRefreshOptions = {},
): AutoRefreshHandle {
  const intervalMs = options.intervalMs ?? AUTO_REFRESH_INTERVAL_MS;
  const isHidden = options.isHidden ?? (() => document.hidden);
  const isBusy = options.isBusy ?? (() => false);
  let timer: ReturnType<typeof setInterval> | undefined;
  let missedWhileHidden = false;

  function tick() {
    if (isHidden()) {
      missedWhileHidden = true;
      return;
    }
    if (isBusy()) return;
    missedWhileHidden = false;
    refresh();
  }

  return {
    start() {
      if (timer === undefined) timer = setInterval(tick, intervalMs);
    },
    stop() {
      if (timer !== undefined) {
        clearInterval(timer);
        timer = undefined;
      }
    },
    onVisible() {
      if (missedWhileHidden && !isHidden()) tick();
    },
  };
}
