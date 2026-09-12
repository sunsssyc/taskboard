export type TaskStatus = "todo" | "active" | "waiting" | "done" | "dropped";
export type TaskOwner = "" | "你" | "我" | "双方";
export type TaskPriority = 0 | 1 | 2 | 3;
export type AgentProvider = "codex" | "claude";
export type AgentRunStatus = "submitted" | "opened" | "failed";

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

export interface AgentRun {
  id: number;
  task_id: number;
  provider: AgentProvider;
  dispatch_id: string;
  repository_path: string | null;
  external_thread_id: string | null;
  external_turn_id: string | null;
  status: AgentRunStatus;
  error: string | null;
  started_at: string;
  updated_at: string;
}

export interface AgentDispatchRequest {
  provider: AgentProvider;
  project: string;
  reference: number;
  title: string;
  detail: string | null;
  accept: string | null;
  repositoryPath: string;
}

export interface AgentDispatchResult {
  provider: AgentProvider;
  dispatchId: string;
  repositoryPath: string;
  status: AgentRunStatus;
  externalThreadId: string | null;
  externalTurnId: string | null;
  startedAt: string;
  warning: string | null;
}

export interface BoardTask {
  ref: number;
  title: string;
  detail: string | null;
  accept: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  owner: string | null;
  gate: boolean;
  branch: string | null;
  pr: string | null;
  repositories: Repository[];
  agent_runs: AgentRun[];
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

export type ConceptState = "proposed" | "aligned" | "stale" | "rejected";

export interface ConceptAnchor {
  repository: string;
  repository_path: string | null;
  path: string;
  symbol: string;
}

/** 概念卡:代码概念归仓库、跨需求共享;需求概念只归需求。状态由锚点提交现算。 */
export interface BoardConcept {
  id: number;
  project: string;
  category: string | null;
  title: string;
  body: string | null;
  repository: string | null;
  repository_path: string | null;
  task_ref: number | null;
  task_project: string | null;
  files: ConceptAnchor[];
  moved: string[];
  state: ConceptState;
  aligned_at: string | null;
  aligned_commit: string | null;
  rejected_at: string | null;
  created_at: string;
}

export interface ConceptEdit {
  title?: string;
  body?: string;
  keepAligned?: boolean;
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
  concepts: BoardConcept[];
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
  /** 只有 board serve 会明确给出;桌面端与演示模式视为可写。 */
  writeEnabled?: boolean;
}

/** board serve 注入到页面的上下文;不存在时说明不是网页模式。 */
export interface WebContext {
  csrf: string;
  writeEnabled: boolean;
  title: string;
  dev: boolean;
}
