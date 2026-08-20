"""SQLite 存储层:项目、任务、依赖、结论/风险、事件流。

单库跨项目:默认 ~/.taskboard/board.db(可用 TASKBOARD_HOME 改),每个项目一条
记录、任务在项目内自增编号(ref),CLI 与渲染器都只经由本层读写。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# waiting = 卡在人工/外部动作上(服务器执行、页面操作、等发版),我推不动;
# 与"被依赖阻塞"是两回事,前者等的是人,后者等的是别的任务。
STATUSES = ('todo', 'active', 'waiting', 'done', 'dropped')
OPEN_STATUSES = ('todo', 'active', 'waiting')
ACTIONABLE_STATUSES = ('todo', 'active')
NOTE_KINDS = ('finding', 'risk', 'link')
DEFAULT_STALE_DAYS = 3
MARKDOWN_CODE_RE = re.compile(r'```.*?```|`[^`\n]*`', re.DOTALL)
LITERAL_PARAGRAPH_BREAK_RE = re.compile(r'(?<!\\)\\n(?<!\\)\\n')


def validate_markdown_newlines(*values: str | None) -> None:
    """拒绝正文里的字面量 ``\\n\\n``，代码片段中的展示用法除外。"""
    for value in values:
        if not value:
            continue
        prose = MARKDOWN_CODE_RE.sub('', value)
        if LITERAL_PARAGRAPH_BREAK_RE.search(prose):
            raise BoardError(
                r"检测到字面量 \n\n；请传真实换行。bash/zsh 示例: "
                r"--detail $'第一段\n\n第二段'。若要展示转义符,请放进行内代码 `\n\n`。"
            )


def home_dir() -> Path:
    return Path(os.environ.get('TASKBOARD_HOME') or (Path.home() / '.taskboard'))


def default_db() -> Path:
    return home_dir() / 'board.db'


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    key          TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    repo         TEXT,
    summary      TEXT,
    artifact_url TEXT,
    archived     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT NOT NULL REFERENCES projects(key) ON DELETE CASCADE,
    ref         INTEGER NOT NULL,
    title       TEXT NOT NULL,
    detail      TEXT,
    accept      TEXT,
    status      TEXT NOT NULL DEFAULT 'todo',
    owner       TEXT,
    gate        INTEGER NOT NULL DEFAULT 0,
    branch      TEXT,
    pr          TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (project, ref)
);
CREATE TABLE IF NOT EXISTS deps (
    task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    blocked_by_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, blocked_by_id)
);
CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT NOT NULL REFERENCES projects(key) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    category    TEXT,
    title       TEXT NOT NULL,
    body        TEXT,
    metric      TEXT,
    created_at  TEXT NOT NULL
);
-- superseded_by:被哪条记录推翻(NULL=当前有效)。旧结论不删除,保留
-- "曾经这么认为、被什么推翻"这条信息,防止在同一问题上反复改判。
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT,
    task_ref    INTEGER,
    action      TEXT NOT NULL,
    payload     TEXT,
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project, ref);
CREATE INDEX IF NOT EXISTS idx_notes_project ON notes(project, kind);
CREATE INDEX IF NOT EXISTS idx_events_at ON events(at DESC);
"""


class BoardError(Exception):
    """面向用户的错误:CLI 直接打印 message,不带堆栈。"""


class Store:
    def __init__(self, db_path: str | Path | None = None):
        self.path = Path(db_path) if db_path else default_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys = ON')
        # WAL:读不挡写、写不挡读,多个 CLI 进程与 serve 并存时不会互相卡死;
        # busy_timeout:抢锁时等待而不是立刻抛 database is locked
        self.conn.execute('PRAGMA journal_mode = WAL')
        self.conn.execute('PRAGMA busy_timeout = 5000')
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _add_columns(self, table: str, columns: dict[str, str]) -> None:
        existing = {row['name'] for row in self.conn.execute(f'PRAGMA table_info({table})')}
        for name, decl in columns.items():
            if name not in existing:
                self.conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')

    def _migrate(self) -> None:
        """就地补列:老库直接用新版本打开即可,不需要单独的迁移命令。"""
        self._add_columns('notes', {
            'category': 'TEXT', 'superseded_by': 'INTEGER', 'superseded_at': 'TEXT',
        })
        self._add_columns('tasks', {'accept': 'TEXT', 'branch': 'TEXT', 'pr': 'TEXT'})
        self._add_columns('projects', {'artifact_url': 'TEXT'})

    def close(self) -> None:
        self.conn.close()

    # ── 事件流 ──────────────────────────────────────────────────────────
    def log_event(self, action: str, project: str | None = None,
                  task_ref: int | None = None, **payload) -> None:
        self.conn.execute(
            'INSERT INTO events (project, task_ref, action, payload, at) VALUES (?,?,?,?,?)',
            (project, task_ref, action, json.dumps(payload, ensure_ascii=False) or None, now_iso()),
        )

    def events(self, limit: int = 30, project: str | None = None) -> list[sqlite3.Row]:
        sql = 'SELECT * FROM events'
        args: list = []
        if project:
            sql += ' WHERE project = ?'
            args.append(project)
        sql += ' ORDER BY id DESC LIMIT ?'
        args.append(limit)
        return list(self.conn.execute(sql, args))

    # ── 项目 ────────────────────────────────────────────────────────────
    def create_project(self, key: str, name: str, repo: str | None = None,
                       summary: str | None = None) -> sqlite3.Row:
        if self.find_project(key):
            raise BoardError(f'项目已存在: {key}')
        stamp = now_iso()
        self.conn.execute(
            'INSERT INTO projects (key, name, repo, summary, created_at, updated_at)'
            ' VALUES (?,?,?,?,?,?)',
            (key, name, str(Path(repo).resolve()) if repo else None, summary, stamp, stamp),
        )
        self.log_event('project_created', project=key, name=name)
        self.conn.commit()
        return self.get_project(key)

    def find_project(self, key: str) -> sqlite3.Row | None:
        return self.conn.execute('SELECT * FROM projects WHERE key = ?', (key,)).fetchone()

    def get_project(self, key: str) -> sqlite3.Row:
        row = self.find_project(key)
        if row is None:
            raise BoardError(f'没有这个项目: {key}(先 board init {key})')
        return row

    def projects(self, include_archived: bool = False) -> list[sqlite3.Row]:
        sql = 'SELECT * FROM projects'
        if not include_archived:
            sql += ' WHERE archived = 0'
        sql += ' ORDER BY archived, key'
        return list(self.conn.execute(sql))

    def update_project(self, key: str, **fields) -> sqlite3.Row:
        project = self.get_project(key)
        allowed = {'name', 'repo', 'summary', 'archived', 'artifact_url'}
        sets, args = [], []
        for field, value in fields.items():
            if field not in allowed or value is None:
                continue
            if field == 'repo':
                value = str(Path(value).resolve())
            sets.append(f'{field} = ?')
            args.append(int(value) if field == 'archived' else value)
        if sets:
            sets.append('updated_at = ?')
            args.extend([now_iso(), key])
            self.conn.execute(f'UPDATE projects SET {", ".join(sets)} WHERE key = ?', args)
            self.log_event('project_updated', project=key, fields=sorted(fields))
            self.conn.commit()
        return self.get_project(project['key'])

    def project_for_path(self, path: str | Path) -> sqlite3.Row | None:
        """按 cwd 归属判定当前项目:取路径最长(最具体)的匹配项目。"""
        target = Path(path).resolve()
        best = None
        for project in self.projects(include_archived=True):
            repo = project['repo']
            if not repo:
                continue
            repo_path = Path(repo)
            if target == repo_path or repo_path in target.parents:
                if best is None or len(repo) > len(best['repo']):
                    best = project
        return best

    # ── 任务 ────────────────────────────────────────────────────────────
    def add_task(self, project: str, title: str, detail: str | None = None,
                 owner: str | None = None, gate: bool = False,
                 blocked_by: list[int] | None = None, accept: str | None = None,
                 branch: str | None = None, pr: str | None = None) -> sqlite3.Row:
        self.get_project(project)
        # ref 是"读 MAX+1 再插":必须在写锁下完成,否则两个进程会算出同一个号。
        # BEGIN IMMEDIATE 在读之前就拿写锁,配合 UNIQUE(project, ref) 双保险。
        in_transaction = self.conn.in_transaction
        if not in_transaction:
            self.conn.execute('BEGIN IMMEDIATE')
        try:
            next_ref = (self.conn.execute(
                'SELECT COALESCE(MAX(ref), 0) + 1 FROM tasks WHERE project = ?', (project,),
            ).fetchone()[0])
            stamp = now_iso()
            cursor = self.conn.execute(
                'INSERT INTO tasks (project, ref, title, detail, accept, status, owner, gate,'
                ' branch, pr, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (project, next_ref, title, detail, accept, 'todo', owner, int(bool(gate)),
                 branch, pr, stamp, stamp),
            )
            task_id = cursor.lastrowid
            for blocker_ref in blocked_by or []:
                self._add_dep(task_id, self.get_task(project, blocker_ref)['id'])
            self.log_event('task_added', project=project, task_ref=next_ref, title=title)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.get_task(project, next_ref)

    def get_task(self, project: str, ref: int) -> sqlite3.Row:
        row = self.conn.execute(
            'SELECT * FROM tasks WHERE project = ? AND ref = ?', (project, ref),
        ).fetchone()
        if row is None:
            raise BoardError(f'{project} 里没有任务 #{ref}')
        return row

    def tasks(self, project: str, include_dropped: bool = True) -> list[sqlite3.Row]:
        sql = 'SELECT * FROM tasks WHERE project = ?'
        if not include_dropped:
            sql += " AND status != 'dropped'"
        sql += ' ORDER BY ref'
        return list(self.conn.execute(sql, (project,)))

    def set_status(self, project: str, ref: int, status: str,
                   commit_sha: str | None = None) -> sqlite3.Row:
        if status not in STATUSES:
            raise BoardError(f'状态只能是 {"/".join(STATUSES)},收到 {status}')
        task = self.get_task(project, ref)
        self.conn.execute(
            'UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?',
            (status, now_iso(), task['id']),
        )
        payload = {'old': task['status'], 'new': status}
        if commit_sha:
            # 记在事件流里而不是任务上:squash/rebase 会让任务字段里的 sha 失效,
            # 事件流至少留下"完成时 HEAD 在哪"这个事实
            payload['commit'] = commit_sha
        self.log_event('status_changed', project=project, task_ref=ref, **payload)
        self.conn.commit()
        return self.get_task(project, ref)

    def update_task(self, project: str, ref: int, **fields) -> sqlite3.Row:
        task = self.get_task(project, ref)
        allowed = {'title', 'detail', 'owner', 'gate', 'accept', 'branch', 'pr'}
        sets, args = [], []
        for field, value in fields.items():
            if field not in allowed or value is None:
                continue
            sets.append(f'{field} = ?')
            args.append(int(bool(value)) if field == 'gate' else value)
        if sets:
            sets.append('updated_at = ?')
            args.extend([now_iso(), task['id']])
            self.conn.execute(f'UPDATE tasks SET {", ".join(sets)} WHERE id = ?', args)
            self.log_event('task_updated', project=project, task_ref=ref, fields=sorted(fields))
            self.conn.commit()
        return self.get_task(project, ref)

    def delete_task(self, project: str, ref: int) -> None:
        task = self.get_task(project, ref)
        self.conn.execute('DELETE FROM tasks WHERE id = ?', (task['id'],))
        self.log_event('task_deleted', project=project, task_ref=ref, title=task['title'])
        self.conn.commit()

    # ── 依赖 ────────────────────────────────────────────────────────────
    def _add_dep(self, task_id: int, blocker_id: int) -> None:
        if task_id == blocker_id:
            raise BoardError('任务不能阻塞自己')
        if self._reaches(blocker_id, task_id):
            raise BoardError('会形成依赖环,已拒绝')
        self.conn.execute(
            'INSERT OR IGNORE INTO deps (task_id, blocked_by_id) VALUES (?,?)',
            (task_id, blocker_id),
        )

    def _reaches(self, start_id: int, target_id: int) -> bool:
        """start 的阻塞链上是否能走到 target(用于建边前的成环检查)。"""
        seen, stack = set(), [start_id]
        while stack:
            current = stack.pop()
            if current == target_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(
                row['blocked_by_id'] for row in
                self.conn.execute('SELECT blocked_by_id FROM deps WHERE task_id = ?', (current,))
            )
        return False

    def add_dep(self, project: str, ref: int, blocker_ref: int) -> None:
        task = self.get_task(project, ref)
        blocker = self.get_task(project, blocker_ref)
        self._add_dep(task['id'], blocker['id'])
        self.log_event('dep_added', project=project, task_ref=ref, blocked_by=blocker_ref)
        self.conn.commit()

    def remove_dep(self, project: str, ref: int, blocker_ref: int) -> None:
        task = self.get_task(project, ref)
        blocker = self.get_task(project, blocker_ref)
        self.conn.execute(
            'DELETE FROM deps WHERE task_id = ? AND blocked_by_id = ?',
            (task['id'], blocker['id']),
        )
        self.log_event('dep_removed', project=project, task_ref=ref, blocked_by=blocker_ref)
        self.conn.commit()

    def dep_map(self, project: str) -> dict[int, list[int]]:
        """{任务 ref: [阻塞它的 ref, ...]},按 ref 升序。"""
        rows = self.conn.execute(
            'SELECT t.ref AS ref, b.ref AS blocker FROM deps d'
            ' JOIN tasks t ON t.id = d.task_id'
            ' JOIN tasks b ON b.id = d.blocked_by_id'
            ' WHERE t.project = ? ORDER BY t.ref, b.ref',
            (project,),
        )
        result: dict[int, list[int]] = {}
        for row in rows:
            result.setdefault(row['ref'], []).append(row['blocker'])
        return result

    # ── 结论 / 风险 ─────────────────────────────────────────────────────
    def add_note(self, project: str, kind: str, title: str,
                 body: str | None = None, metric: str | None = None,
                 supersedes: list[int] | None = None,
                 category: str | None = None) -> sqlite3.Row:
        self.get_project(project)
        if kind not in NOTE_KINDS:
            raise BoardError(f'类型只能是 {"/".join(NOTE_KINDS)},收到 {kind}')
        category = self._normalize_category(category)
        # 先校验待推翻的记录,避免建了新记录才发现引用有误
        targets = [self.get_note(note_id) for note_id in supersedes or []]
        for target in targets:
            if target['project'] != project:
                raise BoardError(f'记录 {target["id"]} 属于项目 {target["project"]},不能跨项目推翻')
        cursor = self.conn.execute(
            'INSERT INTO notes (project, kind, category, title, body, metric, created_at)'
            ' VALUES (?,?,?,?,?,?,?)',
            (project, kind, category, title, body, metric, now_iso()),
        )
        note_id = cursor.lastrowid
        self.log_event('note_added', project=project, kind=kind, title=title,
                       category=category)
        for target in targets:
            self._supersede(target, note_id)
        self.conn.commit()
        return self.get_note(note_id)

    def get_note(self, note_id: int) -> sqlite3.Row:
        row = self.conn.execute('SELECT * FROM notes WHERE id = ?', (note_id,)).fetchone()
        if row is None:
            raise BoardError(f'没有这条记录: {note_id}')
        return row

    @staticmethod
    def _normalize_category(category: str | None) -> str | None:
        if category is None:
            return None
        if not isinstance(category, str):
            raise BoardError('category 必须是文本')
        value = category.strip()
        if not value:
            return None
        if '\n' in value or '\r' in value:
            raise BoardError('分类必须保持单行')
        if len(value) > 40:
            raise BoardError('分类不能超过 40 个字符')
        return value

    def set_note_category(self, note_id: int, category: str | None) -> sqlite3.Row:
        """给已有记录归类；空字符串用于移回“未分类”。"""
        note = self.get_note(note_id)
        category = self._normalize_category(category)
        self.conn.execute('UPDATE notes SET category = ? WHERE id = ?', (category, note_id))
        self.log_event('note_category_changed', project=note['project'], note_id=note_id,
                       old=note['category'], new=category)
        self.conn.commit()
        return self.get_note(note_id)

    def _supersede(self, target: sqlite3.Row, by_note_id: int) -> None:
        if target['id'] == by_note_id:
            raise BoardError('记录不能推翻自己')
        if target['superseded_by'] is not None:
            raise BoardError(
                f'记录 {target["id"]} 已被 {target["superseded_by"]} 推翻,'
                f'请改推翻最新那条'
            )
        self.conn.execute(
            'UPDATE notes SET superseded_by = ?, superseded_at = ? WHERE id = ?',
            (by_note_id, now_iso(), target['id']),
        )
        self.log_event('note_superseded', project=target['project'],
                       note_id=target['id'], by=by_note_id, title=target['title'])

    def supersede_note(self, note_id: int, by_note_id: int) -> sqlite3.Row:
        """把已有的两条记录连成"新推翻旧"(用于事后补关系)。"""
        target = self.get_note(note_id)
        replacement = self.get_note(by_note_id)
        if target['project'] != replacement['project']:
            raise BoardError('两条记录不在同一项目,不能建立推翻关系')
        self._supersede(target, replacement['id'])
        self.conn.commit()
        return self.get_note(note_id)

    def restore_note(self, note_id: int) -> sqlite3.Row:
        """撤销推翻标记(误标时用)。"""
        target = self.get_note(note_id)
        if target['superseded_by'] is None:
            raise BoardError(f'记录 {note_id} 本来就是有效的')
        self.conn.execute(
            'UPDATE notes SET superseded_by = NULL, superseded_at = NULL WHERE id = ?',
            (note_id,),
        )
        self.log_event('note_restored', project=target['project'], note_id=note_id)
        self.conn.commit()
        return self.get_note(note_id)

    def notes(self, project: str, kind: str | None = None,
              include_superseded: bool = True) -> list[sqlite3.Row]:
        sql = 'SELECT * FROM notes WHERE project = ?'
        args: list = [project]
        if kind:
            sql += ' AND kind = ?'
            args.append(kind)
        if not include_superseded:
            sql += ' AND superseded_by IS NULL'
        sql += ' ORDER BY id'
        return list(self.conn.execute(sql, args))

    def delete_note(self, note_id: int) -> None:
        row = self.get_note(note_id)
        # 被删的那条可能正推翻着别人:先把指向它的标记清掉,否则旧结论会永远
        # 停在"已被某条不存在的记录推翻"
        self.conn.execute(
            'UPDATE notes SET superseded_by = NULL, superseded_at = NULL WHERE superseded_by = ?',
            (note_id,),
        )
        self.conn.execute('DELETE FROM notes WHERE id = ?', (note_id,))
        self.log_event('note_deleted', project=row['project'], title=row['title'])
        self.conn.commit()

    # ── 派生视图 ────────────────────────────────────────────────────────
    def _note_dicts(self, project: str, kind: str) -> list[dict]:
        """带上推翻关系:superseded_by(被谁推翻)与 supersedes(推翻了谁)。

        有效记录在前、被推翻的沉底,让读的人先看到当前结论。
        """
        rows = [dict(row) for row in self.notes(project, kind)]
        overturned: dict[int, list[int]] = {}
        for row in rows:
            if row['superseded_by'] is not None:
                overturned.setdefault(row['superseded_by'], []).append(row['id'])
        for row in rows:
            row['supersedes'] = sorted(overturned.get(row['id'], []))
            row['is_superseded'] = row['superseded_by'] is not None
        return sorted(rows, key=lambda row: (row['is_superseded'], row['id']))

    @staticmethod
    def _order_by_dependency(tasks: list[dict]) -> list[dict]:
        """按依赖拓扑排序,让列表读起来就是执行顺序。

        创建号只反映"什么时候想到的",后补的前置任务会排在被它阻塞的任务后面。
        这里让每个任务排在其全部前置之后,同层按创建号稳定排序;成环时把剩余
        任务按创建号原样收尾,不丢任务。
        """
        by_ref = {task['ref']: task for task in tasks}
        pending = sorted(by_ref)
        emitted: list[dict] = []
        emitted_refs: set[int] = set()
        while pending:
            ready = [
                ref for ref in pending
                if all(dep not in by_ref or dep in emitted_refs
                       for dep in by_ref[ref]['blocked_by'])
            ]
            if not ready:  # 成环:剩余按创建号收尾
                ready = pending
            for ref in ready:
                emitted.append(by_ref[ref])
                emitted_refs.add(ref)
            pending = [ref for ref in pending if ref not in emitted_refs]
        return emitted

    def snapshot(self, include_archived: bool = False) -> dict:
        """渲染与 `board next` 共用的完整状态快照。"""
        data = {'generated_at': now_iso(), 'db': str(self.path), 'projects': []}
        for project in self.projects(include_archived=include_archived):
            key = project['key']
            deps = self.dep_map(key)
            tasks = []
            done_refs = {
                task['ref'] for task in self.tasks(key) if task['status'] == 'done'
            }
            for task in self.tasks(key):
                blockers = deps.get(task['ref'], [])
                open_blockers = [ref for ref in blockers if ref not in done_refs]
                tasks.append({
                    'ref': task['ref'],
                    'title': task['title'],
                    'detail': task['detail'],
                    'accept': task['accept'],
                    'status': task['status'],
                    'owner': task['owner'],
                    'gate': bool(task['gate']),
                    'branch': task['branch'],
                    'pr': task['pr'],
                    'blocked_by': blockers,
                    'open_blockers': open_blockers,
                    'blocks': sorted(
                        other for other, refs in deps.items() if task['ref'] in refs
                    ),
                    # waiting 卡在人工动作上,不算"能开工"——它要的是人不是我
                    'actionable': task['status'] in ACTIONABLE_STATUSES and not open_blockers,
                    'updated_at': task['updated_at'],
                })
            tasks = self._order_by_dependency(tasks)
            counts = {status: 0 for status in STATUSES}
            for task in tasks:
                counts[task['status']] += 1
            data['projects'].append({
                'key': key,
                'name': project['name'],
                'repo': project['repo'],
                'summary': project['summary'],
                'artifact_url': project['artifact_url'],
                'archived': bool(project['archived']),
                'counts': counts,
                'waiting': [t['ref'] for t in tasks if t['status'] == 'waiting'],
                'gates': [t['ref'] for t in tasks if t['gate'] and t['status'] != 'done'],
                'tasks': tasks,
                'findings': self._note_dicts(key, 'finding'),
                'risks': self._note_dicts(key, 'risk'),
                'links': self._note_dicts(key, 'link'),
                'updated_at': project['updated_at'],
            })
        return data

    # ── 检索 ────────────────────────────────────────────────────────────
    def search(self, keyword: str, project: str | None = None) -> dict:
        """在任务标题/正文/验收条件与记录标题/正文里找关键词,大小写不敏感。"""
        like = f'%{keyword.lower()}%'
        task_sql = (
            'SELECT * FROM tasks WHERE (LOWER(title) LIKE ? OR LOWER(COALESCE(detail, "")) LIKE ?'
            ' OR LOWER(COALESCE(accept, "")) LIKE ?)'
        )
        note_sql = (
            'SELECT * FROM notes WHERE (LOWER(title) LIKE ? OR LOWER(COALESCE(body, "")) LIKE ?)'
        )
        task_args: list = [like, like, like]
        note_args: list = [like, like]
        if project:
            task_sql += ' AND project = ?'
            note_sql += ' AND project = ?'
            task_args.append(project)
            note_args.append(project)
        task_sql += ' ORDER BY project, ref'
        note_sql += ' ORDER BY project, id'
        return {
            'tasks': [dict(row) for row in self.conn.execute(task_sql, task_args)],
            'notes': [dict(row) for row in self.conn.execute(note_sql, note_args)],
        }

    def stale_tasks(self, days: int = DEFAULT_STALE_DAYS,
                    project: str | None = None) -> list[dict]:
        """长时间没动静的在办任务:测真实停滞,不是想象中的计划延期。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec='seconds')
        sql = "SELECT * FROM tasks WHERE status IN ('active', 'waiting') AND updated_at < ?"
        args: list = [cutoff]
        if project:
            sql += ' AND project = ?'
            args.append(project)
        sql += ' ORDER BY updated_at'
        rows = []
        for row in self.conn.execute(sql, args):
            item = dict(row)
            try:
                idle = datetime.now(timezone.utc) - datetime.fromisoformat(item['updated_at'])
                item['idle_days'] = round(idle.total_seconds() / 86400, 1)
            except (TypeError, ValueError):
                item['idle_days'] = None
            rows.append(item)
        return rows
