"""Git 只读探测。

取 SHA 的逻辑集中在这里:此前 CLI 按进程 cwd 取、serve 按任务第一个仓库取,
两处不一致导致完成记录常常指向别的仓库或别的任务的提交。
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(repo: str | Path | None, argv: list[str], timeout: int = 10) -> str | None:
    try:
        result = subprocess.run(
            ['git', '-C', str(repo or Path.cwd()), *argv],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _rev_parse_raw(repo: str | Path | None, argv: list[str]) -> str | None:
    out = _run_git(repo, ['rev-parse', *argv], timeout=3)
    return out.strip() or None if out is not None else None


def _rev_parse(repo: str | Path | None, rev: str) -> str | None:
    return _rev_parse_raw(repo, ['--short', '--verify', '--quiet', rev])


def head_sha(repo: str | Path | None = None) -> str | None:
    """仓库当前短 sha;不在仓库里或 git 不可用时返回 None。"""
    return _rev_parse(repo, 'HEAD')


def has_commit(repo: str | Path | None, sha: str | None) -> bool:
    """sha 指向的提交在该仓库里是否还在。squash/rebase 且 gc 之后会变 False。"""
    if not sha:
        return False
    return _rev_parse(repo, f'{sha}^{{commit}}') is not None


def diff_argv(base: str, head: str | None, against_worktree: bool) -> list[str]:
    """在办任务比到工作区(含未提交):审 Agent 产出时,改动往往还没提交。"""
    return [base] if against_worktree else [f'{base}..{head}']


def diff_numstat(repo: str | Path, base: str | None, head: str | None,
                 against_worktree: bool = False) -> list[dict] | None:
    """区间的逐文件增删行数;区间不可用(缺端点或 sha 已失效)时返回 None。"""
    if not base or not (head or against_worktree):
        return None
    try:
        result = subprocess.run(
            ['git', '-C', str(repo), 'diff', '--numstat',
             *diff_argv(base, head, against_worktree)],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    files = []
    for line in result.stdout.splitlines():
        parts = line.split('\t')
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        binary = '-' in (added, deleted)
        files.append({
            'path': path,
            'added': 0 if binary else int(added),
            'deleted': 0 if binary else int(deleted),
            'binary': binary,
        })
    return files


def _common_dir(path: str | Path) -> str | None:
    """仓库的共享 .git 目录;同一仓库的多个工作树返回同一个值。"""
    absolute = _rev_parse_raw(path, ['--path-format=absolute', '--git-common-dir'])
    if absolute:
        return absolute
    relative = _rev_parse_raw(path, ['--git-common-dir'])
    if not relative:
        return None
    return str((Path(path) / relative).resolve())


def worktree_for(repo: str | Path) -> Path:
    """这次该看哪个工作树:cwd 属于同一个仓库就用 cwd,否则用登记路径。

    Agent 常在 git worktree 里干活(Claude Code 默认就这么开),此时仓库主检出的 HEAD
    和工作区都不是这次改动。判据是两边 --git-common-dir 相同——即同一个仓库的另一个
    工作树,而不是"随便哪个 cwd",这与此前按 cwd 乱取 sha 的缺陷不是一回事。
    """
    here = Path.cwd()
    mine = _common_dir(here)
    return here if mine and mine == _common_dir(repo) else Path(repo)


def worktree_head_sha(repo: str | Path) -> str | None:
    tree = worktree_for(repo)
    return head_sha(tree) or head_sha(repo)


def untracked_files(repo: str | Path, limit: int = 50) -> list[dict]:
    """未跟踪的新文件。

    过滤直接用 git 自己的 --exclude-standard(.gitignore + .git/info/exclude +
    全局 core.excludesFile),不在看板里重做一套排除规则——那只会变成 gitignore 的
    劣质副本,且和 git status 看到的不一致。剩下的噪音是仓库卫生问题,该改 gitignore。
    """
    listed = _run_git(repo, ['ls-files', '--others', '--exclude-standard'])
    if listed is None:
        return []
    files = []
    for path in listed.splitlines()[:limit]:
        full = Path(repo) / path
        try:
            raw = full.read_bytes()
        except OSError:
            continue
        binary = b'\x00' in raw[:8000]
        files.append({
            'path': path,
            'added': 0 if binary else raw.count(b'\n') + (0 if raw.endswith(b'\n') else 1),
            'deleted': 0,
            'binary': binary,
        })
    return files


def commits_between(repo: str | Path, base: str | None, head: str | None,
                    limit: int = 200) -> list[dict] | None:
    """区间内的提交,新的在前。

    提交消息是 Agent 已经付过成本的分段和意图说明,按提交读比读一整块 diff 便宜,
    所以审查包先给提交列表,合并 diffstat 只作为总量参考。
    """
    if not (base and head):
        return None
    out = _run_git(repo, ['log', '--format=%x00%h%x1f%s%x1f%p', '--numstat',
                          f'{base}..{head}'], timeout=15)
    if out is None:
        return None
    commits = []
    for block in out.split('\x00'):
        header, _, body = block.strip('\n').partition('\n')
        parts = header.split('\x1f')
        if len(parts) != 3:
            continue
        sha, subject, parents = parts
        added = deleted = 0
        for line in body.splitlines():
            cols = line.split('\t')
            if len(cols) == 3 and '-' not in (cols[0], cols[1]):
                added += int(cols[0])
                deleted += int(cols[1])
        commits.append({
            'sha': sha, 'subject': subject, 'added': added, 'deleted': deleted,
            # 合并提交在 git log --numstat 下不产出行数,单独标出来免得看成空改动
            'merge': len(parents.split()) > 1,
        })
        if len(commits) >= limit:
            break
    return commits


def dirty_files(repo: str | Path) -> list[str]:
    """工作区里还没提交的文件;git status 本身就不列被忽略的。"""
    out = _run_git(repo, ['status', '--porcelain'])
    if out is None:
        return []
    return [line[3:] for line in out.splitlines() if line.strip()]
