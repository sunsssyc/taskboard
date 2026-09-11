import { describe, expect, it } from "vitest";
import {
  DEFAULT_SIDEBAR_WIDTH,
  MAX_SIDEBAR_WIDTH,
  MIN_SIDEBAR_WIDTH,
  clampSidebarWidth,
  parseStoredSidebarWidth,
} from "./sidebar";

describe("desktop sidebar width", () => {
  it("keeps the width inside a usable range", () => {
    expect(clampSidebarWidth(120)).toBe(MIN_SIDEBAR_WIDTH);
    expect(clampSidebarWidth(320.4)).toBe(320);
    expect(clampSidebarWidth(600)).toBe(MAX_SIDEBAR_WIDTH);
  });

  it("falls back safely when persisted data is missing or invalid", () => {
    expect(parseStoredSidebarWidth(null)).toBe(DEFAULT_SIDEBAR_WIDTH);
    expect(parseStoredSidebarWidth("not-a-number")).toBe(DEFAULT_SIDEBAR_WIDTH);
    expect(parseStoredSidebarWidth("360")).toBe(360);
  });
});
