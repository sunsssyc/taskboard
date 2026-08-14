"""board 命令行入口。

当前项目按 cwd 归属自动判定(项目登记了 repo 路径),也可用 -p 显式指定或
`board use` 固定。任务在项目内用 #ref 寻址。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .render import STATUS_LABEL, render, render_json
from .store import BoardError, Store, home_dir

CURRENT_FILE = 'current'

DIM = '\033[2m'
BOLD = '\033[1m'
RESET = '\033[0m'
RED = '\033[31m'
CYAN = '\033[36m'
COLOR = {'done': '\033[32m', 'active': '\033[33m', 'todo': '\033[36m', 'dropped': '\033[2m'}
MARK = {'done': '✓', 'active': '▸', 'todo': '·', 'dropped': '✗'}


def _tty() -> bool:
    return sys.stdout.isatty() and not os.environ.get('NO_COLOR')


def paint(text: str, code: str) -> str:
    return f'{code}{text}{RESET}' if _tty() else text


def _current_path() -> Path:
    return home_dir() / CURRENT_FILE


def resolve_project(store: Store, explicit: str | None) -> str:
    """优先级:-p 参数 > cwd 归属 > board use 固定 > 唯一项目。"""
    if explicit:
        return store.get_project(explicit)['key']
    by_path = store.project_for_path(Path.cwd())
    if by_path is not None:
        return by_path['key']
    pinned = _current_path()
    if pinned.exists():
        key = pinned.read_text().strip()
        if key and store.find_project(key):
            return key
    projects = store.projects()
    if len(projects) == 1:
        return projects[0]['key']
    raise BoardError(
        '认不出当前项目:用 -p <key> 指定,或 board use <key> 固定,'
        '或在项目仓库目录里执行(需 board init --repo 登记过路径)'
    )


def _refs(value: str | None) -> list[int]:
    if not value:
        return []
    return [int(part) for part in str(value).replace(',', ' ').split()]


# ── 输出 ────────────────────────────────────────────────────────────────

def print_task_line(task: dict, indent: str = '') -> None:
    mark = paint(MARK[task['status']], COLOR[task['status']])
    ref = paint(f'#{task["ref"]:<3}', BOLD if task['status'] == 'active' else DIM)
    bits = []
    if task['owner']:
        bits.append(f'@{task["owner"]}')
    if task['gate'] and task['status'] != 'done':
        bits.append(paint('闸门', RED))
    if task['open_blockers']:
        bits.append(paint('阻塞于 #' + ',#'.join(str(r) for r in task['open_blockers']), DIM))
    elif task['status'] == 'todo':
        bits.append(paint('可开工', CYAN))
    suffix = f'  {paint(" · ".join(bits), DIM)}' if bits else ''
    print(f'{indent}{mark} {ref} {task["title"]}{suffix}')


def cmd_init(store: Store, args) -> int:
    project = store.create_project(args.key, args.name or args.key, args.repo, args.summary)
    print(f'已建项目 {paint(project["key"], BOLD)} · {project["name"]}')
    if project['repo']:
        print(f'  仓库 {project["repo"]}(在此目录下执行 board 命令即自动定位该项目)')
    return 0


def cmd_projects(store: Store, args) -> int:
    snapshot = store.snapshot(include_archived=args.all)
    if not snapshot['projects']:
        print('还没有项目。board init <key> --name "..." --repo .')
        return 0
    for project in snapshot['projects']:
        counts = project['counts']
        total = sum(counts.values())
        head = f'{paint(project["key"], BOLD)}  {project["name"]}'
        if project['archived']:
            head += paint('  [已归档]', DIM)
        print(head)
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
    print(f'当前项目固定为 {paint(key, BOLD)}')
    return 0


def cmd_add(store: Store, args) -> int:
    project = resolve_project(store, args.project)
    task = store.add_task(
        project, args.title, detail=args.detail, owner=args.owner,
        gate=args.gate, blocked_by=_refs(args.blocked_by),
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
        ready = [t for t in project['tasks'] if t['actionable']]
        if not ready:
            continue
        found = True
        print(f'{paint(project["key"], BOLD)} · {project["name"]}')
        for task in ready[:args.limit]:
            print_task_line(task, indent='  ')
    if not found:
        print('没有可开工的任务(要么都完成了,要么全被阻塞——board ls 看依赖)')
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
                + (f' · 负责 {task["owner"]}' if task['owner'] else '')
                + (' · 闸门' if task['gate'] else ''), DIM))
    if task['detail']:
        print(f'\n{task["detail"]}')
    if task['blocked_by']:
        print(paint(f'\n阻塞于 #{",#".join(str(r) for r in task["blocked_by"])}'
                    + (f'(未完成 #{",#".join(str(r) for r in task["open_blockers"])})'
                       if task['open_blockers'] else '(均已完成)'), DIM))
    if task['blocks']:
        print(paint(f'阻塞 → #{",#".join(str(r) for r in task["blocks"])}', DIM))
    print(paint(f'\n更新于 {task["updated_at"]}', DIM))
    return 0


def _status_cmd(status: str):
    def handler(store: Store, args) -> int:
        project = resolve_project(store, args.project)
        for ref in args.refs:
            task = store.set_status(project, ref, status)
            print(f'{paint(MARK[status], COLOR[status])} #{task["ref"]} {task["title"]}'
                  f'  {paint(STATUS_LABEL[status], DIM)}')
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
    project = resolve_project(store, args.project)
    gate = True if args.gate else (False if args.no_gate else None)
    task = store.update_task(
        project, args.ref, title=args.title, detail=args.detail, owner=args.owner, gate=gate,
    )
    print(f'#{task["ref"]} {task["title"]}')
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


NOTE_LABEL = {'finding': '结论', 'risk': '尾巴', 'link': '文件'}


def _note_cmd(kind: str):
    def handler(store: Store, args) -> int:
        project = resolve_project(store, args.project)
        supersedes = _refs(getattr(args, 'supersedes', None))
        note = store.add_note(project, kind, args.title, body=args.body,
                              metric=args.metric, supersedes=supersedes)
        print(f'{NOTE_LABEL[kind]} [{note["id"]}] {note["title"]}')
        for old_id in supersedes:
            print(paint(f'  ↳ 推翻了 [{old_id}]', DIM))
        return 0
    return handler


def cmd_notes(store: Store, args) -> int:
    project = resolve_project(store, args.project)
    labels = {'finding': '约束性结论', 'risk': '尾巴与风险', 'link': '关键文件'}
    for kind, label in labels.items():
        notes = store._note_dicts(project, kind)
        if not args.superseded:
            notes = [note for note in notes if not note['is_superseded']]
        if not notes:
            continue
        print(paint(label, BOLD))
        for note in notes:
            metric = paint(f'  {note["metric"]}', DIM) if note['metric'] else ''
            title = note['title']
            if note['is_superseded']:
                title = paint(f'{title}(已被 [{note["superseded_by"]}] 推翻)', DIM)
            print(f'  [{note["id"]}] {title}{metric}')
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
    if args.json:
        output = render_json(snapshot)
    else:
        output = render(snapshot, title=args.title, live=False)
    if args.out == '-':
        print(output)
        return 0
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding='utf-8')
    print(f'已导出 {out_path}')
    return 0


def cmd_serve(store: Store, args) -> int:
    from .serve import serve
    serve(store, host=args.host, port=args.port, title=args.title,
          include_archived=args.all, open_browser=args.open, dev=args.dev)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='board', description='跨项目任务看板:CLI 更新进度,本地服务或静态导出查看')
    parser.add_argument('--db', help='指定数据库路径(默认 ~/.taskboard/board.db)')
    sub = parser.add_subparsers(dest='command', required=True)

    def add_project_flag(sp):
        sp.add_argument('-p', '--project', help='项目 key(默认按 cwd 归属自动判定)')

    sp = sub.add_parser('init', help='登记一个项目')
    sp.add_argument('key')
    sp.add_argument('--name')
    sp.add_argument('--repo', help='仓库路径,登记后在该目录下自动定位此项目')
    sp.add_argument('--summary')
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser('projects', help='列出所有项目与进度')
    sp.add_argument('--all', action='store_true', help='含已归档')
    sp.set_defaults(func=cmd_projects)

    sp = sub.add_parser('use', help='固定当前项目')
    sp.add_argument('key')
    sp.set_defaults(func=cmd_use)

    sp = sub.add_parser('add', help='加任务')
    sp.add_argument('title')
    sp.add_argument('--detail')
    sp.add_argument('--owner')
    sp.add_argument('--gate', action='store_true', help='标记为闸门/关键节点')
    sp.add_argument('--blocked-by', help='前置任务 ref,逗号分隔')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser('ls', help='列任务')
    sp.add_argument('--done', action='store_true', help='含已完成')
    sp.add_argument('--all', action='store_true', help='含已放弃')
    sp.add_argument('-A', '--all-projects', action='store_true', help='所有项目')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_ls)

    sp = sub.add_parser('next', help='现在能开工的任务(未完成且无未决前置)')
    sp.add_argument('--limit', type=int, default=5)
    add_project_flag(sp)
    sp.set_defaults(func=cmd_next)

    sp = sub.add_parser('show', help='看单个任务')
    sp.add_argument('ref', type=int)
    add_project_flag(sp)
    sp.set_defaults(func=cmd_show)

    for name, status, help_text in (
        ('start', 'active', '标记进行中'),
        ('done', 'done', '标记完成(并提示解锁了谁)'),
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
    sp.add_argument('--gate', action='store_true')
    sp.add_argument('--no-gate', action='store_true')
    add_project_flag(sp)
    sp.set_defaults(func=cmd_edit)

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
        sp.add_argument('--supersedes', help='推翻哪几条旧记录(id,逗号分隔);旧记录保留但标记失效')
        add_project_flag(sp)
        sp.set_defaults(func=_note_cmd(kind))

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
