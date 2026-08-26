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

export function buildNoteSheets(
  findings: BoardNote[],
  risks: BoardNote[],
  links: BoardNote[],
): NoteSheet[] {
  const sheets: NoteSheet[] = [];
  for (const group of grouped(findings)) {
    sheets.push({
      id: `finding:${group.category}`,
      kind: "finding",
      category: group.category,
      label: group.category,
      notes: group.notes,
    });
  }
  for (const group of grouped(risks)) {
    sheets.push({
      id: `risk:${group.category}`,
      kind: "risk",
      category: group.category,
      label: `风险 · ${group.category}`,
      notes: group.notes,
    });
  }
  for (const group of grouped(links)) {
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
