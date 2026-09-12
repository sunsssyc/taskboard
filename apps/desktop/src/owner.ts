import type { TaskOwner } from "./types";

const OWNER_LABELS: Record<string, string> = {
  你: "用户",
  我: "Agent",
};

export const OWNER_OPTIONS: readonly { value: TaskOwner; label: string }[] = [
  { value: "你", label: "用户" },
  { value: "我", label: "Agent" },
  { value: "双方", label: "双方" },
  { value: "", label: "未分配" },
];

export function ownerLabel(owner: string): string {
  return OWNER_LABELS[owner] ?? owner;
}
