import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { demoSnapshot } from "../demo";
import {
  dispatchTaskAgent,
  loadBoardSnapshot,
  saveProjectArchived,
  saveTaskOwner,
  saveTaskPriority,
  saveTaskStatus,
} from "../board";

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
  saveTaskPriority: vi.fn(async () => {}),
  saveTaskStatus: vi.fn(async () => {}),
  saveProjectArchived: vi.fn(async () => {}),
}));
import {
  moveProjectOrder,
  noteMatches,
  parseSearchQuery,
  projectMatches,
  resolveSearchQuery,
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

describe("project completion", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("archives the selected project and returns to the active project list", async () => {
    vi.useFakeTimers();
    const board = useBoardStore();
    board.snapshot = demoSnapshot;
    board.selectProject("taskboard");

    await board.setProjectArchived("taskboard", true);

    expect(saveProjectArchived).toHaveBeenCalledWith("taskboard", true);
    expect(board.selectedProjectKey).toBe("");
    expect(board.actionNotice).toContain("仍有 6 项未完成任务");
    expect(loadBoardSnapshot).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1400);
    expect(board.actionNotice).toBe("");
    vi.useRealTimers();
  });

  it("separates archived projects from the normal sidebar collection", () => {
    const board = useBoardStore();
    board.snapshot = structuredClone(demoSnapshot);
    board.snapshot.projects[0].archived = true;

    expect(board.projects.map((project) => project.key)).toEqual(["reg-calibration"]);
    expect(board.archivedProjects.map((project) => project.key)).toEqual(["taskboard"]);
  });

  it("restores a completed project through the same bridge", async () => {
    vi.useFakeTimers();
    const board = useBoardStore();
    await board.setProjectArchived("taskboard", false);

    expect(saveProjectArchived).toHaveBeenCalledWith("taskboard", false);
    expect(board.actionNotice).toContain("已恢复");

    await vi.advanceTimersByTimeAsync(1400);
    expect(board.actionNotice).toBe("");
    vi.useRealTimers();
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

describe("task priority switch", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("persists the new priority through the CLI bridge and reloads", async () => {
    const board = useBoardStore();
    await board.setTaskPriority("taskboard", 24, 0);
    expect(saveTaskPriority).toHaveBeenCalledWith("taskboard", 24, 0);
    expect(loadBoardSnapshot).toHaveBeenCalledTimes(1);
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
    expect(taskMatches(task, "P0")).toBe(true);
    expect(taskMatches(task, "不存在")).toBe(false);
  });

  it("matches note categories and metrics", () => {
    const note = demoSnapshot.projects[0].findings[0];
    expect(noteMatches(note, "产品结构")).toBe(true);
    expect(noteMatches(note, "6 个需求")).toBe(true);
  });

  it("parses plain, task, and note ID queries", () => {
    expect(parseSearchQuery("262")).toEqual({ kind: "any-id", id: 262, needle: "262" });
    expect(parseSearchQuery(" #262 ")).toEqual({ kind: "task-id", id: 262 });
    expect(parseSearchQuery("[262]")).toEqual({ kind: "note-id", id: 262 });
    expect(parseSearchQuery("262 修复")).toEqual({ kind: "text", needle: "262 修复" });
  });

  it("matches plain digits against both exact IDs and body text", () => {
    const sourceTask = demoSnapshot.projects[0].tasks[0];
    const targetTask = { ...sourceTask, ref: 262, detail: "目标任务" };
    const referencedTask = { ...sourceTask, ref: 292, detail: "后续按 #262 推进" };
    const sourceNote = demoSnapshot.projects[0].findings[0];
    const targetNote = { ...sourceNote, id: 262, body: "目标结论" };
    const referencedNote = { ...sourceNote, id: 292, body: "后续按 [262] 的方向补齐" };

    expect(taskMatches(targetTask, "262")).toBe(true);
    expect(taskMatches(referencedTask, "262")).toBe(true);
    expect(noteMatches(targetNote, "262")).toBe(true);
    expect(noteMatches(referencedNote, "262")).toBe(true);
    expect(taskMatches(targetTask, "#262")).toBe(true);
    expect(noteMatches(targetNote, "#262")).toBe(false);
    expect(noteMatches(targetNote, "[262]")).toBe(true);
    expect(taskMatches(targetTask, "[262]")).toBe(false);
  });

  it("falls back to full-text search when a plain numeric ID does not exist", () => {
    const snapshot = structuredClone(demoSnapshot);
    const project = snapshot.projects.find((item) => item.key === "reg-calibration");
    expect(project).toBeDefined();

    const sourceTask = project!.tasks[0];
    const sourceNote = project!.findings[0];
    project!.tasks = [{ ...sourceTask, ref: 291, detail: "补齐 3000 条训练样本" }];
    project!.findings = [{ ...sourceNote, id: 292, body: "固定导出 3000 条" }];

    expect(resolveSearchQuery("3000", snapshot.projects))
      .toEqual({ kind: "any-id", id: 3000, needle: "3000" });

    const board = useBoardStore();
    board.snapshot = snapshot;
    board.selectProject("reg-calibration");
    board.query = "3000";

    expect(board.matchingTasks.map((task) => task.ref)).toEqual([291]);
    expect(board.matchingFindings.map((note) => note.id)).toEqual([292]);

    board.query = "#3000";
    expect(board.matchingTasks).toEqual([]);
    board.query = "[3000]";
    expect(board.matchingFindings).toEqual([]);
  });

  it("prioritizes the exact note ID while keeping text matches", () => {
    const snapshot = structuredClone(demoSnapshot);
    const project = snapshot.projects.find((item) => item.key === "reg-calibration");
    expect(project).toBeDefined();

    const sourceNote = project!.findings[0];
    project!.findings = [
      { ...sourceNote, id: 292, title: "引用结论", body: "后续按 [262] 的方向补齐" },
      { ...sourceNote, id: 262, title: "目标结论", body: "目标正文" },
    ];

    const board = useBoardStore();
    board.snapshot = snapshot;
    board.selectProject("reg-calibration");
    board.query = "262";

    expect(board.matchingTasks).toEqual([]);
    expect(board.matchingFindings.map((note) => note.id)).toEqual([262, 292]);
  });

  it("does not turn project metadata into an ID-wide match", () => {
    const project = {
      ...demoSnapshot.projects[0],
      summary: "当前任务 #262，结论 [262]",
    };
    expect(projectMatches(project, "262")).toBe(false);
    expect(projectMatches(project, "#262")).toBe(false);
    expect(projectMatches(project, "[262]")).toBe(false);
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

  it("separates pinned projects from the regular sidebar collection", () => {
    const board = useBoardStore();
    board.snapshot = demoSnapshot;
    board.viewPrefs = {
      order: ["reg-calibration", "taskboard"],
      pinned: ["taskboard"],
    };

    expect(board.pinnedProjects.map((project) => project.key)).toEqual(["taskboard"]);
    expect(board.regularProjects.map((project) => project.key)).toEqual(["reg-calibration"]);
  });

  it("moves projects before or after the drop target", () => {
    expect(moveProjectOrder(["a", "b", "c"], "c", "a", true)).toEqual(["c", "a", "b"]);
    expect(moveProjectOrder(["a", "b", "c"], "a", "b", false)).toEqual(["b", "a", "c"]);
  });
});
