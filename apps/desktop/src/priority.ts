import type { BoardTask, TaskPriority } from "./types";

export const PRIORITY_OPTIONS: { value: TaskPriority; label: string; hint: string }[] = [
  { value: 0, label: "P0", hint: "紧急 / 硬阻塞" },
  { value: 1, label: "P1", hint: "本轮核心" },
  { value: 2, label: "P2", hint: "常规计划" },
  { value: 3, label: "P3", hint: "可延后" },
];

export function compareTaskPriority(left: BoardTask, right: BoardTask): number {
  if (left.priority !== right.priority) return left.priority - right.priority;
  const leftStatus = left.status === "active" ? 0 : 1;
  const rightStatus = right.status === "active" ? 0 : 1;
  return leftStatus - rightStatus || left.ref - right.ref;
}

export function sortTasksByPriority(tasks: BoardTask[]): BoardTask[] {
  return [...tasks].sort(compareTaskPriority);
}
