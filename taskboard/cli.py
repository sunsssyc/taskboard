"""board 命令行入口。

当前需求按 cwd 关联仓库自动判定,也可用 -p 显式指定或 `board use` 固定。
任务在需求内用 #ref 寻址；project 命名仅为兼容保留。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .gitref import (
    commits_between, diff_argv, diff_numstat, dirty_files, head_sha, untracked_files,
    worktree_for,
)
from .render import STATUS_LABEL, html_document, render, render_json
from .store import BoardError, Store, home_dir, load_view_prefs, validate_markdown_newlines

CURRENT_FILE = 'current'

DIM = '\033[2m'
BOLD = '\033[1m'
RESET = '\033[0m'
RED = '\033[31m'
CYAN = '\033[36m'
COLOR = {'done': '\033[32m', 'active': '\033[33m', 'todo': '\033[36m',
         'waiting': '\033[35m', 'dropped': '\033[2m'}
MARK = {'done': '✓', 'active': '▸', 'todo': '·', 'waiting': '⏸', 'dropped': '✗'}


def _tty() -> bool:
    return sys.stdout.isatty() and not os.environ.get('NO_COLOR')


def paint(text: str, code: str) -> str:
    return f'{code}{text}{RESET}' if _tty() else text


def _current_path() -> Path:
    return home_dir() / CURRENT_FILE


def resolve_project(store: Store, explicit: str | None) -> str:
    """优先级:-p 参数 > cwd 关联仓库 > board use 固定 > 唯一需求。"""
    if explicit:
        return store.get_project(explicit)['key']
    by_path = store.projects_for_path(Path.cwd())
    if len(by_path) == 1:
        return by_path[0]['key']
    if len(by_path) > 1:
        choices = ', '.join(project['key'] for project in by_path)
        raise BoardError(f'当前仓库关联多个需求({choices}),请用 -p <key> 明确选择')
    pinned = _current_path()
    if pinned.exists():
        key = pinned.read_text().strip()
        if key and store.find_project(key):
            return key
    projects = store.projects()
    if len(projects) == 1:
        return projects[0]['key']
    raise BoardError(
        '认不出当前需求:用 -p <key> 指定,或 board use <key> 固定,'
        '或在关联仓库目录里执行(需 board init --repo 登记过路径)'
    )


def _refs(value: str | None) -> list[int]:
    if not value:
        return []
    return [int(part) for part in str(value).replace(',', ' ').split()]


def _priority(value: str) -> int:
    normalized = value.strip().upper()
    if normalized.startswith('P'):
        normalized = normalized[1:]
    if normalized not in {'0', '1', '2', '3'}:
        raise argparse.ArgumentTypeError('优先级只能是 P0/P1/P2/P3（P0 最高）')
    return int(normalized)


# ── 输出 ────────────────────────────────────────────────────────────────

def print_task_line(task: dict, indent: str = '') -> None:
    mark = paint(MARK[task['status']], COLOR[task['status']])
    ref = paint(f'#{task["ref"]:<3}', BOLD if task['status'] == 'active' else DIM)
    bits = [f'P{task["priority"]}']
    if task['owner']:
        bits.append(f'@{task["owner"]}')
    if task['gate'] and task['status'] != 'done':
        bits.append(paint('闸门', RED))
    if task.get('branch'):
        bits.append(task['branch'])
    if task.get('pr'):
        bits.append(f'PR {task["pr"]}')
    if task.get('repositories'):
        bits.append('仓库 ' + ','.join(repository['name'] for repository in task['repositories']))
    if task['open_blockers']:
        bits.append(paint('阻塞于 #' + ',#'.join(str(r) for r in task['open_blockers']), DIM))
    elif task['status'] == 'waiting':
        bits.append(paint('等人工', '\033[35m'))
    elif task['status'] == 'todo':
        bits.append(paint('可开工', CYAN))
    suffix = f'  {paint(" · ".join(bits), DIM)}' if bits else ''
    print(f'{indent}{mark} {ref} {task["title"]}{suffix}')


def _priority_key(task: dict) -> tuple[int, int, int]:
    status_rank = 0 if task['status'] == 'active' else 1
    return task['priority'], status_rank, task['ref']


def cmd_init(store: Store, args) -> int:
    project = store.create_project(
        args.key, args.name or args.key, summary=args.summary,
        repositories=args.repo,
    )
    print(f'已建需求 {paint(project["key"], BOLD)} · {project["name"]}')
    for repository in store.project_repositories(project['key']):
        print(f'  仓库 {repository["name"]} · {repository["path"]}')
    return 0


def cmd_projects(store: Store, args) -> int:
    snapshot = store.snapshot(include_archived=args.all)
    if not snapshot['projects']:
        print('还没有需求。board init <key> --name "..." --repo .')
        return 0
    for project in snapshot['projects']:
        counts = project['counts']
        total = sum(counts.values())
        head = f'{paint(project["key"], BOLD)}  {project["name"]}'
        if project['archived']:
            head += paint('  [已归档]', DIM)
        print(head)
        if project['repositories']:
            print(paint(
                '  仓库 ' + ' · '.join(repository['name'] for repository in project['repositories']),
                DIM,
            ))
        print(paint(
            f'  完成 {counts["done"]}/{total} · 进行 {counts["active"]} · 待办 {counts["todo"]}'
            + (f' · 闸门 #{",#".join(str(g) for g in project["gates"])}' if project['gates'] else ''),
            DIM,
        ))
    return 0


def cmd_use(store: Store, args) -> int:
    key = store.get_project(args.key)['key']
    path = _current_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key)
    print(f'当前需求固定为 {paint(key, BOLD)}')
    return 0


def git_head_sha(cwd: Path | None = None) -> str | None:
    """cwd 所在仓库的短 sha。只用于没有关联仓库的任务;有关联仓库时由 Store 逐仓库取。"""
    return head_sha(cwd)


def print_task_commits(store: Store, project: str, ref: int, status: str) -> None:
    """打印刚记下的区间端点,让人当场看到记的是哪个仓库的哪个提交。"""
    for entry in store.task_commits(project, ref):
        if status == 'active' and entry['base_sha']:
            print(paint(f'  起点 {entry["name"]} {entry["base_sha"]}', DIM))
        elif status == 'done' and entry['head_sha']:
            span = (
                f'{entry["base_sha"]}..{entry["head_sha"]}' if entry['complete']
                else f'{entry["head_sha"]}(缺起点,区间不完整)'
            )
            print(paint(f'  区间 {entry["name"]} {span}', DIM))


def cmd_add(store: Store, args) -> int:
    validate_markdown_newlines(args.detail, args.accept)
    project = resolve_project(store, args.project)
    available_repositories = store.project_repositories(project)
    if args.repo is None and len(available_repositories) > 1:
        choices = ', '.join(repository['name'] for repository in available_repositories)
        raise BoardError(
            f'需求 {project} 涉及多个仓库({choices});请先和用户确认本任务范围,'
            '再用一个或多个 --repo 指定'
        )
    task = store.add_task(
        project, args.title, detail=args.detail, owner=args.owner,
        gate=args.gate, blocked_by=_refs(args.blocked_by),
        accept=args.accept, branch=args.branch, pr=args.pr,
        repositories=args.repo, priority=args.priority,
    )
    print(f'{project} #{task["ref"]} {task["title"]}')
    return 0


def cmd_ls(store: Store, args) -> int:
    if args.all_projects:
        snapshot = store.snapshot()
        for index, project in enumerate(snapshot['projects']):
            if index:
                print()
            print(f'{paint(project["key"], BOLD)} · {project["name"]}')
            for task in project['tasks']:
                if task['status'] == 'done' and not args.done:
                    continue
                if task['status'] == 'dropped' and not args.all:
                    continue
                print_task_line(task, indent='  ')
        return 0

    project = resolve_project(store, args.project)
    snapshot = store.snapshot(include_archived=True)
    data = next(p for p in snapshot['projects'] if p['key'] == project)
    counts = data['counts']
    print(f'{paint(data["key"], BOLD)} · {data["name"]}  '
          + paint(f'完成 {counts["done"]} / 进行 {counts["active"]} / 待办 {counts["todo"]}', DIM))
    for task in data['tasks']:
        if task['status'] == 'done' and not args.done:
            continue
        if task['status'] == 'dropped' and not args.all:
            continue
        print_task_line(task)
    if data['risks']:
        print(paint(f'\n尾巴 {len(data["risks"])} 条 · board notes 查看', DIM))
    return 0


def cmd_next(store: Store, args) -> int:
    snapshot = store.snapshot()
    projects = snapshot['projects']
    if args.project:
        projects = [p for p in projects if p['key'] == store.get_project(args.project)['key']]
    found = False
    for project in projects:
        ready = sorted(
            (t for t in project['tasks'] if t['actionable']), key=_priority_key,
        )
        if args.owner:
            ready = [t for t in ready if t['owner'] == args.owner]
        waiting = [t for t in project['tasks'] if t['status'] == 'waiting']
        if not ready and not (waiting and not args.owner):
            continue
        found = True
        print(f'{paint(project["key"], BOLD)} · {project["name"]}')
        for task in ready[:args.limit]:
            print_task_line(task, indent='  ')
        if waiting and not args.owner:
            print(paint('  等人工:', DIM))
            for task in waiting[:args.limit]:
                print_task_line(task, indent='  ')
    if not found:
        print('没有可开工的任务(要么都完成了,要么全被阻塞——board ls 看依赖)')
    return 0


def cmd_brief(store: Store, args) -> int:
    """交接摘要:新会话读这一段就能接上,不用翻对话历史。"""
    snapshot = store.snapshot()
    projects = snapshot['projects']
    if not args.all_projects:
        key = resolve_project(store, args.project)
        projects = [p for p in projects if p['key'] == key]

    for index, project in enumerate(projects):
        if index:
            print()
        counts = project['counts']
        print(f'# {project["name"]}({project["key"]})')
        if project['summary']:
            print(project['summary'])
        if project['repositories']:
            print('关联仓库:' + ' · '.join(repo['name'] for repo in project['repositories']))
        line = (f'进度 完成 {counts["done"]} / 进行 {counts["active"]} / '
                f'等人工 {counts["waiting"]} / 待办 {counts["todo"]}')
        if project['gates']:
            line += f' · 闸门 #{", #".join(str(g) for g in project["gates"])}'
        print(line)

        active = sorted(
            (t for t in project['tasks'] if t['status'] == 'active'), key=_priority_key,
        )
        ready = sorted(
            (t for t in project['tasks'] if t['actionable'] and t['status'] == 'todo'),
            key=_priority_key,
        )
        waiting = [t for t in project['tasks'] if t['status'] == 'waiting']
        for label, items in (('进行中', active), ('可开工', ready), ('等人工', waiting)):
            if not items:
                continue
            print(f'\n## {label}')
            for task in items[:args.limit]:
                owner = f'(@{task["owner"]})' if task['owner'] else ''
                repositories = (
                    ' [' + ' · '.join(repo['name'] for repo in task['repositories']) + ']'
                    if task['repositories'] else ''
                )
                print(f'- #{task["ref"]} {task["title"]}{owner}{repositories}')
                if task['detail'] and args.verbose:
                    print(f'  {task["detail"]}')

        findings = [f for f in project['findings'] if not f['is_superseded']]
        if findings:
            print('\n## 已定结论(不要重新推演)')
            for note in findings:
                metric = f' — {note["metric"]}' if note['metric'] else ''
                print(f'- [{note["id"]}] {note["title"]}{metric}')
        risks = [r for r in project['risks'] if not r['is_superseded']]
        if risks:
            print('\n## 尾巴')
            for note in risks:
                print(f'- [{note["id"]}] {note["title"]}')
        links = [link for link in project['links'] if not link['is_superseded']]
        if links:
            print('\n## 关键文件')
            for note in links:
                body = f' — {note["body"]}' if note['body'] else ''
                print(f'- {note["title"]}{body}')
        if project['artifact_url']:
            print(f'\n看板页面:{project["artifact_url"]}')
    return 0


def cmd_find(store: Store, args) -> int:
    project = None
    if not args.all_projects:
        try:
            project = resolve_project(store, args.project)
        except BoardError:
            project = None
    result = store.search(args.keyword, project=project)
    if result['tasks']:
        print(paint('任务', BOLD))
        for task in result['tasks']:
            print(f'  {task["project"]} #{task["ref"]} {task["title"]}'
                  f'  {paint(STATUS_LABEL[task["status"]], DIM)}')
    if result['notes']:
        print(paint('记录', BOLD))
        for note in result['notes']:
            flag = paint('(已推翻)', DIM) if note['superseded_by'] else ''
            print(f'  {note["project"]} [{note["id"]}] {NOTE_LABEL[note["kind"]]} '
                  f'{note["title"]}{flag}')
    if not result['tasks'] and not result['notes']:
        print(f'没找到含「{args.keyword}」的任务或记录')
    return 0


def cmd_stale(store: Store, args) -> int:
    project = None
    if not args.all_projects:
        try:
            project = resolve_project(store, args.project)
        except BoardError:
            project = None
    rows = store.stale_tasks(days=args.days, project=project)
    if not rows:
        print(f'没有停滞超过 {args.days} 天的在办任务')
        return 0
    print(paint(f'停滞超过 {args.days} 天:', BOLD))
    for task in rows:
        idle = f'{task["idle_days"]} 天没动' if task['idle_days'] is not None else '时间未知'
        print(f'  {task["project"]} #{task["ref"]} {task["title"]}  '
              f'{paint(STATUS_LABEL[task["status"]] + " · " + idle, DIM)}')
    return 0


def cmd_set(store: Store, args) -> int:
    key = resolve_project(store, args.project)
    project = store.update_project(
        key, name=args.name, summary=args.summary,
        artifact_url=args.artifact_url,
        archived=1 if args.archive else (0 if args.unarchive else None),
    )
    if args.repo is not None:
        store.set_project_repositories(key, args.repo)
        project = store.get_project(key)
    print(f'{paint(project["key"], BOLD)} · {project["name"]}')
    if project['artifact_url']:
        print(paint(f'  看板页面 {project["artifact_url"]}', DIM))
    repositories = store.project_repositories(key)
    if repositories:
        print(paint('  仓库 ' + ' · '.join(row['name'] for row in repositories), DIM))
    return 0


def cmd_repo_move(store: Store, args) -> int:
    result = store.move_repository(
        args.old, args.new, merge=args.merge, force=args.force,
    )
    repository = result['repository']
    verb = '的关联已并入' if result['merged'] else '已迁移为'
    print(f'仓库 {paint(result["previous_name"], BOLD)} {verb} '
          f'{paint(repository["name"], BOLD)} · {repository["path"]}')
    print(paint(f'  原路径 {result["previous_path"]}', DIM))
    projects = ' · '.join(result['projects']) or '(无)'
    print(paint(f'  跟随更新:需求 {projects},任务关联 {result["tasks"]} 条', DIM))
    for key in result['conflicts']:
        print(paint(
            f'  注意:需求 {key} 下现在有两个仓库都叫 {repository["name"]},'
            f'--repo 要传完整路径才不歧义', RED,
        ))
    return 0


def cmd_show(store: Store, args) -> int:
    project = resolve_project(store, args.project)
    snapshot = store.snapshot(include_archived=True)
    data = next(p for p in snapshot['projects'] if p['key'] == project)
    task = next((t for t in data['tasks'] if t['ref'] == args.ref), None)
    if task is None:
        raise BoardError(f'{project} 里没有任务 #{args.ref}')
    ref_label = paint('#{}'.format(task['ref']), BOLD)
    print(f'{ref_label} {task["title"]}')
    print(paint(f'  状态 {STATUS_LABEL[task["status"]]}'
                + f' · 优先级 P{task["priority"]}'
                + (f' · 负责 {task["owner"]}' if task['owner'] else '')
                + (' · 闸门' if task['gate'] else ''), DIM))
    if task['repositories']:
        print(paint(
            '  仓库 ' + ' · '.join(repository['name'] for repository in task['repositories']), DIM,
        ))
    if task['branch'] or task['pr']:
        bits = [b for b in (task['branch'], f'PR {task["pr"]}' if task['pr'] else None) if b]
        print(paint('  ' + ' · '.join(bits), DIM))
    for entry in store.task_commits(project, args.ref, verify=True):
        if not (entry['base_sha'] or entry['head_sha']):
            continue
        span = (
            f'{entry["base_sha"]}..{entry["head_sha"]}' if entry['complete']
            else f'{entry["base_sha"] or "?"}..{entry["head_sha"] or "?"}(区间不完整)'
        )
        if entry.get('missing'):
            span += '(' + '、'.join(entry['missing']) + ' 已不在仓库里)'
        print(paint(f'  改动 {entry["name"]} {span}', DIM))
    if task['detail']:
        print(f'\n{task["detail"]}')
    if task['accept']:
        print(paint(f'\n验收条件:{task["accept"]}', CYAN))
    if task['blocked_by']:
        print(paint(f'\n阻塞于 #{",#".join(str(r) for r in task["blocked_by"])}'
                    + (f'(未完成 #{",#".join(str(r) for r in task["open_blockers"])})'
                       if task['open_blockers'] else '(均已完成)'), DIM))
    if task['blocks']:
        print(paint(f'阻塞 → #{",#".join(str(r) for r in task["blocks"])}', DIM))
    print(paint(f'\n更新于 {task["updated_at"]}', DIM))
    return 0


def _effective_range(entry: dict, status: str,
                     committed_only: bool = False) -> tuple[str | None, str | None, bool, str]:
    """在办任务比到工作区,这样改到一半也能审;已完成任务用记录的两个端点。

    第四个返回值是该去哪个工作树看:在 worktree 里干活时,登记路径的工作区是别人的。
    """
    base, head = entry['base_sha'], entry['head_sha']
    tree = str(worktree_for(entry['path']))
    if base and not head and status == 'active' and not committed_only:
        live = head_sha(tree)
        if live:
            return base, live, True, tree
    return base, head, False, entry['path']


def _range_label(base: str | None, head: str | None, live: bool) -> str:
    if live:
        return f'{base}..工作区(含未提交)'
    if base and head:
        return f'{base}..{head}'
    return f'{base or "?"}..{head or "?"}(区间不完整)'


CONCEPT_STATE_LABEL = {
    'proposed': '待对齐', 'aligned': '已对齐', 'stale': '需重新对齐', 'rejected': '已否决',
}
CONCEPT_STATE_COLOR = {
    'proposed': CYAN, 'aligned': '\033[32m', 'stale': '\033[33m', 'rejected': DIM,
}


def print_concept(entry: dict, verbose: bool = False) -> None:
    state = paint(CONCEPT_STATE_LABEL[entry['state']], CONCEPT_STATE_COLOR[entry['state']])
    scope = entry['repository'] or f'{entry["project"]}(需求概念)'
    print(f'{paint("[" + str(entry["id"]) + "]", DIM)} {entry["title"]}  {state}'
          f'  {paint(scope, DIM)}')
    if verbose and entry['body']:
        print(f'    {entry["body"]}')
    if verbose and entry['files']:
        anchors = '、'.join(
            item['path'] + (f':{item["symbol"]}' if item['symbol'] else '')
            for item in entry['files']
        )
        print(paint(f'    锚点 {anchors}', DIM))
    if entry['state'] == 'stale':
        moved = '、'.join(entry['moved']) or '锚点'
        print(paint(f'    对齐于 {entry["aligned_commit"]},之后 {moved} 变过——只需重看这处',
                    DIM))


def cmd_concept(store: Store, args) -> int:
    validate_markdown_newlines(args.why)
    project = None
    if args.project:
        project = store.get_project(args.project)['key']
    repository = args.repo
    if not repository and args.file:
        # 只有代码锚点非要落在某个仓库里;方法论概念不该被逼着挑一个仓库
        candidates = store.project_repositories(project) if project else []
        if len(candidates) != 1:
            raise BoardError('传了 --file 且需求关联多个仓库,用 --repo 指明锚点在哪个仓库')
        repository = candidates[0]['path']
    entry = store.add_concept(
        repository, args.title, body=args.why, files=args.file,
        project=project, task_ref=args.task, category=args.category,
    )
    print_concept(entry, verbose=True)
    print(paint(f'  等人确认:board align {entry["id"]}', DIM))
    return 0


def cmd_concepts(store: Store, args) -> int:
    project = None if args.all_projects else resolve_project(store, args.project)
    entries = store.concepts(
        project=project, repository=args.repo, include_rejected=args.rejected,
    )
    if not entries:
        print('还没有概念。board concept "一句话" --why "为什么选它" --file path:symbol')
        return 0
    for state in ('proposed', 'stale', 'aligned', 'rejected'):
        group = [entry for entry in entries if entry['state'] == state]
        if not group:
            continue
        print(paint(f'{CONCEPT_STATE_LABEL[state]} {len(group)}', BOLD))
        for entry in group:
            print_concept(entry, verbose=args.verbose or state in ('proposed', 'stale'))
        print()
    return 0


def cmd_concept_edit(store: Store, args) -> int:
    validate_markdown_newlines(args.why)
    entry = store.update_concept(
        args.id, title=args.title, body=args.why, files=args.file,
        category=args.category, keep_aligned=args.keep_aligned,
    )
    print_concept(entry, verbose=True)
    if entry.get('alignment_reset'):
        print(paint('  措辞变了,已退回待对齐——你当初点头认的是旧那句话', DIM))
        print(paint(f'  确实只是改说法就:board align {entry["id"]}', DIM))
    return 0


def cmd_align(store: Store, args) -> int:
    if args.reject:
        entry = store.reject_concept(args.id, args.reject)
        print(f'已否决 [{entry["id"]}] {entry["title"]}')
        print(paint(f'  理由 {args.reject}', DIM))
        return 0
    entry = store.align_concept(args.id, note=args.note)
    print(f'已对齐 [{entry["id"]}] {entry["title"]}')
    print(paint(f'  锚在 {entry["repository"]} {entry["aligned_commit"]},'
                f'之后锚点文件动过会提示重新对齐', DIM))
    return 0


QUEUE_BUCKET = {
    'align': ('必须先对齐', RED),
    'read': ('精读', CYAN),
    'skim': ('可跳过', DIM),
}


def cmd_review_queue(store: Store, args) -> int:
    project = None if args.all_projects else resolve_project(store, args.project)
    entries = store.review_queue(project=project, since_days=args.since)
    if not entries:
        print(f'近 {args.since} 天没有带提交区间的改动')
        return 0
    worth = [entry for entry in entries if entry['bucket'] != 'skim'][:args.limit]
    skipped = [entry for entry in entries if entry not in worth]
    print(paint(f'该读的 {len(worth)} 条(近 {args.since} 天共 {len(entries)} 个任务有改动)',
                BOLD))
    for bucket in ('align', 'read'):
        group = [entry for entry in worth if entry['bucket'] == bucket]
        if not group:
            continue
        label, color = QUEUE_BUCKET[bucket]
        print(f'\n{paint(label, color)} {len(group)}')
        for entry in group:
            print(f'  #{entry["ref"]:<4}{entry["title"]}')
            print(paint(f'       {entry["reason"]}', DIM))
            print(paint(f'       {entry["files"]} 个文件 +{entry["added"]} −{entry["deleted"]}'
                        f'  ·  board review {entry["ref"]} -p {entry["project"]}', DIM))
    if skipped:
        # 全量列表本身就是过载的一部分,可跳过的折成一行
        refs = ' '.join(f'#{entry["ref"]}' for entry in skipped[:12])
        more = f' 等 {len(skipped)} 条' if len(skipped) > 12 else ''
        print(f'\n{paint("可跳过", DIM)} {refs}{more}')
    return 0


COMMIT_LIST_LIMIT = 10


def _print_commits(tree: str, name: str, base: str | None, head: str | None,
                   live: bool) -> None:
    """先按提交读:分段是 Agent 已经付过的成本,合并成一块 diff 等于把它扔掉。"""
    commits = commits_between(tree, base, head)
    if commits is None:
        return
    if not commits:
        if live:
            print(paint(f'\n提交 {name} 0 个 — 改动都还没提交,先提交再审更省事', DIM))
        return
    print(f'\n{paint("提交", BOLD)} {name} {base}..{head}  {len(commits)} 个')
    for commit in commits[:COMMIT_LIST_LIMIT]:
        size = '合并' if commit['merge'] else f'+{commit["added"]} −{commit["deleted"]}'
        print(f'  {commit["sha"]:<10}{size:<14}{commit["subject"]}')
    if len(commits) > COMMIT_LIST_LIMIT:
        print(paint(f'  还有 {len(commits) - COMMIT_LIST_LIMIT} 个提交', DIM))


def cmd_review(store: Store, args) -> int:
    if args.queue:
        return cmd_review_queue(store, args)
    if args.ref is None:
        raise BoardError('要么给任务号看审查包,要么加 --queue 看今天该读什么')
    project = resolve_project(store, args.project)
    task = store.get_task(project, args.ref)
    ranges = store.task_commits(project, args.ref, verify=True)
    if args.diff:
        shown = 0
        for entry in ranges:
            base, head, live, tree = _effective_range(entry, task['status'], args.committed)
            if not (base and head) or entry.get('missing'):
                continue
            subprocess.run(
                ['git', '-C', tree, 'diff', *diff_argv(base, head, live)], check=False,
            )
            shown += 1
        if not shown:
            raise BoardError('没有可用区间,无法出 diff;先看 board review 的说明')
        return 0

    print(f'{paint("#" + str(task["ref"]), BOLD)} {task["title"]}')
    meta = [STATUS_LABEL[task['status']], f'P{task["priority"]}']
    if task['owner']:
        meta.append(f'@{task["owner"]}')
    print(paint('  ' + ' · '.join(meta), DIM))
    if task['accept']:
        print(paint(f'  验收 {task["accept"]}', CYAN))
    if task['detail']:
        print(f'\n{paint("为什么做", BOLD)}\n{task["detail"]}')

    if not ranges:
        print(paint('\n无区间记录:任务没有关联仓库,或在提交区间功能上线前就完成了', DIM))
        return 0

    changed_paths: list[str] = []
    starts = [entry['base_at'] for entry in ranges if entry['base_at']]
    ends = [entry['head_at'] for entry in ranges if entry['head_at']]
    for entry in ranges:
        base, head, live, tree = _effective_range(entry, task['status'], args.committed)
        label = _range_label(base, head, live)
        files = diff_numstat(tree, base, head, against_worktree=live)
        if entry.get('missing'):
            gone = '、'.join(entry['missing'])
            print(paint(f'\n改动 {entry["name"]} {label} — {gone} 已不在仓库里,无法出 diff', RED))
            continue
        _print_commits(tree, entry['name'], base, head, live)
        if files is None:
            print(paint(f'\n改动 {entry["name"]} {label} — 区间不可用', DIM))
            continue
        changed_paths.extend(item['path'] for item in files)
        total_added = sum(item['added'] for item in files)
        total_deleted = sum(item['deleted'] for item in files)
        head_line = (f'\n{paint("改动", BOLD)} {entry["name"]} {label}  '
                     f'{len(files)} 个文件 +{total_added} −{total_deleted}')
        print(head_line)
        ordered = sorted(files, key=lambda item: item['added'] + item['deleted'], reverse=True)
        for item in ordered[:args.files]:
            size = '二进制' if item['binary'] else f'+{item["added"]} −{item["deleted"]}'
            print(f'  {size:<14}{item["path"]}')
        if len(ordered) > args.files:
            print(paint(f'  还有 {len(ordered) - args.files} 个文件,--files 看全部', DIM))
        if live:
            # 未跟踪文件单独列,不进上面的计数:那个数字是改动规模,是 C 层排序的输入,
            # 不能随桌面上有什么临时文件波动。过滤已由 git 的 --exclude-standard 做掉。
            fresh = untracked_files(tree)
            if fresh:
                print(paint(f'  未跟踪的新文件 {len(fresh)} 个(不计入上面的规模)', DIM))
                for item in sorted(fresh, key=lambda x: x['added'], reverse=True)[:args.files]:
                    size = '二进制' if item['binary'] else f'+{item["added"]}'
                    print(paint(f'  {size:<14}{item["path"]}', DIM))

    hits = store.link_notes_touching(project, changed_paths)
    if hits:
        print(f'\n{paint("关键文件", BOLD)}')
        for note in hits:
            print(f'  · {note["title"]}  {paint("[" + str(note["id"]) + "]", DIM)}')

    window = store.notes_between(project, min(starts, default=None), max(ends, default=None))
    if window['added'] or window['superseded']:
        print(f'\n{paint("区间内结论", BOLD)}')
        for note in window['added']:
            print(f'  + [{note["id"]}] {note["title"]}')
        for note in window['superseded']:
            print(paint(f'  ↳ [{note["id"]}] {note["title"]} 已被 [{note["superseded_by"]}] 推翻',
                        DIM))
    return 0


def _warn_uncommitted(store: Store, project: str, ref: int) -> None:
    """完成时工作区还脏,说明这些改动不在区间里——这是唯一值得提醒的时刻。"""
    for repository in store.task_repositories(project, ref):
        dirty = dirty_files(worktree_for(repository['path']))
        if dirty:
            preview = '、'.join(dirty[:3]) + ('…' if len(dirty) > 3 else '')
            print(paint(f'  ⚠ {repository["name"]} 有 {len(dirty)} 个文件未提交,'
                        f'不在区间里:{preview}', RED))


def _status_cmd(status: str):
    def handler(store: Store, args) -> int:
        project = resolve_project(store, args.project)
        # 没有关联仓库的任务才退回 cwd:有仓库时 Store 会逐仓库取,不看这个值
        sha = git_head_sha() if status == 'done' else None
        for ref in args.refs:
            task = store.set_status(project, ref, status, commit_sha=sha)
            print(f'{paint(MARK[status], COLOR[status])} #{task["ref"]} {task["title"]}'
                  f'  {paint(STATUS_LABEL[status], DIM)}')
            if status == 'done' and task['accept']:
                print(paint(f'  验收条件:{task["accept"]}', CYAN))
            if status in ('active', 'done'):
                print_task_commits(store, project, ref, status)
            if status == 'done':
                _warn_uncommitted(store, project, ref)
        if status == 'done' and sha and not store.task_repositories(project, args.refs[0]):
            print(paint(f'  记录完成时 HEAD {sha}(任务没有关联仓库)', DIM))
        if status == 'done':
            snapshot = store.snapshot()
            data = next(p for p in snapshot['projects'] if p['key'] == project)
            unblocked = [
                t for t in data['tasks']
                if t['actionable'] and t['status'] == 'todo'
                and set(t['blocked_by']) & set(args.refs)
            ]
            for task in unblocked:
                print(paint(f'  → 解锁 #{task["ref"]} {task["title"]}', CYAN))
        return 0
    return handler


def cmd_edit(store: Store, args) -> int:
    validate_markdown_newlines(args.detail, args.accept)
    project = resolve_project(store, args.project)
    gate = True if args.gate else (False if args.no_gate else None)
    task = store.update_task(
        project, args.ref, title=args.title, detail=args.detail, owner=args.owner, gate=gate,
        accept=args.accept, branch=args.branch, pr=args.pr, priority=args.priority,
    )
    if args.repo is not None:
        if store.project_repositories(project) and not args.repo:
            raise BoardError('任务至少关联一个需求仓库')
        store.set_task_repositories(project, args.ref, args.repo)
    print(f'#{task["ref"]} {task["title"]}')
    return 0


def cmd_agent_run(store: Store, args) -> int:
    project = resolve_project(store, args.project)
    run = store.record_agent_run(
        project,
        args.ref,
        provider=args.provider,
        dispatch_id=args.dispatch_id,
        repository_path=args.repository,
        status=args.status,
        external_thread_id=args.thread_id,
        external_turn_id=args.turn_id,
        error=args.error,
    )
    print(json.dumps(dict(run), ensure_ascii=False))
    return 0


def cmd_rm(store: Store, args) -> int:
    project = resolve_project(store, args.project)
    for ref in args.refs:
        store.delete_task(project, ref)
        print(f'已删除 #{ref}')
    return 0


def cmd_dep(store: Store, args) -> int:
    project = resolve_project(store, args.project)
    for blocker in _refs(args.on):
        if args.remove:
            store.remove_dep(project, args.ref, blocker)
            print(f'#{args.ref} 不再阻塞于 #{blocker}')
        else:
            store.add_dep(project, args.ref, blocker)
            print(f'#{args.ref} 阻塞于 #{blocker}')
    return 0


NOTE_LABEL = {'finding': '结论', 'risk': '尾巴', 'link': '文件', 'concept': '概念'}


def _note_cmd(kind: str):
    def handler(store: Store, args) -> int:
        validate_markdown_newlines(args.body)
        project = resolve_project(store, args.project)
        supersedes = _refs(getattr(args, 'supersedes', None))
        note = store.add_note(project, kind, args.title, body=args.body,
                              metric=args.metric, supersedes=supersedes,
                              category=args.category)
        category = f' · {note["category"]}' if note['category'] else ''
        print(f'{NOTE_LABEL[kind]} [{note["id"]}] {note["title"]}{category}')
        for old_id in supersedes:
            print(paint(f'  ↳ 推翻了 [{old_id}]', DIM))
        return 0
    return handler


def cmd_notes(store: Store, args) -> int:
    project = resolve_project(store, args.project)
    # 概念按仓库列:同一仓库下别的需求提的概念,对这个需求同样有效,不该重新解释一遍
    concepts = store.concepts(project=project)
    pending = [entry for entry in concepts if entry['state'] in ('proposed', 'stale')]
    if concepts:
        aligned = len(concepts) - len(pending)
        print(paint(f'概念 · 待你确认 {len(pending)} · 已对齐 {aligned}', BOLD))
        for entry in pending:
            print_concept(entry, verbose=args.verbose)
        if pending:
            print(paint('  board align <id> 确认,或 board align <id> --reject "理由"', DIM))
        print()
    labels = {'finding': '约束性结论', 'risk': '尾巴与风险', 'link': '关键文件'}
    for kind, label in labels.items():
        notes = store._note_dicts(project, kind)
        if not args.superseded:
            notes = [note for note in notes if not note['is_superseded']]
        if not notes:
            continue
        print(paint(label, BOLD))
        groups: dict[str, list[dict]] = {}
        for note in notes:
            groups.setdefault(note.get('category') or '未分类', []).append(note)
        for category in sorted(groups, key=lambda value: value == '未分类'):
            category_notes = groups[category]
            print(paint(f'  {category} · {len(category_notes)}', CYAN))
            for note in category_notes:
                metric = paint(f'  {note["metric"]}', DIM) if note['metric'] else ''
                title = note['title']
                if note['is_superseded']:
                    title = paint(f'{title}(已被 [{note["superseded_by"]}] 推翻)', DIM)
                print(f'    [{note["id"]}] {title}{metric}')
                if note['supersedes']:
                    print(paint('      ↳ 推翻了 ' + ', '.join(f'[{i}]' for i in note['supersedes']), DIM))
                if note['body'] and args.verbose:
                    print(paint(f'      {note["body"]}', DIM))
    if not args.superseded:
        hidden = sum(
            1 for kind in labels
            for note in store._note_dicts(project, kind) if note['is_superseded']
        )
        if hidden:
            print(paint(f'\n另有 {hidden} 条已被推翻 · board notes --superseded 查看', DIM))
    return 0


def cmd_note_category(store: Store, args) -> int:
    for note_id in args.ids:
        note = store.set_note_category(note_id, args.category)
        category = note['category'] or '未分类'
        print(f'[{note["id"]}] {note["title"]} → {category}')
    return 0


def cmd_supersede(store: Store, args) -> int:
    note = store.supersede_note(args.old, args.by)
    print(f'[{note["id"]}] {note["title"]} → 已标记为被 [{args.by}] 推翻')
    return 0


def cmd_restore(store: Store, args) -> int:
    for note_id in args.ids:
        note = store.restore_note(note_id)
        print(f'[{note["id"]}] {note["title"]} → 恢复为有效')
    return 0


def cmd_note_rm(store: Store, args) -> int:
    for note_id in args.ids:
        store.delete_note(note_id)
        print(f'已删除记录 {note_id}')
    return 0


def cmd_log(store: Store, args) -> int:
    project = None
    if not args.all_projects:
        try:
            project = resolve_project(store, args.project)
        except BoardError:
            project = None
    for event in store.events(limit=args.limit, project=project):
        ref = f'#{event["task_ref"]}' if event['task_ref'] else ''
        print(f'{paint(event["at"][:16].replace("T", " "), DIM)}  '
              f'{event["project"] or "-":<18} {ref:<5} {event["action"]}')
    return 0


def cmd_export(store: Store, args) -> int:
    snapshot = store.snapshot(include_archived=args.all)
    if args.project:
        key = store.get_project(args.project)['key']
        snapshot['projects'] = [p for p in snapshot['projects'] if p['key'] == key]
    if not args.show_paths:
        # 导出物常被发布或转发；默认移除只对本机有意义、同时会暴露用户名和目录结构的路径。
        # serve 仍直接渲染完整 snapshot，macOS App 则显式传 --show-paths 保持本地体验。
        snapshot['db'] = None
        for project in snapshot['projects']:
            project['repo'] = None
            for repository in project.get('repositories', []):
                repository['path'] = None
            for task in project.get('tasks', []):
                for repository in task.get('repositories', []):
                    repository['path'] = None
                for run in task.get('agent_runs', []):
                    run['repository_path'] = None
    if args.json:
        output = render_json(snapshot)
    else:
        output = html_document(render(
            snapshot, title=args.title, live=False, bridge=args.bridge,
            view_prefs=load_view_prefs(store.path),
        ))
    if args.out == '-':
        print(output)
        return 0
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding='utf-8')
    print(f'已导出 {out_path}')
    published = [p for p in snapshot['projects'] if p['artifact_url']]
    for project in published:
        # 提示复用原链接:另发一个新链接会让之前分享出去的地址变成过期版本
        print(paint(f'  {project["key"]} 已发布于 {project["artifact_url"]} — 更新请复用该链接',
                    DIM))
    return 0


def cmd_serve(store: Store, args) -> int:
    from .serve import serve
    serve(store, host=args.host, port=args.port, title=args.title,
          include_archived=args.all, open_browser=args.open, dev=args.dev)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='board', description='跨对话需求/工作流看板:CLI 更新进度,本地服务或静态导出查看')
    parser.add_argument('--db', help='指定数据库路径(默认 ~/.taskboard/board.db)')
    sub = parser.add_subparsers(dest='command', required=True)

    def add_project_flag(sp):
        sp.add_argument('-p', '--project', help='需求 key(参数名为兼容保留;默认按 cwd 归属判定)')

    sp = sub.add_parser('init', help='登记一个需求/长期工作流')
    sp.add_argument('key')
    sp.add_argument('--name')
    sp.add_argument('--repo', action='append', help='关联仓库路径;可重复传入')
    sp.add_argument('--summary')
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser('projects', help='列出所有需求与进度(命令名为兼容保留)')
    sp.add_argument('--all', action='store_true', help='含已归档')
    sp.set_defaults(func=cmd_projects)

    sp = sub.add_parser('use', help='固定当前需求')
    sp.add_argument('key')
    sp.set_defaults(func=cmd_use)

    sp = sub.add_parser('add', help='加任务')
    sp.add_argument('title')
    sp.add_argument('--detail')
    sp.add_argument('--owner')
    sp.add_argument('--priority', type=_priority, default=2,
                    metavar='P0-P3', help='任务优先级（P0 最高，默认 P2）')
    sp.add_argument('--accept', help='验收条件,done 时会打印出来对照')
    sp.add_argument('--branch', help='关联分支')
    sp.add_argument('--pr', help='关联 PR')
    sp.add_argument('--repo', action='append', help='本任务关联仓库名称或路径;可重复传入')
    sp.add_argument('--gate', action='store_true', help='标记为闸门/关键节点')
    sp.add_argument('--blocked-by', help='前置任务 ref,逗号分隔')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser('ls', help='列任务')
    sp.add_argument('--done', action='store_true', help='含已完成')
    sp.add_argument('--all', action='store_true', help='含已放弃')
    sp.add_argument('-A', '--all-projects', action='store_true', help='所有需求')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_ls)

    sp = sub.add_parser('next', help='现在能开工的任务(未完成、无未决前置、不等人工)')
    sp.add_argument('--limit', type=int, default=5)
    sp.add_argument('--owner', help='只看某人的,如 --owner 我')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_next)

    sp = sub.add_parser('brief', help='交接摘要:可粘贴的现状+下一步+已定结论')
    sp.add_argument('--limit', type=int, default=8)
    sp.add_argument('-v', '--verbose', action='store_true', help='带任务说明')
    sp.add_argument('-A', '--all-projects', action='store_true')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_brief)

    sp = sub.add_parser('find', help='搜任务与记录')
    sp.add_argument('keyword')
    sp.add_argument('-A', '--all-projects', action='store_true')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser('stale', help='停滞的在办任务')
    sp.add_argument('--days', type=int, default=3)
    sp.add_argument('-A', '--all-projects', action='store_true')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_stale)

    sp = sub.add_parser('set', help='改需求属性')
    sp.add_argument('--name')
    sp.add_argument('--summary')
    sp.add_argument('--repo', action='append', help='替换需求关联仓库;可重复传入')
    sp.add_argument('--artifact-url', dest='artifact_url', help='看板发布链接,更新时复用')
    sp.add_argument('--archive', action='store_true')
    sp.add_argument('--unarchive', action='store_true')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser('repo-move', help='仓库改名/搬家后迁移登记路径,已有需求与任务关联跟着走')
    sp.add_argument('old', help='原仓库名或路径')
    sp.add_argument('new', help='新路径')
    sp.add_argument('--merge', action='store_true',
                    help='新路径已登记为另一个仓库时,把旧仓库的关联并过去并删掉旧登记')
    sp.add_argument('--force', action='store_true', help='新路径当前不存在也照样登记')
    sp.set_defaults(func=cmd_repo_move)

    sp = sub.add_parser(
        'review', help='审查包(给任务号)或今天该读什么(--queue,按风险分诊)')
    sp.add_argument('ref', type=int, nargs='?')
    sp.add_argument('--queue', action='store_true',
                    help='按风险排出今天该读的,主信号是有没有引入未对齐概念')
    sp.add_argument('--since', type=int, default=1, metavar='天', help='看近几天(默认 1)')
    sp.add_argument('--limit', type=int, default=5, help='最多列几条(默认 5)')
    sp.add_argument('-A', '--all-projects', action='store_true')
    sp.add_argument('--diff', action='store_true', help='直接出 git diff,渲染交给 git/delta')
    sp.add_argument('--files', type=int, default=8, help='最多列几个文件(默认 8)')
    sp.add_argument('--committed', action='store_true',
                    help='只看已提交区间,在办任务也不比工作区')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser('show', help='看单个任务')
    sp.add_argument('ref', type=int)
    add_project_flag(sp)
    sp.set_defaults(func=cmd_show)

    for name, status, help_text in (
        ('start', 'active', '标记进行中'),
        ('wait', 'waiting', '标记为等人工/外部动作(不再出现在可开工里)'),
        ('done', 'done', '标记完成(打印验收条件、记 HEAD、提示解锁了谁)'),
        ('todo', 'todo', '退回待办'),
        ('drop', 'dropped', '放弃'),
    ):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument('refs', type=int, nargs='+')
        add_project_flag(sp)
        sp.set_defaults(func=_status_cmd(status))

    sp = sub.add_parser('edit', help='改任务')
    sp.add_argument('ref', type=int)
    sp.add_argument('--title')
    sp.add_argument('--detail')
    sp.add_argument('--owner')
    sp.add_argument('--priority', type=_priority, metavar='P0-P3',
                    help='调整任务优先级（P0 最高）')
    sp.add_argument('--accept')
    sp.add_argument('--branch')
    sp.add_argument('--pr')
    sp.add_argument('--repo', action='append', help='替换本任务关联仓库;可重复传入')
    sp.add_argument('--gate', action='store_true')
    sp.add_argument('--no-gate', action='store_true')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_edit)

    sp = sub.add_parser('agent-run', help='记录桌面 Agent 派发结果')
    sp.add_argument('ref', type=int)
    sp.add_argument('--provider', required=True, choices=('codex', 'claude'))
    sp.add_argument('--dispatch-id', required=True)
    sp.add_argument('--repository', required=True)
    sp.add_argument('--status', required=True, choices=('submitted', 'opened', 'failed'))
    sp.add_argument('--thread-id')
    sp.add_argument('--turn-id')
    sp.add_argument('--error')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_agent_run)

    sp = sub.add_parser('rm', help='删任务')
    sp.add_argument('refs', type=int, nargs='+')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_rm)

    sp = sub.add_parser('dep', help='设/删依赖')
    sp.add_argument('ref', type=int)
    sp.add_argument('--on', required=True, help='前置任务 ref,逗号分隔')
    sp.add_argument('--remove', action='store_true')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_dep)

    for name, kind, help_text in (
        ('finding', 'finding', '记一条约束性结论(已判定的事实,别再推演)'),
        ('risk', 'risk', '记一条尾巴/已知风险'),
        ('link', 'link', '记一个关键文件/入口'),
    ):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument('title')
        sp.add_argument('--body')
        sp.add_argument('--metric', help='一行关键数字')
        sp.add_argument('--category', help='稳定主题分类；同一项目建议只用 2~6 类')
        sp.add_argument('--supersedes', help='推翻哪几条旧记录(id,逗号分隔);旧记录保留但标记失效')
        add_project_flag(sp)
        sp.set_defaults(func=_note_cmd(kind))

    sp = sub.add_parser('concept', help='登记一个待人确认的概念(归属仓库,跨需求共享)')
    sp.add_argument('title', help='一句话:是什么、解决什么问题')
    sp.add_argument('--why', help='为什么选它、替代方案为何不用')
    sp.add_argument('--file', action='append', metavar='PATH[:SYMBOL]',
                    help='代码坐标,只给位置不贴代码;可重复传入')
    sp.add_argument('--task', type=int, help='由哪个任务引入(每任务最多 3 个)')
    sp.add_argument('--repo', help='属于哪个仓库(单仓库需求可省略)')
    sp.add_argument('--category')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_concept)

    sp = sub.add_parser('concepts', help='列概念:待对齐/需重新对齐/已对齐')
    sp.add_argument('-v', '--verbose', action='store_true')
    sp.add_argument('--rejected', action='store_true', help='含已否决的')
    sp.add_argument('--repo', help='只看某个仓库')
    sp.add_argument('-A', '--all-projects', action='store_true')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_concepts)

    sp = sub.add_parser('concept-edit', help='改概念卡:追问后补充或修正措辞')
    sp.add_argument('id', type=int)
    sp.add_argument('--title')
    sp.add_argument('--why')
    sp.add_argument('--file', action='append', metavar='PATH[:SYMBOL]',
                    help='替换全部代码锚点;可重复传入')
    sp.add_argument('--category')
    sp.add_argument('--keep-aligned', dest='keep_aligned', action='store_true',
                    help='只改了说法、意思没变时保留已对齐状态')
    sp.set_defaults(func=cmd_concept_edit)

    sp = sub.add_parser('align', help='人确认理解了这个概念(或否决它)')
    sp.add_argument('id', type=int)
    sp.add_argument('--note', help='对齐时想补一句')
    sp.add_argument('--reject', metavar='理由',
                    help='否决:不算新概念,或方案本身不对')
    sp.set_defaults(func=cmd_align)

    sp = sub.add_parser('notes', help='列结论/尾巴/文件(默认只列有效的)')
    sp.add_argument('-v', '--verbose', action='store_true')
    sp.add_argument('--superseded', action='store_true', help='含已被推翻的')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_notes)

    sp = sub.add_parser('supersede', help='事后补推翻关系:old 被 by 推翻')
    sp.add_argument('old', type=int)
    sp.add_argument('--by', type=int, required=True)
    sp.set_defaults(func=cmd_supersede)

    sp = sub.add_parser('restore', help='撤销推翻标记')
    sp.add_argument('ids', type=int, nargs='+')
    sp.set_defaults(func=cmd_restore)

    sp = sub.add_parser('note-rm', help='删记录')
    sp.add_argument('ids', type=int, nargs='+')
    sp.set_defaults(func=cmd_note_rm)

    sp = sub.add_parser('note-category', help='给已有记录设置分类；传空字符串移回未分类')
    sp.add_argument('ids', type=int, nargs='+')
    sp.add_argument('--category', required=True)
    sp.set_defaults(func=cmd_note_category)

    sp = sub.add_parser('log', help='变更历史')
    sp.add_argument('--limit', type=int, default=20)
    sp.add_argument('-A', '--all-projects', action='store_true')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser('export', help='导出自包含 HTML(可发布)')
    sp.add_argument('--out', default='board.html', help='输出路径,- 为 stdout')
    sp.add_argument('--title', default='任务看板')
    sp.add_argument('--json', action='store_true', help='导出 JSON 而非 HTML')
    sp.add_argument('--all', action='store_true', help='含已归档项目')
    sp.add_argument('--show-paths', action='store_true',
                    help='保留本机数据库和仓库绝对路径(默认脱敏)')
    sp.add_argument('--bridge', action='store_true',
                    help='macOS App 专用:状态 chip 可点击,经原生桥写库')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser('serve', help='起本地看板(CLI 一改就自动刷新)')
    sp.add_argument('--port', type=int, default=8787)
    sp.add_argument('--host', default='127.0.0.1')
    sp.add_argument('--title', default='任务看板')
    sp.add_argument('--all', action='store_true', help='含已归档项目')
    sp.add_argument('--open', action='store_true', help='顺便打开浏览器')
    sp.add_argument('--dev', action='store_true',
                    help='开发模式:改代码免重启,保存后页面自动刷新')
    sp.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = Store(args.db)
    try:
        return args.func(store, args)
    except BoardError as exc:
        print(f'{paint("错误", RED)}: {exc}', file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == '__main__':
    raise SystemExit(main())
