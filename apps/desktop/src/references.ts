export type BoardReferenceKind = "task" | "note";

export interface BoardReference {
  kind: BoardReferenceKind;
  id: number;
}

export interface BoardReferenceRequest extends BoardReference {
  token: number;
}

export type BoardReferencePart =
  | { kind: "text"; text: string }
  | { kind: "reference"; text: string; reference: BoardReference };

export function boardReferenceParts(value: string): BoardReferencePart[] {
  const parts: BoardReferencePart[] = [];
  const pattern = /#(\d+)|\[(\d+)\]/g;
  let cursor = 0;

  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push({ kind: "text", text: value.slice(cursor, index) });

    const taskId = match[1] ? Number.parseInt(match[1], 10) : null;
    const noteId = match[2] ? Number.parseInt(match[2], 10) : null;
    const reference = taskId !== null
      ? { kind: "task" as const, id: taskId }
      : { kind: "note" as const, id: noteId ?? 0 };
    parts.push({ kind: "reference", text: match[0], reference });
    cursor = index + match[0].length;
  }

  if (cursor < value.length) parts.push({ kind: "text", text: value.slice(cursor) });
  return parts.length ? parts : [{ kind: "text", text: value }];
}
