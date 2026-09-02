import { describe, expect, it } from "vitest";
import { demoSnapshot } from "./demo";
import { buildNoteSheets } from "./noteSheets";

describe("note sheets", () => {
  it("turns each topic category into one sheet", () => {
    const project = demoSnapshot.projects[0];
    const sheets = buildNoteSheets(project.findings, project.risks, project.links);
    expect(sheets.map((sheet) => sheet.label)).toEqual([
      "产品结构",
      "macOS App",
      "数据口径",
      "发布协同",
    ]);
    expect(sheets.map((sheet) => sheet.notes.length)).toEqual([2, 4, 3, 2]);
    expect(sheets.find((sheet) => sheet.label === "发布协同")?.notes.map((note) => note.kind))
      .toEqual(["finding", "risk"]);
    expect(sheets.find((sheet) => sheet.label === "macOS App")?.notes.map((note) => note.kind))
      .toEqual(["finding", "finding", "finding", "link"]);
  });

  it("merges duplicate category names across note kinds", () => {
    const finding = { ...demoSnapshot.projects[0].findings[0], category: "发布" };
    const risk = { ...demoSnapshot.projects[0].risks[0], category: "发布" };
    const link = { ...demoSnapshot.projects[0].links[0], category: "发布" };
    const sheets = buildNoteSheets([finding], [risk], [link]);
    expect(sheets.map((sheet) => sheet.id)).toEqual(["发布"]);
    expect(sheets[0].notes.map((note) => note.kind)).toEqual(["finding", "risk", "link"]);
  });
});
