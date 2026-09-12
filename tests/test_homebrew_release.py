import hashlib
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'prepare_homebrew_release.py'


def prepare(output_dir: Path):
    return subprocess.run(
        [
            sys.executable, str(SCRIPT), '--repository', 'example/taskboard',
            '--output-dir', str(output_dir),
        ],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )


def test_prepare_homebrew_release_is_deterministic_and_complete(tmp_path):
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    prepare(first)
    prepare(second)

    archive_name = 'taskboard-0.1.0.tar.gz'
    archive = first / archive_name
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert archive.read_bytes() == (second / archive_name).read_bytes()

    with tarfile.open(archive, 'r:gz') as bundle:
        names = set(bundle.getnames())
    assert 'taskboard-0.1.0/taskboard/cli.py' in names
    assert 'taskboard-0.1.0/.agents/skills/taskboard/SKILL.md' in names

    formula = (first / 'taskboard.rb').read_text(encoding='utf-8')
    assert 'https://github.com/example/taskboard/releases/download/v0.1.0/' in formula
    assert f'sha256 "{digest}"' in formula
    assert 'depends_on "python@3.13"' in formula
    assert 'license "MIT"' in formula
    assert '@REPOSITORY@' not in formula and '@SHA256@' not in formula
    # skill 装进 libexec/.agents/skills,brew 安装后 board skill-sync 才找得到源目录
    assert '(libexec/".agents/skills").install ".agents/skills/taskboard"' in formula
    assert 'skill-sync' in formula


def test_prepare_homebrew_release_rejects_mismatched_version(tmp_path):
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT), '--repository', 'example/taskboard',
            '--version', '9.9.9', '--output-dir', str(tmp_path),
        ],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert 'does not match pyproject.toml' in result.stderr


def test_release_workflow_updates_owner_tap_after_release():
    workflow = (ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8')
    assert '${{ github.repository_owner }}/homebrew-tap' in workflow
    assert 'HOMEBREW_TAP_TOKEN' in workflow
    assert 'gh release create' in workflow
    assert 'Formula/taskboard.rb' in workflow
