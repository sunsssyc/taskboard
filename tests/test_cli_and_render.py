import json
import subprocess

import pytest

from taskboard.cli import main
from taskboard.render import _fmt_stamp, render, render_markdown
from taskboard.store import Store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('TASKBOARD_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('NO_COLOR', '1')
    return str(tmp_path / 'board.db')


def run(db, *argv) -> int:
    return main(['--db', db, *argv])


def _write_test_skill(source):
    (source / 'agents').mkdir(parents=True)
    (source / 'SKILL.md').write_text('---\nname: taskboard\n---\n', encoding='utf-8')
    (source / 'agents' / 'openai.yaml').write_text('interface: {}\n', encoding='utf-8')


def test_skill_sync_updates_codex_and_claude_without_opening_board_db(
        tmp_path, monkeypatch, capsys,
):
    source = tmp_path / 'source-skill'
    _write_test_skill(source)
    codex_home = tmp_path / 'codex-home'
    claude_home = tmp_path / 'claude-home'
    unused_db = tmp_path / 'must-not-be-created.db'
    monkeypatch.setenv('CODEX_HOME', str(codex_home))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(claude_home))

    assert main([
        '--db', str(unused_db), 'skill-sync', '--source', str(source),
    ]) == 0

    assert not unused_db.exists()
    for tool_home in (codex_home, claude_home):
        installed = tool_home / 'skills' / 'taskboard'
        assert (installed / 'SKILL.md').read_text(encoding='utf-8').startswith('---')
        assert (installed / 'agents' / 'openai.yaml').is_file()
    output = capsys.readouterr().out
    assert 'Codex: 已同步 2 个文件' in output
    assert 'Claude Code: 已同步 2 个文件' in output


def test_skill_sync_dry_run_does_not_write(tmp_path, monkeypatch, capsys):
    source = tmp_path / 'source-skill'
    _write_test_skill(source)
    codex_home = tmp_path / 'codex-home'
    monkeypatch.setenv('CODEX_HOME', str(codex_home))

    assert main([
        'skill-sync', '--source', str(source), '--target', 'codex', '--dry-run',
    ]) == 0

    assert not (codex_home / 'skills' / 'taskboard').exists()
    assert 'Codex: 将更新 2 个文件' in capsys.readouterr().out


def test_skill_sync_writes_shared_symlink_target_only_once(tmp_path, monkeypatch, capsys):
    source = tmp_path / 'source-skill'
    _write_test_skill(source)
    shared_target = tmp_path / 'shared-taskboard-skill'
    shared_target.mkdir()
    codex_home = tmp_path / 'codex-home'
    claude_home = tmp_path / 'claude-home'
    for tool_home in (codex_home, claude_home):
        skills_dir = tool_home / 'skills'
        skills_dir.mkdir(parents=True)
        (skills_dir / 'taskboard').symlink_to(shared_target, target_is_directory=True)
    monkeypatch.setenv('CODEX_HOME', str(codex_home))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(claude_home))

    assert main(['skill-sync', '--source', str(source)]) == 0

    assert (shared_target / 'SKILL.md').is_file()
    output = capsys.readouterr().out
    assert 'Codex: 已同步 2 个文件' in output
    assert 'Claude Code: 与 Codex 共用' in output


def test_format_stamp_uses_utc_plus_8():
    assert _fmt_stamp('2026-08-21T00:15:00+00:00') == '2026-08-21 08:15 UTC+8'


def test_cli_flow_add_start_done(db, capsys):
    assert run(db, 'init', 'demo', '--name', '示例') == 0
    assert run(db, 'add', '第一件', '--owner', '我', '-p', 'demo') == 0
    assert run(db, 'add', '第二件', '--blocked-by', '1', '-p', 'demo') == 0
    capsys.readouterr()

    assert run(db, 'next', '-p', 'demo') == 0
    out = capsys.readouterr().out
    assert '第一件' in out and '第二件' not in out  # 被阻塞的不算可开工

    assert run(db, 'done', '1', '-p', 'demo') == 0
    out = capsys.readouterr().out
    assert '解锁' in out and '第二件' in out


def test_cli_priority_orders_next_and_supports_dynamic_update(db, capsys):
    run(db, 'init', 'demo', '--name', '示例')
    run(db, 'add', '常规任务', '--priority', 'P2', '-p', 'demo')
    run(db, 'add', '最高任务', '--priority', 'P0', '-p', 'demo')
    run(db, 'add', '核心任务', '--priority', '1', '-p', 'demo')
    capsys.readouterr()

    run(db, 'next', '-p', 'demo')
    output = capsys.readouterr().out
    assert output.index('最高任务') < output.index('核心任务') < output.index('常规任务')
    assert 'P0' in output and 'P1' in output and 'P2' in output

    run(db, 'edit', '1', '--priority', 'P0', '-p', 'demo')
    capsys.readouterr()
    run(db, 'next', '-p', 'demo')
    output = capsys.readouterr().out
    assert output.index('常规任务') < output.index('最高任务')  # 同优先级按 ref 稳定排序


def test_cli_ls_hides_done_until_flag(db, capsys):
    run(db, 'init', 'demo', '--name', '示例')
    run(db, 'add', '做完的', '-p', 'demo')
    run(db, 'done', '1', '-p', 'demo')
    capsys.readouterr()

    run(db, 'ls', '-p', 'demo')
    assert '做完的' not in capsys.readouterr().out
    run(db, 'ls', '--done', '-p', 'demo')
    assert '做完的' in capsys.readouterr().out


def test_cli_notes_group_and_reclassify(db, capsys):
    run(db, 'init', 'demo', '--name', '结论分类')
    run(db, 'finding', '模型已定', '--category', '模型口径', '-p', 'demo')
    run(db, 'finding', '已部署', '--category', '交付状态', '-p', 'demo')
    capsys.readouterr()

    assert run(db, 'notes', '-p', 'demo') == 0
    output = capsys.readouterr().out
    assert '模型口径 · 1' in output and '交付状态 · 1' in output

    assert run(db, 'note-category', '1', '--category', '交付状态') == 0
    capsys.readouterr()
    store = Store(db)
    assert store.get_note(1)['category'] == '交付状态'
    store.close()


def test_cli_resolves_project_from_cwd(db, tmp_path, monkeypatch, capsys):
    repo = tmp_path / 'myrepo'
    repo.mkdir()
    run(db, 'init', 'byrepo', '--name', '按目录', '--repo', str(repo))
    run(db, 'add', '目录内任务', '-p', 'byrepo')
    capsys.readouterr()

    monkeypatch.chdir(repo)
    assert run(db, 'ls') == 0  # 不传 -p 也能定位
    assert '目录内任务' in capsys.readouterr().out


def test_cli_unknown_project_errors_cleanly(db, capsys):
    assert run(db, 'add', '无主任务', '-p', 'nope') == 1
    assert '没有这个需求' in capsys.readouterr().err


def test_cli_ambiguous_project_errors_cleanly(db, tmp_path, monkeypatch, capsys):
    run(db, 'init', 'a', '--name', 'A')
    run(db, 'init', 'b', '--name', 'B')
    capsys.readouterr()
    monkeypatch.chdir(tmp_path)
    assert run(db, 'ls') == 1
    assert '认不出当前需求' in capsys.readouterr().err


def test_cli_multi_repo_task_requires_explicit_repository(db, tmp_path, capsys):
    backend = tmp_path / 'coinex_backend'
    admin = tmp_path / 'coinex_admin_frontend'
    backend.mkdir()
    admin.mkdir()
    assert run(
        db, 'init', 'multi', '--name', '跨仓库需求',
        '--repo', str(backend), '--repo', str(admin),
    ) == 0
    capsys.readouterr()

    assert run(db, 'add', '未确认仓库', '-p', 'multi') == 1
    assert '请先和用户确认' in capsys.readouterr().err
    assert run(db, 'add', '后端任务', '-p', 'multi', '--repo', 'coinex_backend') == 0

    store = Store(db)
    try:
        assert [repo['name'] for repo in store.task_repositories('multi', 1)] == [
            'coinex_backend',
        ]
    finally:
        store.close()


def test_cli_repo_move_restores_cwd_detection_after_rename(db, tmp_path, monkeypatch, capsys):
    old = tmp_path / 'claude-taskboard'
    old.mkdir()
    other = tmp_path / 'other'
    other.mkdir()
    assert run(db, 'init', 'tb', '--name', '看板', '--repo', str(old)) == 0
    assert run(db, 'init', 'other', '--name', '别的', '--repo', str(other)) == 0
    assert run(db, 'add', '既有任务', '-p', 'tb') == 0
    new = tmp_path / 'taskboard'
    old.rename(new)
    capsys.readouterr()

    monkeypatch.chdir(new)
    assert run(db, 'ls') == 1  # 路径还是旧的,cwd 认不出需求
    assert '认不出当前需求' in capsys.readouterr().err
    assert run(db, 'set', '-p', 'tb', '--repo', str(new)) == 1
    assert '仍被任务' in capsys.readouterr().err

    assert run(db, 'repo-move', 'claude-taskboard', str(new)) == 0
    out = capsys.readouterr().out
    assert 'claude-taskboard' in out and str(new) in out and '任务关联 1 条' in out

    assert run(db, 'ls') == 0
    assert '既有任务' in capsys.readouterr().out


def test_cli_start_and_done_print_commit_range(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    repo.mkdir()

    def git(*argv):
        subprocess.run(
            ['git', '-C', str(repo), '-c', 'user.email=t@t', '-c', 'user.name=t', *argv],
            check=True, capture_output=True,
        )

    git('init', '-q')
    git('commit', '-q', '--allow-empty', '-m', 'init')
    assert run(db, 'init', 'ranged', '--name', '带区间', '--repo', str(repo)) == 0
    assert run(db, 'add', '会产生提交的活', '-p', 'ranged') == 0
    capsys.readouterr()

    assert run(db, 'start', '1', '-p', 'ranged') == 0
    started = capsys.readouterr().out
    assert '起点 repo' in started

    git('commit', '-q', '--allow-empty', '-m', '任务里的改动')
    assert run(db, 'done', '1', '-p', 'ranged') == 0
    finished = capsys.readouterr().out
    assert '区间 repo' in finished and '..' in finished

    assert run(db, 'show', '1', '-p', 'ranged') == 0
    assert '改动 repo' in capsys.readouterr().out


def _repo_with_commit(path, message='init'):
    path.mkdir(parents=True, exist_ok=True)

    def git(*argv):
        subprocess.run(
            ['git', '-C', str(path), '-c', 'user.email=t@t', '-c', 'user.name=t', *argv],
            check=True, capture_output=True,
        )

    git('init', '-q')
    (path / 'seed.txt').write_text('seed\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', message)
    return git


def test_cli_review_shows_range_files_and_window_notes(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    git = _repo_with_commit(repo)
    assert run(db, 'init', 'rev', '--name', '审查', '--repo', str(repo)) == 0
    assert run(db, 'add', '改点东西', '-p', 'rev', '--detail', '为了验证审查包',
               '--accept', '能一屏看完') == 0
    assert run(db, 'start', '1', '-p', 'rev') == 0
    (repo / 'big.py').write_text('x = 1\n' * 30, encoding='utf-8')
    (repo / 'small.py').write_text('y = 2\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', '任务里的改动')
    assert run(db, 'link', 'big.py', '-p', 'rev', '--body', '关键入口') == 0
    assert run(db, 'done', '1', '-p', 'rev') == 0
    capsys.readouterr()

    assert run(db, 'review', '1', '-p', 'rev') == 0
    out = capsys.readouterr().out
    assert '为了验证审查包' in out and '能一屏看完' in out
    assert '2 个文件' in out
    # 大文件排在前面:先看改得多的
    assert out.index('big.py') < out.index('small.py')
    assert '关键文件' in out          # link 命中被改的文件
    assert '区间内结论' in out         # 区间内新增的记录


def test_cli_review_of_active_task_includes_uncommitted_work(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    _repo_with_commit(repo)
    assert run(db, 'init', 'wip', '--name', '在办', '--repo', str(repo)) == 0
    assert run(db, 'add', '还没做完', '-p', 'wip') == 0
    assert run(db, 'start', '1', '-p', 'wip') == 0
    (repo / 'seed.txt').write_text('seed\nchanged\n', encoding='utf-8')
    capsys.readouterr()

    assert run(db, 'review', '1', '-p', 'wip') == 0
    out = capsys.readouterr().out
    assert '工作区(含未提交)' in out
    assert 'seed.txt' in out


def test_cli_review_reports_unusable_range_instead_of_faking_one(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    git = _repo_with_commit(repo)
    assert run(db, 'init', 'gone', '--name', '失效', '--repo', str(repo)) == 0
    assert run(db, 'add', '会被改写', '-p', 'gone') == 0
    assert run(db, 'start', '1', '-p', 'gone') == 0
    git('commit', '-q', '--allow-empty', '-m', '原提交')
    assert run(db, 'done', '1', '-p', 'gone') == 0
    git('commit', '-q', '--allow-empty', '--amend', '-m', '改写后')
    git('reflog', 'expire', '--expire=now', '--all')
    git('gc', '-q', '--prune=now')
    capsys.readouterr()

    assert run(db, 'review', '1', '-p', 'gone') == 0
    out = capsys.readouterr().out
    assert '已不在仓库里' in out and '个文件' not in out


def test_cli_review_without_range_says_so(db, capsys):
    assert run(db, 'init', 'bare', '--name', '没仓库') == 0
    assert run(db, 'add', '没有关联仓库', '-p', 'bare') == 0
    assert run(db, 'done', '1', '-p', 'bare') == 0
    capsys.readouterr()

    assert run(db, 'review', '1', '-p', 'bare') == 0
    assert '无区间记录' in capsys.readouterr().out


def test_cli_review_caps_file_list(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    git = _repo_with_commit(repo)
    assert run(db, 'init', 'many', '--name', '很多文件', '--repo', str(repo)) == 0
    assert run(db, 'add', '改一堆', '-p', 'many') == 0
    assert run(db, 'start', '1', '-p', 'many') == 0
    for index in range(6):
        (repo / f'f{index}.py').write_text(f'v = {index}\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', '六个文件')
    assert run(db, 'done', '1', '-p', 'many') == 0
    capsys.readouterr()

    assert run(db, 'review', '1', '-p', 'many', '--files', '2') == 0
    out = capsys.readouterr().out
    assert '6 个文件' in out and '还有 4 个文件' in out


def test_cli_review_lists_untracked_separately_and_respects_gitignore(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    _repo_with_commit(repo)
    (repo / '.gitignore').write_text('noise/\n', encoding='utf-8')
    assert run(db, 'init', 'fresh', '--name', '新文件', '--repo', str(repo)) == 0
    assert run(db, 'add', '新建了文件', '-p', 'fresh') == 0
    assert run(db, 'start', '1', '-p', 'fresh') == 0
    (repo / 'seed.txt').write_text('seed\nchanged\n', encoding='utf-8')
    (repo / 'brand_new.py').write_text('a = 1\nb = 2\n', encoding='utf-8')
    (repo / 'noise').mkdir()
    (repo / 'noise' / 'junk.tmp').write_text('垃圾\n', encoding='utf-8')
    capsys.readouterr()

    assert run(db, 'review', '1', '-p', 'fresh') == 0
    out = capsys.readouterr().out
    assert 'brand_new.py' in out              # 未跟踪的新文件要看得见
    assert '未跟踪的新文件' in out
    assert 'junk.tmp' not in out              # 被 .gitignore 挡掉,不重做一套排除规则
    # 规模只算已跟踪的改动:未跟踪文件不能让这个数字随桌面上的临时文件波动
    assert '1 个文件' in out


def test_cli_review_committed_flag_ignores_working_tree(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    _repo_with_commit(repo)
    assert run(db, 'init', 'strict', '--name', '只看已提交', '--repo', str(repo)) == 0
    assert run(db, 'add', '在办任务', '-p', 'strict') == 0
    assert run(db, 'start', '1', '-p', 'strict') == 0
    (repo / 'seed.txt').write_text('seed\n未提交的改动\n', encoding='utf-8')
    capsys.readouterr()

    assert run(db, 'review', '1', '-p', 'strict', '--committed') == 0
    out = capsys.readouterr().out
    assert '工作区(含未提交)' not in out
    assert '区间不完整' in out                 # 还没 done,没有终点,如实说


def test_cli_review_lists_commits_before_merged_diffstat(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    git = _repo_with_commit(repo)
    assert run(db, 'init', 'byc', '--name', '按提交读', '--repo', str(repo)) == 0
    assert run(db, 'add', '分两步做', '-p', 'byc') == 0
    assert run(db, 'start', '1', '-p', 'byc') == 0
    (repo / 'first.py').write_text('a = 1\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', '第一步:打地基')
    (repo / 'second.py').write_text('b = 2\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', '第二步:接上去')
    assert run(db, 'done', '1', '-p', 'byc') == 0
    capsys.readouterr()

    assert run(db, 'review', '1', '-p', 'byc') == 0
    out = capsys.readouterr().out
    assert '第一步:打地基' in out and '第二步:接上去' in out
    # 提交列表在合并 diffstat 之前:先按提交读,合并数字只作总量参考
    assert out.index('第二步:接上去') < out.index('2 个文件')


def test_cli_review_nudges_to_commit_when_nothing_committed(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    _repo_with_commit(repo)
    assert run(db, 'init', 'nudge', '--name', '还没提交', '--repo', str(repo)) == 0
    assert run(db, 'add', '写了没提交', '-p', 'nudge') == 0
    assert run(db, 'start', '1', '-p', 'nudge') == 0
    (repo / 'seed.txt').write_text('seed\n改了\n', encoding='utf-8')
    capsys.readouterr()

    assert run(db, 'review', '1', '-p', 'nudge') == 0
    assert '改动都还没提交' in capsys.readouterr().out


def test_cli_done_warns_about_uncommitted_work(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    git = _repo_with_commit(repo)
    assert run(db, 'init', 'dirty', '--name', '完成时还脏', '--repo', str(repo)) == 0
    assert run(db, 'add', '做完但没提交干净', '-p', 'dirty') == 0
    assert run(db, 'start', '1', '-p', 'dirty') == 0
    (repo / 'done.py').write_text('x = 1\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', '提交了一部分')
    (repo / 'forgotten.py').write_text('y = 2\n', encoding='utf-8')
    capsys.readouterr()

    assert run(db, 'done', '1', '-p', 'dirty') == 0
    out = capsys.readouterr().out
    assert '未提交' in out and 'forgotten.py' in out


def test_cli_done_stays_quiet_when_tree_is_clean(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    git = _repo_with_commit(repo)
    assert run(db, 'init', 'clean', '--name', '干净收工', '--repo', str(repo)) == 0
    assert run(db, 'add', '提交干净了', '-p', 'clean') == 0
    assert run(db, 'start', '1', '-p', 'clean') == 0
    (repo / 'done.py').write_text('x = 1\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', '全提交了')
    capsys.readouterr()

    assert run(db, 'done', '1', '-p', 'clean') == 0
    assert '未提交' not in capsys.readouterr().out


def test_cli_concept_align_flow_across_projects(db, tmp_path, capsys):
    repo = tmp_path / 'svc'
    git = _repo_with_commit(repo)
    assert run(db, 'init', 'alpha', '--name', '需求A', '--repo', str(repo)) == 0
    assert run(db, 'init', 'beta', '--name', '需求B') == 0
    assert run(db, 'set', '-p', 'beta', '--repo', str(repo)) == 0
    assert run(db, 'add', '做点事', '-p', 'alpha') == 0
    capsys.readouterr()

    assert run(db, 'concept', '增量对账用水位线', '--why', '全量扫描随数据增长',
               '--file', 'seed.txt', '--task', '1', '-p', 'alpha') == 0
    out = capsys.readouterr().out
    assert '待对齐' in out and '锚点 seed.txt' in out

    # 另一个需求也看得到:概念归仓库,不归需求
    assert run(db, 'concepts', '-p', 'beta') == 0
    assert '增量对账用水位线' in capsys.readouterr().out
    assert run(db, 'notes', '-p', 'beta') == 0
    assert '待你确认 1' in capsys.readouterr().out

    assert run(db, 'align', '1') == 0
    assert '已对齐' in capsys.readouterr().out

    (repo / 'seed.txt').write_text('seed\n改了锚点\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', '动了锚点文件')
    assert run(db, 'concepts', '-p', 'alpha') == 0
    assert '需重新对齐' in capsys.readouterr().out


def test_cli_concept_rejects_with_reason(db, tmp_path, capsys):
    repo = tmp_path / 'svc'
    _repo_with_commit(repo)
    assert run(db, 'init', 'solo', '--name', '单需求', '--repo', str(repo)) == 0
    assert run(db, 'concept', '可疑概念', '-p', 'solo') == 0
    capsys.readouterr()

    assert run(db, 'align', '1', '--reject', '这不算新概念') == 0
    out = capsys.readouterr().out
    assert '已否决' in out and '这不算新概念' in out
    assert run(db, 'concepts', '-p', 'solo') == 0
    assert '还没有概念' in capsys.readouterr().out


def test_cli_concept_repo_is_required_only_for_code_anchors(db, tmp_path, capsys):
    backend = tmp_path / 'backend'
    frontend = tmp_path / 'frontend'
    _repo_with_commit(backend)
    _repo_with_commit(frontend)
    assert run(db, 'init', 'multi', '--name', '跨仓库',
               '--repo', str(backend), '--repo', str(frontend)) == 0
    capsys.readouterr()

    # 有代码锚点就必须说清锚在哪个仓库
    assert run(db, 'concept', '带锚点的', '-p', 'multi', '--file', 'seed.txt') == 1
    assert '--repo' in capsys.readouterr().err
    assert run(db, 'concept', '带锚点的', '-p', 'multi',
               '--file', 'seed.txt', '--repo', 'backend') == 0
    capsys.readouterr()

    # 方法论概念没有锚点,不该被逼着在两个仓库里挑一个
    assert run(db, 'concept', 'KS 值只在同一时间窗内可比', '-p', 'multi') == 0
    assert '需求概念' in capsys.readouterr().out


def _queued(db, *extra):
    """跑一次队列并把输出切成 (档位 -> 该档里的任务号)。"""
    import io, contextlib
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert run(db, 'review', '--queue', *extra) == 0
    return buffer.getvalue()


def test_cli_review_queue_ranks_unaligned_concepts_first(db, tmp_path, capsys):
    repo = tmp_path / 'svc'
    git = _repo_with_commit(repo)
    (repo / '.gitattributes').write_text('*.py diff=python\n', encoding='utf-8')
    (repo / 'core.py').write_text(
        'def sched():\n    return 1\n\n\ndef util():\n    return 2\n', encoding='utf-8')
    (repo / 'render.py').write_text('def render():\n    return 3\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', '基线')
    assert run(db, 'init', 'q', '--name', '分诊', '--repo', str(repo)) == 0
    assert run(db, 'link', 'render.py', '-p', 'q', '--body', '导出入口') == 0

    # 引入新概念的任务
    assert run(db, 'add', '重构调度器', '-p', 'q', '--accept', '旧接口不变') == 0
    assert run(db, 'start', '1', '-p', 'q') == 0
    assert run(db, 'concept', '调度改用时间轮', '--file', 'core.py:sched',
               '--task', '1', '-p', 'q') == 0
    (repo / 'core.py').write_text(
        'def sched():\n    return 99\n\n\ndef util():\n    return 2\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', '时间轮')
    assert run(db, 'done', '1', '-p', 'q') == 0

    # 只碰关键文件的任务
    assert run(db, 'add', '改导出', '-p', 'q', '--accept', '不乱码') == 0
    assert run(db, 'start', '2', '-p', 'q') == 0
    (repo / 'render.py').write_text('def render():\n    return 33\n', encoding='utf-8')
    git('add', '-A')
    git('commit', '-q', '-m', '改导出')
    assert run(db, 'done', '2', '-p', 'q') == 0
    capsys.readouterr()

    out = _queued(db, '-p', 'q')
    assert '必须先对齐' in out and '调度改用时间轮' in out
    assert out.index('#1') < out.index('#2')          # 未对齐概念排在关键文件前面
    assert '触碰关键文件 render.py' in out

    # 对齐之后 #1 掉出该读的队列——队列会因为人的动作而变短
    assert run(db, 'align', '2') == 0
    after = _queued(db, '-p', 'q')
    assert '必须先对齐' not in after
    assert '可跳过' in after and '#1' in after.split('可跳过')[1]


def test_cli_review_queue_collapses_skippable_and_needs_a_target(db, tmp_path, capsys):
    repo = tmp_path / 'svc'
    git = _repo_with_commit(repo)
    assert run(db, 'init', 'quiet', '--name', '安静', '--repo', str(repo)) == 0
    for index in range(3):
        assert run(db, 'add', f'小改动{index}', '-p', 'quiet', '--accept', '无回归') == 0
        assert run(db, 'start', str(index + 1), '-p', 'quiet') == 0
        (repo / f'f{index}.py').write_text('x = 1\n', encoding='utf-8')
        git('add', '-A')
        git('commit', '-q', '-m', f'改动{index}')
        assert run(db, 'done', str(index + 1), '-p', 'quiet') == 0
    capsys.readouterr()

    out = _queued(db, '-p', 'quiet')
    # 全量列表本身就是过载的一部分:可跳过的折成一行
    assert '该读的 0 条' in out
    assert out.count('可跳过') == 1

    assert run(db, 'review', '-p', 'quiet') == 1
    assert '--queue' in capsys.readouterr().err


def test_cli_export_html_and_json(db, tmp_path, capsys):
    repo = tmp_path / 'repo'
    repo.mkdir()
    run(db, 'init', 'demo', '--name', '示例项目', '--repo', str(repo))
    run(db, 'add', '任务甲', '--detail', '细节说明', '-p', 'demo')
    run(db, 'finding', '关键结论', '--metric', '40/40', '-p', 'demo')
    capsys.readouterr()

    html_path = tmp_path / 'out.html'
    run(db, 'export', '--out', str(html_path), '-p', 'demo')
    html = html_path.read_text(encoding='utf-8')
    assert html.startswith('<!doctype html><meta charset="utf-8">')
    assert '示例项目' in html and '任务甲' in html
    assert '关键结论' in html and '40/40' in html
    assert db not in html
    assert str(repo) not in html
    assert 'class="repo-tag">repo</span>' in html
    assert 'class="chip repo">repo</span>' in html

    json_path = tmp_path / 'out.json'
    run(db, 'export', '--json', '--out', str(json_path))
    data = json.loads(json_path.read_text(encoding='utf-8'))
    assert data['projects'][0]['tasks'][0]['title'] == '任务甲'
    assert data['projects'][0]['repositories'][0]['path'] is None
    assert data['projects'][0]['tasks'][0]['repositories'][0]['path'] is None
    assert data['db'] is None
    assert data['projects'][0]['repo'] is None

    local_path = tmp_path / 'local.html'
    run(db, 'export', '--show-paths', '--out', str(local_path), '-p', 'demo')
    local_html = local_path.read_text(encoding='utf-8')
    assert db in local_html
    assert str(repo) in local_html


def test_cli_agent_run_records_ids_and_scrubs_repository_from_public_export(
    db, tmp_path, capsys,
):
    repo = tmp_path / 'repo'
    repo.mkdir()
    run(db, 'init', 'demo', '--name', 'Agent 派发', '--repo', str(repo))
    run(db, 'add', '交给 Codex', '-p', 'demo')
    capsys.readouterr()

    assert run(
        db, 'agent-run', '1', '-p', 'demo', '--provider', 'codex',
        '--dispatch-id', 'codex-cli-test', '--repository', str(repo),
        '--status', 'submitted', '--thread-id', 'thread-cli', '--turn-id', 'turn-cli',
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['external_thread_id'] == 'thread-cli'

    exported = tmp_path / 'agent.json'
    run(db, 'export', '--json', '--out', str(exported))
    agent_run = json.loads(exported.read_text(encoding='utf-8'))['projects'][0]['tasks'][0][
        'agent_runs'
    ][0]
    assert agent_run['provider'] == 'codex'
    assert agent_run['repository_path'] is None


def test_render_escapes_html(tmp_path):
    store = Store(tmp_path / 'board.db')
    store.create_project('x', '<script>alert(1)</script>')
    store.add_task('x', '标题 & <b>粗</b>')
    html = render(store.snapshot())
    store.close()
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html
    assert '&amp;' in html


def test_render_uses_xcode_style_light_workspace(tmp_path):
    store = Store(tmp_path / 'board.db')
    store.create_project('x', '主题检查')
    html = render(store.snapshot())
    store.close()
    assert 'color-scheme:light' in html
    assert '--chrome:#f7f7f8' in html
    assert 'grid-template-columns:248px minmax(0,1fr)' in html
    assert 'class="navigator" aria-label="需求导航"' in html
    assert '<h3>全部需求</h3>' in html
    assert '<div class="navigator-head"><span>需求</span>' in html
    assert '<main class="content">' in html
    assert 'prefers-color-scheme: dark' not in html
    assert 'background:var(--ground)' in html
    assert '.done-fold summary, .active-fold summary, .ready-fold summary,' in html
    assert 'grid-template-columns:48px minmax(0,1fr); align-items:center' in html
    assert '.done-fold > .step, .active-fold > .step,' in html
    assert 'grid-template-columns:64px minmax(0,1fr)' in html
    assert 'grid-template-columns:56px minmax(0,1fr)' in html
    assert '.task-disclosure { position:relative; width:100%' in html
    assert 'transform:translate(-50%,-50%) rotate(-45deg)' in html
    assert '.task-disclosure > span { position:absolute; left:calc(50% + 8px)' in html


def test_render_marks_gate_and_blocking(tmp_path):
    store = Store(tmp_path / 'board.db')
    store.create_project('x', '闸门')
    first = store.add_task('x', '前置')
    store.add_task('x', '闸门任务', gate=True, blocked_by=[first['ref']])
    html = render(store.snapshot())
    store.close()
    assert '闸门</span>' in html
    assert '阻塞 →' in html  # 主任务仍展示它会阻塞谁
    assert '<details class="blocked-fold">' in html
    assert '<summary>还有 1 项被阻塞待办</summary>' in html


def test_render_long_notes_use_full_width_reading_layout(tmp_path):
    store = Store(tmp_path / 'long-notes.db')
    store.create_project('demo', '长结论排版')
    store.add_note('demo', 'finding', '短结论', body='一句话说明')
    store.add_note('demo', 'finding', '长篇技术结论', body='技术正文' * 100)
    html = render(store.snapshot())
    store.close()

    assert '<details class="note finding" id="note-1"' in html
    assert '<details class="note finding long" id="note-2"' in html
    assert html.count('class="note-summary"') >= 2
    assert 'class="note finding" id="note-1" open' not in html
    assert 'role="heading" aria-level="4"' in html
    assert 'grid-column:1/-1' in html
    assert 'grid-template-columns:minmax(240px,.75fr) minmax(0,1.8fr)' in html
    assert 'grid-template-columns:48px minmax(0,1fr)' in html
    assert '.note-summary { min-height:42px' in html
    assert '.notes { display:flex; flex-direction:column' in html
    assert 'overflow-wrap:anywhere' in html
    assert '@media (max-width:760px)' in html


def test_render_groups_findings_by_category_with_uncategorized_last(tmp_path):
    store = Store(tmp_path / 'categories.db')
    store.create_project('demo', '结论分类')
    store.add_note('demo', 'finding', '采样口径', category='模型口径')
    store.add_note('demo', 'finding', '发版完成', category='交付状态')
    store.add_note('demo', 'finding', '旧数据')
    store.add_note('demo', 'link', 'docs/model.md', category='模型口径')
    html = render(store.snapshot())
    store.close()

    assert 'class="category-index"' in html
    assert '<h3>模型口径</h3><span>1 条</span>' in html
    assert '<h3>交付状态</h3><span>1 条</span>' in html
    assert '<h3>未分类</h3><span>1 条</span>' in html
    assert html.index('<h3>未分类</h3>') > html.index('<h3>交付状态</h3>')
    assert 'data-search="1 模型口径 采样口径' in html
    assert html.count('id="finding-demo-category-') == 3
    assert html.count('class="note-group" id="finding-demo-category-1" open') == 1
    assert 'class="note-group" id="link-demo-category-1" open' in html
    assert 'data-search="模型口径 docs/model.md' in html


def test_safe_markdown_renders_supported_blocks_and_rejects_unsafe_html():
    rendered = render_markdown("""## 当前判断

**影响明确**，字段 `sampling_policy` 已固定。

- 证据一
- 证据二

1. 先验证
2. 再发布

> 不要跳过回归测试。

```python
print("<unsafe>")
```

[安全链接](https://example.com/docs?a=1&b=2)
[危险链接](javascript:alert(1))
[实体伪装](java&#x73;cript:alert(1))
[控制字符伪装](java\tscript:alert(1))
<script>alert(1)</script>
""")

    assert '<h5>当前判断</h5>' in rendered
    assert '<strong>影响明确</strong>' in rendered
    assert '<code>sampling_policy</code>' in rendered
    assert '<ul><li>证据一</li><li>证据二</li></ul>' in rendered
    assert '<ol><li>先验证</li><li>再发布</li></ol>' in rendered
    assert '<blockquote><p>不要跳过回归测试。</p></blockquote>' in rendered
    assert '<pre><code class="language-python">print(&quot;&lt;unsafe&gt;&quot;)</code></pre>' in rendered
    assert 'href="https://example.com/docs?a=1&amp;b=2"' in rendered
    assert rendered.count('<a href=') == 1
    assert 'href="javascript:' not in rendered and 'href="java&amp;#x73;cript:' not in rendered
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered


def test_task_and_note_fields_render_markdown(tmp_path):
    store = Store(tmp_path / 'markdown.db')
    store.create_project('demo', 'Markdown')
    store.add_task('demo', '结构化任务', detail='**影响**\n\n- 补测试', accept='运行 `pytest`')
    store.add_note('demo', 'finding', '结构化结论', body='> 已验证\n\n查看 [文档](docs/check.md)')
    store.add_note('demo', 'link', 'docs/check.md', body='查看 **支持范围**')
    html = render(store.snapshot())
    store.close()

    assert 'class="markdown card-detail"' in html
    assert '<strong>影响</strong>' in html and '<li>补测试</li>' in html
    assert '<div class="accept"><b>验收</b>运行 <code>pytest</code></div>' in html
    # 主任务默认完整展开,正文开关收进节点序号旁的 disclosure,不再使用底部按钮。
    assert '<div class="task-body"><div class="markdown card-detail"' in html
    assert 'class="task-disclosure" aria-expanded="true"' in html
    assert 'aria-label="收起 #1 全文"' in html
    assert 'body.hidden = !expanded' in html
    assert '展开全部' not in html
    assert '<div class="lifecycle" aria-label="节点时间">' in html
    assert '<b>创建</b><time datetime="' in html
    assert '<b>首次开始</b>尚未开始' in html
    assert '<b>最近变更</b><time datetime="' in html
    assert 'UTC+8</time>' in html
    assert 'class="markdown note-body"' in html
    assert '<blockquote><p>已验证</p></blockquote>' in html
    assert '<a href="docs/check.md">文档</a>' in html
    assert '<code>docs/check.md</code> 查看 <strong>支持范围</strong>' in html


def test_live_render_has_interactions_but_static_export_stays_read_only(tmp_path):
    store = Store(tmp_path / 'interactive.db')
    store.create_project('demo', '交互看板')
    store.add_task('demo', '可操作任务', detail='**说明**', owner='我')
    store.add_note('demo', 'finding', '分类提示', category='模型口径')
    snapshot = store.snapshot()
    store.close()

    live_html = render(
        snapshot, live=True, csrf_token='test-csrf', write_enabled=True,
    )
    assert 'name="query"' in live_html and 'name="status"' in live_html
    assert 'class="detail-button"' in live_html
    assert 'data-create="task"' in live_html and 'data-create="finding"' in live_html
    assert 'name="category"' in live_html
    assert 'name="repositories" multiple' in live_html
    assert 'data-repositories=' in live_html
    assert "payload.repositories = data.getAll('repositories')" in live_html
    assert '<label>需求<select name="project"' in live_html
    assert "document.querySelector('.pgroup[data-selected] .pcard[data-project]')" in live_html
    assert 'list="finding-categories"' in live_html and '模型口径' in live_html
    assert "var createForm = createDialog ?" in live_html
    assert 'data-status="done"' in live_html
    assert 'data-csrf="test-csrf"' in live_html
    assert '/api/tasks/' in live_html
    assert "current.task.accept ? '\\n\\n验收条件" in live_html
    assert 'function formatUtc8(value)' in live_html
    assert "['首次开始', task.first_started_at ? formatUtc8(task.first_started_at) : '尚未开始']" in live_html
    assert "element('time', '', formatUtc8(event.at))" in live_html
    assert 'inset:0 0 0 auto' in live_html and '--inspector-shadow' in live_html

    static_html = render(snapshot)
    assert 'name="query"' in static_html  # 搜索筛选仍是纯前端只读交互
    assert 'class="detail-button"' not in static_html
    assert 'data-create="task"' not in static_html
    assert '<button type="button" class="action primary" data-status="done">' not in static_html
    assert 'data-csrf=' not in static_html
    assert '/api/tasks/' not in static_html


def test_task_commands_reject_literal_paragraph_breaks(db, capsys):
    run(db, 'init', 'demo', '--name', '换行防错')
    capsys.readouterr()

    assert run(db, 'add', '错误换行', '--detail', r'第一段\n\n第二段', '-p', 'demo') == 1
    assert '字面量 \\n\\n' in capsys.readouterr().err

    assert run(db, 'add', '真实换行', '--detail', '第一段\n\n第二段', '-p', 'demo') == 0
    assert run(db, 'edit', '1', '--detail', r'改后第一段\n\n改后第二段', '-p', 'demo') == 1
    assert '字面量 \\n\\n' in capsys.readouterr().err

    # 明确放在代码跨度里的转义符是展示内容,不应误报。
    assert run(db, 'edit', '1', '--detail', r'展示 `\n\n` 转义符', '-p', 'demo') == 0


@pytest.mark.parametrize('command', ['finding', 'risk', 'link'])
def test_note_commands_reject_literal_paragraph_breaks(db, capsys, command):
    run(db, 'init', 'demo', '--name', '记录换行防错')
    capsys.readouterr()

    assert run(db, command, '错误记录', '--body', r'第一段\n\n第二段', '-p', 'demo') == 1
    assert '字面量 \\n\\n' in capsys.readouterr().err

    store = Store(db)
    try:
        assert store.notes('demo') == []
    finally:
        store.close()


def test_render_embeds_view_prefs_with_script_escape(db):
    store = Store(db)
    store.create_project('demo', '嵌入偏好')
    snapshot = store.snapshot()
    store.close()

    page = render(snapshot, view_prefs={'order': ['demo'], 'pinned': []})
    assert 'window.__BOARD_VIEW__ = {"order": ["demo"], "pinned": []};' in page

    hostile = render(snapshot, view_prefs={'order': ['x</script><script>alert(1)'], 'pinned': []})
    assert '<\\/script>' in hostile
    assert 'x</script>' not in hostile

    bare = render(snapshot)
    assert 'window.__BOARD_VIEW__ = {' not in bare


def test_cli_export_embeds_view_prefs(db, tmp_path, capsys):
    from taskboard.store import save_view_prefs

    assert run(db, 'init', 'demo', '--name', '导出嵌入') == 0
    save_view_prefs(db, {'order': ['demo'], 'pinned': ['demo']})
    out = tmp_path / 'board.html'
    assert run(db, 'export', '--out', str(out)) == 0
    capsys.readouterr()

    page = out.read_text(encoding='utf-8')
    assert 'window.__BOARD_VIEW__ = {"order": ["demo"], "pinned": ["demo"]};' in page


def test_render_bridge_mode_clicks_status_via_native_bridge(db):
    store = Store(db)
    store.create_project('demo', '桥接模式')
    store.add_task('demo', '可点状态', accept='通过验收')
    snapshot = store.snapshot()
    store.close()

    page = render(snapshot, bridge=True)
    assert 'class="chip todo status-button"' in page
    assert 'title="点击修改状态" aria-haspopup="menu" aria-expanded="false"' in page
    assert 'id="status-menu"' in page
    assert "item.setAttribute('aria-checked', String(current))" in page
    assert 'window.__boardSetStatus' in page
    assert 'handlers.boardStatus.postMessage' in page
    assert 'data-csrf' not in page  # 桥接模式没有 serve 的写入 API
    assert 'class="detail-button"' not in page  # 详情依赖 /api,桥接导出不含

    plain = render(snapshot)
    assert 'class="chip todo status-button"' not in plain
    assert 'id="status-menu"' not in plain


def test_cli_export_bridge_flag(db, tmp_path, capsys):
    assert run(db, 'init', 'demo', '--name', '桥接导出') == 0
    assert run(db, 'add', '点我改状态', '-p', 'demo') == 0
    capsys.readouterr()

    out = tmp_path / 'bridge.html'
    assert run(db, 'export', '--bridge', '--out', str(out)) == 0
    page = out.read_text(encoding='utf-8')
    assert 'status-button' in page and 'handlers.boardStatus.postMessage' in page

    plain_out = tmp_path / 'plain.html'
    assert run(db, 'export', '--out', str(plain_out)) == 0
    assert 'class="chip todo status-button"' not in plain_out.read_text(encoding='utf-8')
