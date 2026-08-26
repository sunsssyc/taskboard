import { describe, expect, it } from "vitest";
import { demoSnapshot } from "./demo";
import { buildNoteSheets } from "./noteSheets";

describe("note sheets", () => {
  it("turns each finding category into one sheet", () => {
    const project = demoSnapshot.projects[0];
    const sheets = buildNoteSheets(project.findings, project.risks, project.links);
    expect(sheets.slice(0, 2).map((sheet) => sheet.label)).toEqual(["产品结构", "macOS App"]);
    expect(sheets.some((sheet) => sheet.label === "风险 · 发布协同")).toBe(true);
    expect(sheets.some((sheet) => sheet.label === "入口 · 实现入口")).toBe(true);
    expect(sheets.every((sheet) => sheet.notes.length === 1)).toBe(true);
  });

  it("keeps duplicate category names isolated by note kind", () => {
    const finding = { ...demoSnapshot.projects[0].findings[0], category: "发布" };
    const risk = { ...demoSnapshot.projects[0].risks[0], category: "发布" };
    const sheets = buildNoteSheets([finding], [risk], []);
    expect(sheets.map((sheet) => sheet.id)).toEqual(["finding:发布", "risk:发布"]);
    expect(sheets.map((sheet) => sheet.label)).toEqual(["发布", "风险 · 发布"]);
  });
});
