import { describe, expect, it } from "vitest";
import { OWNER_OPTIONS, ownerLabel } from "./owner";

describe("owner labels", () => {
  it("uses product-facing names without changing stored owner values", () => {
    expect(ownerLabel("你")).toBe("用户");
    expect(ownerLabel("我")).toBe("Agent");
    expect(ownerLabel("双方")).toBe("双方");
  });

  it("offers every supported assignment including clearing the owner", () => {
    expect(OWNER_OPTIONS).toEqual([
      { value: "你", label: "用户" },
      { value: "我", label: "Agent" },
      { value: "双方", label: "双方" },
      { value: "", label: "未分配" },
    ]);
  });
});
