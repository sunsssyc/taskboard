import { describe, expect, it } from "vitest";
import { boardReferenceParts } from "./references";

describe("board reference parsing", () => {
  it("recognizes task and note references without losing surrounding text", () => {
    expect(boardReferenceParts("主线 #50，依据 [382]。")).toEqual([
      { kind: "text", text: "主线 " },
      { kind: "reference", text: "#50", reference: { kind: "task", id: 50 } },
      { kind: "text", text: "，依据 " },
      { kind: "reference", text: "[382]", reference: { kind: "note", id: 382 } },
      { kind: "text", text: "。" },
    ]);
  });

  it("keeps both ends of a note range independently addressable", () => {
    const references = boardReferenceParts("([375]~[383])")
      .filter((part) => part.kind === "reference")
      .map((part) => part.reference);

    expect(references).toEqual([
      { kind: "note", id: 375 },
      { kind: "note", id: 383 },
    ]);
  });

  it("returns ordinary text unchanged when no reference exists", () => {
    expect(boardReferenceParts("没有引用")).toEqual([{ kind: "text", text: "没有引用" }]);
  });
});
