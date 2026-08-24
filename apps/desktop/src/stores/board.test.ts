import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { demoSnapshot } from "../demo";
import { noteMatches, taskMatches, useBoardStore } from "./board";

describe("board search", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("matches task metadata and repository names", () => {
    const task = demoSnapshot.projects[0].tasks[0];
    expect(taskMatches(task, "tauri")).toBe(true);
    expect(taskMatches(task, "taskboard")).toBe(true);
    expect(taskMatches(task, "不存在")).toBe(false);
  });

  it("matches note categories and metrics", () => {
    const note = demoSnapshot.projects[0].findings[0];
    expect(noteMatches(note, "产品结构")).toBe(true);
    expect(noteMatches(note, "6 个需求")).toBe(true);
  });

  it("keeps selected project and search state in one store", () => {
    const board = useBoardStore();
    board.snapshot = demoSnapshot;
    board.selectProject("reg-calibration");
    board.query = "概率";
    expect(board.selectedProject?.key).toBe("reg-calibration");
    expect(board.matchingTasks.map((task) => task.ref)).toEqual([27]);
  });
});
