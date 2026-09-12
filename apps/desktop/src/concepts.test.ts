import { describe, expect, it } from "vitest";
import { demoSnapshot } from "./demo";
import { groupConcepts } from "./concepts";

describe("groupConcepts", () => {
  it("puts stale before proposed, then folds aligned and rejected", () => {
    const groups = groupConcepts(demoSnapshot.projects[0].concepts);
    expect(groups.pending.map((c) => [c.id, c.state])).toEqual([
      [327, "stale"],
      [330, "proposed"],
    ]);
    expect(groups.aligned.map((c) => c.id)).toEqual([24]);
    expect(groups.rejected.map((c) => c.id)).toEqual([12]);
  });

  it("handles an empty list", () => {
    expect(groupConcepts([])).toEqual({ pending: [], aligned: [], rejected: [] });
  });
});
