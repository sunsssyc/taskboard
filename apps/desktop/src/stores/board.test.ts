import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { demoSnapshot } from "../demo";
import { dispatchTaskAgent, loadBoardSnapshot, saveTaskOwner, saveTaskStatus } from "../board";

vi.mock("../board", () => ({
  loadBoardSnapshot: vi.fn(async () => ({
    snapshot: { generated_at: "", db: "", projects: [] },
    source: "测试桥接",
    viewPrefs: { order: [], pinned: [] },
  })),
  saveBoardViewPrefs: vi.fn(async (prefs: unknown) => prefs),
  dispatchTaskAgent: vi.fn(async () => ({
    provider: "codex",
    dispatchId: "codex-test",
    repositoryPath: "/Users/demo/taskboard",
    status: "submitted",
    externalThreadId: "thread-test",
    externalTurnId: "turn-test",
    startedAt: "2026-08-27T00:00:00+00:00",
    warning: null,
  })),
  saveTaskOwner: vi.fn(async () => {}),
  saveTaskStatus: vi.fn(async () => {}),
}));
import {
  moveProjectOrder,
  noteMatches,
  projectMatches,
  sortProjectsByPrefs,
  taskMatches,
  useBoardStore,
} from "./board";

describe("task status switch", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("delegates to the CLI bridge and reloads the snapshot", async () => {
    const board = useBoardStore();
    await board.setTaskStatus("taskboard", 26, "done");
    expect(saveTaskStatus).toHaveBeenCalledWith("taskboard", 26, "done");
    expect(loadBoardSnapshot).toHaveBeenCalledTimes(1);
    expect(board.actionError).toBe("");
  });

  it("surfaces bridge failures without dropping current data", async () => {
    vi.mocked(saveTaskStatus).mockRejectedValueOnce(new Error("CLI 不可用"));
    const board = useBoardStore();
    board.snapshot = demoSnapshot;
    await board.setTaskStatus("taskboard", 26, "active");
    expect(board.actionError).toContain("CLI 不可用");
    expect(board.snapshot).toStrictEqual(demoSnapshot);
    expect(loadBoardSnapshot).not.toHaveBeenCalled();
  });
});

describe("task owner switch", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("delegates assignment to the CLI bridge and reloads the snapshot", async () => {
    const board = useBoardStore();
    await board.setTaskOwner("taskboard", 32, "我");
    expect(saveTaskOwner).toHaveBeenCalledWith("taskboard", 32, "我");
    expect(loadBoardSnapshot).toHaveBeenCalledTimes(1);
    expect(board.actionError).toBe("");
  });

  it("supports clearing an assignment", async () => {
    const board = useBoardStore();
    await board.setTaskOwner("taskboard", 32, "");
    expect(saveTaskOwner).toHaveBeenCalledWith("taskboard", 32, "");
  });
});

describe("task Agent dispatch", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("keeps assignment and actual dispatch as separate actions", async () => {
    const board = useBoardStore();
    const task = demoSnapshot.projects[0].tasks[0];
    await board.dispatchTask("taskboard", task, "codex", "/Users/demo/taskboard");

    expect(dispatchTaskAgent).toHaveBeenCalledWith(expect.objectContaining({
      provider: "codex",
      project: "taskboard",
      reference: task.ref,
      repositoryPath: "/Users/demo/taskboard",
    }));
    expect(saveTaskOwner).not.toHaveBeenCalled();
    expect(board.actionNotice).toContain("Codex 已接收");
    expect(loadBoardSnapshot).toHaveBeenCalledTimes(1);
  });

  it("surfaces dispatch failures and clears busy state", async () => {
    vi.mocked(dispatchTaskAgent).mockRejectedValueOnce(new Error("未安装 Claude 桌面应用"));
    const board = useBoardStore();
    const task = demoSnapshot.projects[0].tasks[0];
    await board.dispatchTask("taskboard", task, "claude", "/Users/demo/taskboard");

    expect(board.actionError).toContain("未安装 Claude");
    expect(board.dispatchingTask).toBe("");
    expect(loadBoardSnapshot).not.toHaveBeenCalled();
  });
});

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

  it("searches project metadata as a whole-project match", () => {
    const project = demoSnapshot.projects[1];
    expect(projectMatches(project, "coinex_backend")).toBe(true);
    expect(projectMatches(project, "不存在")).toBe(false);
  });

  it("supports all-project, status, and owner filters", () => {
    const board = useBoardStore();
    board.snapshot = demoSnapshot;
    expect(board.selectedProject).toBeNull();
    expect(board.displayProjects).toHaveLength(2);

    board.statusFilter = "active";
    expect(board.filteredTasks(demoSnapshot.projects[0]).map((task) => task.ref)).toEqual([26]);

    board.statusFilter = "";
    board.ownerFilter = "双方";
    expect(board.filteredTasks(demoSnapshot.projects[0]).map((task) => task.ref)).toEqual([18]);
  });

  it("sorts pinned projects before the remembered order", () => {
    const ordered = sortProjectsByPrefs(demoSnapshot.projects, {
      order: ["reg-calibration", "taskboard"],
      pinned: ["taskboard"],
    });
    expect(ordered.map((project) => project.key)).toEqual(["taskboard", "reg-calibration"]);
  });

  it("moves projects before or after the drop target", () => {
    expect(moveProjectOrder(["a", "b", "c"], "c", "a", true)).toEqual(["c", "a", "b"]);
    expect(moveProjectOrder(["a", "b", "c"], "a", "b", false)).toEqual(["b", "a", "c"]);
  });
});
