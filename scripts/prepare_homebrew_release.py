#!/usr/bin/env python3
"""Build a deterministic source archive and render the Homebrew Formula."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
PROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"\s*$', re.MULTILINE)


def project_version(pyproject: Path) -> str:
    match = PROJECT_VERSION_RE.search(pyproject.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"cannot find project version in {pyproject}")
    return match.group(1)


def render_formula(template: Path, output: Path, *, repository: str, version: str,
                   url: str, sha256: str) -> None:
    text = template.read_text(encoding="utf-8")
    replacements = {
        "@REPOSITORY@": repository,
        "@VERSION@": version,
        "@URL@": url,
        "@SHA256@": sha256,
    }
    for token, value in replacements.items():
        text = text.replace(token, value)
    unresolved = sorted(set(re.findall(r"@[A-Z_]+@", text)))
    if unresolved:
        raise SystemExit(f"unresolved formula tokens: {', '.join(unresolved)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True, help="GitHub owner/repository")
    parser.add_argument("--version", help="release version; defaults to pyproject.toml")
    parser.add_argument("--revision", default="HEAD", help="Git revision to archive")
    parser.add_argument("--output-dir", default="dist/homebrew")
    parser.add_argument("--url", help="archive URL override for local Formula tests")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    repository = args.repository.strip()
    if not REPOSITORY_RE.fullmatch(repository):
        raise SystemExit("--repository must look like owner/repository")
    version = args.version or project_version(root / "pyproject.toml")
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"invalid version: {version}")
    expected = project_version(root / "pyproject.toml")
    if version != expected:
        raise SystemExit(f"version {version} does not match pyproject.toml {expected}")

    output_dir = (root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"taskboard-{version}.tar.gz"
    prefix = f"taskboard-{version}/"

    with tempfile.TemporaryDirectory(prefix="taskboard-release-") as temp_dir:
        tar_path = Path(temp_dir) / "source.tar"
        with tar_path.open("wb") as handle:
            subprocess.run(
                ["git", "archive", "--format=tar", f"--prefix={prefix}", args.revision],
                cwd=root, check=True, stdout=handle,
            )
        with tar_path.open("rb") as source, archive.open("wb") as target:
            with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
                while chunk := source.read(1024 * 1024):
                    compressed.write(chunk)

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    url = args.url or (
        f"https://github.com/{repository}/releases/download/v{version}/{archive.name}"
    )
    formula = output_dir / "taskboard.rb"
    render_formula(
        root / "packaging/homebrew/taskboard.rb.in", formula,
        repository=repository, version=version, url=url, sha256=digest,
    )
    print(f"archive={archive}")
    print(f"sha256={digest}")
    print(f"formula={formula}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
