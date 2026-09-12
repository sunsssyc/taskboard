import { afterEach, describe, expect, it, vi } from "vitest";
import { demoSnapshot } from "./demo";
import {
  detectBackend,
  normalizeSnapshot,
  normalizeTaskPriorities,
  simulateBrowserAgentDispatch,
  simulateConceptAction,
  subscribeBoardChanges,
} from "./board";

describe("browser Agent dispatch demo", () => {
  it("records a simulated Codex run without launching a desktop Agent", () => {
    const snapshot = structuredClone(demoSnapshot);
    const project = snapshot.projects[0];
    const task = project.tasks[0];
    const result = simulateBrowserAgentDispatch(
      snapshot,
      {
        provider: "codex",
        project: project.key,
        reference: task.ref,
        title: task.title,
        detail: task.detail,
        accept: task.accept,
        repositoryPath: task.repositories[0].path!,
      },
      new Date("2026-08-27T08:00:00.000Z"),
    );

    expect(result.status).toBe("submitted");
    expect(result.warning).toContain("未实际启动");
    expect(task.agent_runs[0]).toMatchObject({
      provider: "codex",
      status: "submitted",
      repository_path: "/Users/demo/taskboard",
      external_thread_id: "demo-thread-1787817600000-1",
    });
  });

  it("rejects task references outside the demo snapshot", () => {
    const snapshot = structuredClone(demoSnapshot);
    expect(() => simulateBrowserAgentDispatch(snapshot, {
      provider: "claude",
      project: "taskboard",
      reference: 999,
      title: "missing",
      detail: null,
      accept: null,
      repositoryPath: "/Users/demo/taskboard",
    })).toThrow("找不到任务 #999");
  });
});

describe("priority snapshot compatibility", () => {
  it("maps snapshots from an older CLI to the P2 compatibility default", () => {
    const snapshot = structuredClone(demoSnapshot);
    delete (snapshot.projects[0].tasks[0] as { priority?: number }).priority;

    expect(normalizeTaskPriorities(snapshot).projects[0].tasks[0].priority).toBe(2);
  });
});

describe("snapshot compatibility", () => {
  it("fills in concepts for snapshots from a CLI that predates concept cards", () => {
    const snapshot = structuredClone(demoSnapshot);
    delete (snapshot.projects[0] as { concepts?: unknown }).concepts;
    expect(normalizeSnapshot(snapshot).projects[0].concepts).toEqual([]);
  });
});

// vitest 跑在 node 环境,没有 window;按需塞一个最小的
function stubWindow(fields: Partial<Window> = {}) {
  vi.stubGlobal("window", { ...fields });
}

describe("backend detection", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("falls back to demo data when there is no window at all", () => {
    expect(detectBackend()).toBe("demo");
  });

  it("prefers Tauri, then the board serve page context, then demo data", () => {
    stubWindow();
    expect(detectBackend()).toBe("demo");
    stubWindow({ __TASKBOARD_WEB__: { csrf: "t", writeEnabled: true, title: "看板", dev: false } });
    expect(detectBackend()).toBe("web");
    stubWindow({ __TAURI_INTERNALS__: {}, __TASKBOARD_WEB__: { csrf: "t", writeEnabled: true, title: "看板", dev: false } });
    expect(detectBackend()).toBe("tauri");
  });
});

describe("concept demo actions", () => {
  it("aligns, rejects and edits in place with the CLI's rules", () => {
    const snapshot = structuredClone(demoSnapshot);
    const aligned = simulateConceptAction(snapshot, 330, "align");
    expect(aligned.state).toBe("aligned");
    expect(aligned.aligned_commit).toBe("demo1234");

    // 改措辞退回待对齐;勾了 keepAligned 才保留
    expect(simulateConceptAction(snapshot, 330, "edit", { edit: { title: "换说法" } }).state)
      .toBe("proposed");
    simulateConceptAction(snapshot, 330, "align");
    expect(simulateConceptAction(snapshot, 330, "edit", {
      edit: { body: "补一句", keepAligned: true },
    }).state).toBe("aligned");

    expect(() => simulateConceptAction(snapshot, 330, "reject", { reason: " " }))
      .toThrow("否决要给理由");
    expect(simulateConceptAction(snapshot, 330, "reject", { reason: "不算新概念" }).state)
      .toBe("rejected");
    expect(() => simulateConceptAction(snapshot, 330, "align")).toThrow("已被否决");
    expect(() => simulateConceptAction(snapshot, 999, "align")).toThrow("[999]");
  });
});

describe("board serve change subscription", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("is a no-op outside the web backend", () => {
    stubWindow();
    const stop = subscribeBoardChanges(() => { throw new Error("不该被调用"); });
    stop();
  });

  it("reloads data when the database changes and the page when the build changes", async () => {
    vi.useFakeTimers();
    stubWindow({ __TASKBOARD_WEB__: { csrf: "t", writeEnabled: true, title: "看板", dev: false } });
    const versions = [
      { board: "1", page: "a" },
      { board: "1", page: "a" },
      { board: "2", page: "a" },
      { board: "2", page: "b" },
    ];
    const onChange = vi.fn();
    const reloadPage = vi.fn();
    const stop = subscribeBoardChanges(onChange, {
      intervalMs: 10,
      fetchVersion: async () => versions.shift() ?? { board: "2", page: "b" },
      reloadPage,
    });
    for (let i = 0; i < 4; i += 1) await vi.advanceTimersByTimeAsync(10);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(reloadPage).toHaveBeenCalledTimes(1);
    stop();
  });
});
