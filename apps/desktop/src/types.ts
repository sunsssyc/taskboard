export type TaskStatus = "todo" | "active" | "waiting" | "done" | "dropped";
export type TaskOwner = "" | "你" | "我" | "双方";

export interface Repository {
  id?: number;
  name: string;
  path: string | null;
}

export interface TaskCounts {
  todo: number;
  active: number;
  waiting: number;
  done: number;
  dropped: number;
}

export interface BoardTask {
  ref: number;
  title: string;
  detail: string | null;
  accept: string | null;
  status: TaskStatus;
  owner: string | null;
  gate: boolean;
  branch: string | null;
  pr: string | null;
  repositories: Repository[];
  blocked_by: number[];
  open_blockers: number[];
  blocks: number[];
  actionable: boolean;
  created_at: string;
  first_started_at: string | null;
  updated_at: string;
}

export type NoteKind = "finding" | "risk" | "link";

export interface BoardNote {
  id: number;
  project: string;
  kind: NoteKind;
  category: string | null;
  title: string;
  body: string | null;
  metric: string | null;
  created_at: string;
  superseded_by: number | null;
  superseded_at: string | null;
  supersedes: number[];
  is_superseded: boolean;
}

export interface BoardProject {
  key: string;
  name: string;
  repo: string | null;
  repositories: Repository[];
  summary: string | null;
  artifact_url: string | null;
  archived: boolean;
  counts: TaskCounts;
  waiting: number[];
  gates: number[];
  tasks: BoardTask[];
  findings: BoardNote[];
  risks: BoardNote[];
  links: BoardNote[];
  updated_at: string;
}

export interface BoardSnapshot {
  generated_at: string;
  db: string | null;
  projects: BoardProject[];
}

export interface ViewPrefs {
  order: string[];
  pinned: string[];
}

export interface BoardLoadResponse {
  snapshot: BoardSnapshot;
  source: string;
  viewPrefs: ViewPrefs;
}
