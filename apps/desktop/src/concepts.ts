import type { BoardConcept, ConceptState } from "./types";

export const CONCEPT_STATE_LABEL: Record<ConceptState, string> = {
  proposed: "待对齐",
  stale: "需重新对齐",
  aligned: "已对齐",
  rejected: "已否决",
};

export interface ConceptGroups {
  /** 待对齐与需重新对齐:要人读的,默认展开;需重新对齐排前面——它只要重看变过的那处。 */
  pending: BoardConcept[];
  aligned: BoardConcept[];
  rejected: BoardConcept[];
}

export function groupConcepts(concepts: BoardConcept[]): ConceptGroups {
  const pending = concepts.filter((c) => c.state === "proposed" || c.state === "stale");
  pending.sort((left, right) => {
    if (left.state !== right.state) return left.state === "stale" ? -1 : 1;
    return left.id - right.id;
  });
  return {
    pending,
    aligned: concepts.filter((c) => c.state === "aligned").sort((a, b) => b.id - a.id),
    rejected: concepts.filter((c) => c.state === "rejected").sort((a, b) => b.id - a.id),
  };
}
