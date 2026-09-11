import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTO_REFRESH_INTERVAL_MS, createAutoRefresh } from "./refresh";

describe("board auto refresh", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("refreshes once per interval while visible", () => {
    const refresh = vi.fn();
    const auto = createAutoRefresh(refresh, { isHidden: () => false });
    auto.start();
    vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL_MS * 3);
    expect(refresh).toHaveBeenCalledTimes(3);
    auto.stop();
  });

  it("skips ticks while a load is already running", () => {
    const refresh = vi.fn();
    let busy = true;
    const auto = createAutoRefresh(refresh, {
      isHidden: () => false,
      isBusy: () => busy,
    });
    auto.start();
    vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL_MS);
    expect(refresh).not.toHaveBeenCalled();
    busy = false;
    vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL_MS);
    expect(refresh).toHaveBeenCalledTimes(1);
    auto.stop();
  });

  it("defers hidden-window ticks and catches up once on visible", () => {
    const refresh = vi.fn();
    let hidden = true;
    const auto = createAutoRefresh(refresh, { isHidden: () => hidden });
    auto.start();
    vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL_MS * 4);
    expect(refresh).not.toHaveBeenCalled();
    hidden = false;
    auto.onVisible();
    expect(refresh).toHaveBeenCalledTimes(1);
    auto.onVisible();
    expect(refresh).toHaveBeenCalledTimes(1);
    auto.stop();
  });

  it("stops firing after stop", () => {
    const refresh = vi.fn();
    const auto = createAutoRefresh(refresh, { isHidden: () => false });
    auto.start();
    vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL_MS);
    auto.stop();
    vi.advanceTimersByTime(AUTO_REFRESH_INTERVAL_MS * 5);
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
