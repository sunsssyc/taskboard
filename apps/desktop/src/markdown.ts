export type InlinePart = { kind: "text" | "strong" | "code"; text: string };
export type TableAlignment = "left" | "center" | "right";
export type MarkdownLineBlock = {
  kind: "blank" | "heading" | "bullet" | "number" | "quote" | "paragraph";
  marker?: string;
  parts: InlinePart[];
};
export type MarkdownTableBlock = {
  kind: "table";
  header: InlinePart[][];
  rows: InlinePart[][][];
  alignments: TableAlignment[];
};
export type MarkdownBlock = MarkdownLineBlock | MarkdownTableBlock;

export function inlineParts(value: string): InlinePart[] {
  const parts: InlinePart[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let cursor = 0;
  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push({ kind: "text", text: value.slice(cursor, index) });
    const token = match[0];
    if (token.startsWith("`")) {
      parts.push({ kind: "code", text: token.slice(1, -1) });
    } else {
      parts.push({ kind: "strong", text: token.slice(2, -2) });
    }
    cursor = index + token.length;
  }
  if (cursor < value.length) parts.push({ kind: "text", text: value.slice(cursor) });
  return parts.length ? parts : [{ kind: "text", text: value }];
}

function parseLine(line: string): MarkdownLineBlock {
  if (!line.trim()) return { kind: "blank", parts: [] };
  const heading = line.match(/^#{1,4}\s+(.+)$/);
  if (heading) return { kind: "heading", parts: inlineParts(heading[1]) };
  const bullet = line.match(/^\s*[-*]\s+(.+)$/);
  if (bullet) return { kind: "bullet", marker: "•", parts: inlineParts(bullet[1]) };
  const number = line.match(/^\s*(\d+[.)])\s+(.+)$/);
  if (number) return { kind: "number", marker: number[1], parts: inlineParts(number[2]) };
  const quote = line.match(/^>\s?(.+)$/);
  if (quote) return { kind: "quote", parts: inlineParts(quote[1]) };
  return { kind: "paragraph", parts: inlineParts(line) };
}

function splitTableRow(line: string): string[] | null {
  let value = line.trim();
  if (!value.includes("|")) return null;
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|")) value = value.slice(0, -1);

  const cells: string[] = [];
  let cell = "";
  let inCode = false;
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (character === "\\" && value[index + 1] === "|") {
      cell += "|";
      index += 1;
    } else if (character === "`") {
      inCode = !inCode;
      cell += character;
    } else if (character === "|" && !inCode) {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += character;
    }
  }
  cells.push(cell.trim());
  return cells.length >= 2 ? cells : null;
}

function parseAlignments(line: string, columnCount: number): TableAlignment[] | null {
  const cells = splitTableRow(line);
  if (!cells || cells.length !== columnCount) return null;
  if (!cells.every((cell) => /^:?-{3,}:?$/.test(cell.replaceAll(" ", "")))) return null;
  return cells.map((cell) => {
    const marker = cell.replaceAll(" ", "");
    if (marker.startsWith(":") && marker.endsWith(":")) return "center";
    if (marker.endsWith(":")) return "right";
    return "left";
  });
}

function normalizeCells(cells: string[], columnCount: number): InlinePart[][] {
  return Array.from({ length: columnCount }, (_, index) => inlineParts(cells[index] ?? ""));
}

export function parseMarkdownBlocks(text: string): MarkdownBlock[] {
  const lines = text.split("\n");
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const headerCells = splitTableRow(lines[index]);
    const alignments = headerCells
      ? parseAlignments(lines[index + 1] ?? "", headerCells.length)
      : null;
    if (headerCells && alignments) {
      const rows: InlinePart[][][] = [];
      index += 2;
      while (index < lines.length) {
        const rowCells = splitTableRow(lines[index]);
        if (!rowCells || !lines[index].trim()) break;
        rows.push(normalizeCells(rowCells, headerCells.length));
        index += 1;
      }
      blocks.push({
        kind: "table",
        header: normalizeCells(headerCells, headerCells.length),
        rows,
        alignments,
      });
      continue;
    }

    blocks.push(parseLine(lines[index]));
    index += 1;
  }
  return blocks;
}
