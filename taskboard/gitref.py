"""Git 只读探测。

取 SHA 的逻辑集中在这里:此前 CLI 按进程 cwd 取、serve 按任务第一个仓库取,
两处不一致导致完成记录常常指向别的仓库或别的任务的提交。
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _rev_parse(repo: str | Path | None, rev: str) -> str | None:
    try:
        result = subprocess.run(
            ['git', '-C', str(repo or Path.cwd()), 'rev-parse', '--short', '--verify',
             '--quiet', rev],
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def head_sha(repo: str | Path | None = None) -> str | None:
    """仓库当前短 sha;不在仓库里或 git 不可用时返回 None。"""
    return _rev_parse(repo, 'HEAD')


def has_commit(repo: str | Path | None, sha: str | None) -> bool:
    """sha 指向的提交在该仓库里是否还在。squash/rebase 且 gc 之后会变 False。"""
    if not sha:
        return False
    return _rev_parse(repo, f'{sha}^{{commit}}') is not None
