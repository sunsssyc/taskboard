import { describe, expect, it } from "vitest";
import { demoSnapshot } from "./demo";
import { simulateBrowserAgentDispatch } from "./board";

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
