import { describe, expect, it } from "vitest";
import {
  MAX_ZOOM,
  MIN_ZOOM,
  clampZoom,
  zoomActionForShortcut,
  zoomForAction,
} from "./zoom";

describe("desktop zoom shortcuts", () => {
  it("recognizes macOS and cross-platform shortcuts", () => {
    expect(zoomActionForShortcut({ key: "=", metaKey: true, ctrlKey: false, altKey: false })).toBe("in");
    expect(zoomActionForShortcut({ key: "+", metaKey: false, ctrlKey: true, altKey: false })).toBe("in");
    expect(zoomActionForShortcut({ key: "-", metaKey: true, ctrlKey: false, altKey: false })).toBe("out");
    expect(zoomActionForShortcut({ key: "0", metaKey: false, ctrlKey: true, altKey: false })).toBe("reset");
    expect(zoomActionForShortcut({ key: "=", metaKey: false, ctrlKey: false, altKey: false })).toBeNull();
  });

  it("steps by ten percent and resets", () => {
    expect(zoomForAction(1, "in")).toBe(1.1);
    expect(zoomForAction(1, "out")).toBe(0.9);
    expect(zoomForAction(1.4, "reset")).toBe(1);
  });

  it("clamps zoom to a readable range", () => {
    expect(clampZoom(0.2)).toBe(MIN_ZOOM);
    expect(clampZoom(4)).toBe(MAX_ZOOM);
    expect(zoomForAction(MIN_ZOOM, "out")).toBe(MIN_ZOOM);
    expect(zoomForAction(MAX_ZOOM, "in")).toBe(MAX_ZOOM);
  });
});
