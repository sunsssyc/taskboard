import { describe, expect, it } from "vitest";
import { projectDisplayName } from "./projectName";

describe("project display name", () => {
  it("prefers the human-facing Chinese name over the technical key", () => {
    expect(projectDisplayName({ key: "reg-calibration", name: "注册风控模型校准" }))
      .toBe("注册风控模型校准");
  });

  it("prefers a Chinese key when the configured name is only English", () => {
    expect(projectDisplayName({ key: "推理平台", name: "AI Inference Platform" }))
      .toBe("推理平台");
  });

  it("keeps a readable English name when no Chinese candidate exists", () => {
    expect(projectDisplayName({ key: "deepseek-harness", name: "DeepSeek Harness" }))
      .toBe("DeepSeek Harness");
  });

  it("falls back to the key when the name is empty", () => {
    expect(projectDisplayName({ key: "taskboard", name: "  " })).toBe("taskboard");
  });
});
