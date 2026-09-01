import type { BoardNote, NoteKind } from "./types";

export interface NoteSheet {
  id: string;
  kind: NoteKind;
  category: string;
  label: string;
  notes: BoardNote[];
}

function grouped(notes: BoardNote[]): Array<{ category: string; notes: BoardNote[] }> {
  const groups = new Map<string, BoardNote[]>();
  for (const note of notes) {
    const category = note.category || "未分类";
    groups.set(category, [...(groups.get(category) ?? []), note]);
  }
  return [...groups.entries()].map(([category, items]) => ({ category, notes: items }));
}

/** 统计所有记录中已沉淀(且未被推翻)的条数。 */
export function countSettled(
  findings: BoardNote[],
  risks: BoardNote[],
  links: BoardNote[],
): number {
  return [...findings, ...risks, ...links]
    .filter((n) => n.is_settled && !n.is_superseded).length;
}

export function buildNoteSheets(
  findings: BoardNote[],
  risks: BoardNote[],
  links: BoardNote[],
  includeSettled = false,
): NoteSheet[] {
  const keep = (notes: BoardNote[]) =>
    includeSettled ? notes : notes.filter((n) => !n.is_settled);
  const sheets: NoteSheet[] = [];
  for (const group of grouped(keep(findings))) {
    sheets.push({
      id: `finding:${group.category}`,
      kind: "finding",
      category: group.category,
      label: group.category,
      notes: group.notes,
    });
  }
  for (const group of grouped(keep(risks))) {
    sheets.push({
      id: `risk:${group.category}`,
      kind: "risk",
      category: group.category,
      label: `风险 · ${group.category}`,
      notes: group.notes,
    });
  }
  for (const group of grouped(keep(links))) {
    sheets.push({
      id: `link:${group.category}`,
      kind: "link",
      category: group.category,
      label: `入口 · ${group.category}`,
      notes: group.notes,
    });
  }
  return sheets;
}
