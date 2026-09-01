import { describe, expect, it } from "vitest";
import { parseMarkdownBlocks } from "./markdown";

describe("desktop Markdown parser", () => {
  it("parses a table into semantic header and body data", () => {
    const blocks = parseMarkdownBlocks([
      "| 指标 | 缺失填 0 | 缺失保留 NaN |",
      "|---|:---:|---:|",
      "| OOT AUC | 0.9765 | 0.9657 |",
      "| `recall@0.30` | **0.345** | 0.351 |",
    ].join("\n"));

    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({
      kind: "table",
      alignments: ["left", "center", "right"],
    });
    if (blocks[0].kind !== "table") throw new Error("expected table");
    expect(blocks[0].header[0]).toEqual([{ kind: "text", text: "指标" }]);
    expect(blocks[0].rows).toHaveLength(2);
    expect(blocks[0].rows[1][0]).toEqual([{ kind: "code", text: "recall@0.30" }]);
    expect(blocks[0].rows[1][1]).toEqual([{ kind: "strong", text: "0.345" }]);
  });

  it("keeps ordinary pipe-separated prose as a paragraph", () => {
    const blocks = parseMarkdownBlocks("影响：旧值 | 新值 | 仍需验证");
    expect(blocks).toEqual([{
      kind: "paragraph",
      parts: [{ kind: "text", text: "影响：旧值 | 新值 | 仍需验证" }],
    }]);
  });

  it("does not split escaped or inline-code pipes inside cells", () => {
    const blocks = parseMarkdownBlocks([
      "| 规则 | 值 |",
      "| --- | --- |",
      "| A \\| B | `left|right` |",
    ].join("\n"));
    if (blocks[0].kind !== "table") throw new Error("expected table");
    expect(blocks[0].rows[0][0]).toEqual([{ kind: "text", text: "A | B" }]);
    expect(blocks[0].rows[0][1]).toEqual([{ kind: "code", text: "left|right" }]);
  });
});
