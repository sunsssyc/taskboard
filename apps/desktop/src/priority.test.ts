import { describe, expect, it } from "vitest";
import { demoSnapshot } from "./demo";
import { sortTasksByPriority } from "./priority";

describe("task priority order", () => {
  it("sorts P0 before P3 and keeps active work ahead when priorities tie", () => {
    const base = demoSnapshot.projects[0].tasks[0];
    const tasks = [
      { ...base, ref: 3, status: "todo" as const, priority: 1 as const },
      { ...base, ref: 2, status: "active" as const, priority: 1 as const },
      { ...base, ref: 1, status: "todo" as const, priority: 0 as const },
      { ...base, ref: 4, status: "todo" as const, priority: 3 as const },
    ];

    expect(sortTasksByPriority(tasks).map((task) => task.ref)).toEqual([1, 2, 3, 4]);
  });

  it("does not mutate the snapshot task order", () => {
    const tasks = demoSnapshot.projects[0].tasks.slice(0, 3);
    const refs = tasks.map((task) => task.ref);
    sortTasksByPriority(tasks);
    expect(tasks.map((task) => task.ref)).toEqual(refs);
  });
});
