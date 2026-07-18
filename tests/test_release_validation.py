from __future__ import annotations

import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path


VALIDATOR = Path(__file__).parents[1] / "scripts" / "validate-release-tag.sh"
ARTIFACT_VALIDATOR = (
    Path(__file__).parents[1] / "scripts" / "validate-release-artifacts.py"
)


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


def make_repository(tmp_path: Path, version: str = "0.2.133") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run("git", "init", "-b", "main", cwd=repo)
    run("git", "config", "user.email", "release-test@fleet.ai", cwd=repo)
    run("git", "config", "user.name", "Release Test", cwd=repo)
    (repo / "scripts").mkdir()
    shutil.copy2(VALIDATOR, repo / "scripts" / VALIDATOR.name)
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "fleet-python"\nversion = "{version}"\n'
    )
    run("git", "add", ".", cwd=repo)
    run("git", "commit", "-m", "initial", cwd=repo)
    run("git", "update-ref", "refs/remotes/origin/main", "HEAD", cwd=repo)
    return repo


def validate(repo: Path, tag: str) -> subprocess.CompletedProcess[str]:
    return run(
        "bash",
        "scripts/validate-release-tag.sh",
        tag,
        cwd=repo,
        check=False,
    )


def test_detached_release_tag_must_be_ancestor_of_origin_main(tmp_path: Path) -> None:
    repo = make_repository(tmp_path)
    run("git", "switch", "-c", "unmerged-release", cwd=repo)
    (repo / "release-only.txt").write_text("not on main\n")
    run("git", "add", ".", cwd=repo)
    run("git", "commit", "-m", "unmerged release", cwd=repo)
    run("git", "tag", "fleet-python-v0.2.133", cwd=repo)
    run("git", "checkout", "--detach", "fleet-python-v0.2.133", cwd=repo)

    result = validate(repo, "fleet-python-v0.2.133")

    assert result.returncode != 0
    assert "not reachable from origin/main" in result.stdout + result.stderr


def test_detached_release_tag_on_origin_main_is_valid(tmp_path: Path) -> None:
    repo = make_repository(tmp_path)
    run("git", "tag", "fleet-python-v0.2.133", cwd=repo)
    run("git", "checkout", "--detach", "fleet-python-v0.2.133", cwd=repo)

    result = validate(repo, "fleet-python-v0.2.133")

    assert result.returncode == 0, result.stdout + result.stderr


def test_tag_must_match_pyproject_version(tmp_path: Path) -> None:
    repo = make_repository(tmp_path, version="0.2.132")
    run("git", "tag", "fleet-python-v0.2.133", cwd=repo)
    run("git", "checkout", "--detach", "fleet-python-v0.2.133", cwd=repo)

    result = validate(repo, "fleet-python-v0.2.133")

    assert result.returncode != 0
    assert "does not match pyproject.toml" in result.stdout + result.stderr


def write_dist(dist: Path, version: str) -> None:
    dist.mkdir()
    metadata = f"Metadata-Version: 2.4\nName: fleet-python\nVersion: {version}\n"
    wheel = dist / f"fleet_python-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"fleet_python-{version}.dist-info/METADATA", metadata)

    package = dist / f"fleet_python-{version}"
    package.mkdir()
    (package / "PKG-INFO").write_text(metadata)
    egg_info = package / "fleet_python.egg-info"
    egg_info.mkdir()
    (egg_info / "PKG-INFO").write_text(metadata)
    with tarfile.open(dist / f"fleet_python-{version}.tar.gz", "w:gz") as archive:
        archive.add(package, arcname=package.name)


def validate_artifacts(
    dist: Path, version: str
) -> subprocess.CompletedProcess[str]:
    return run(
        "python",
        str(ARTIFACT_VALIDATOR),
        "--dist-dir",
        str(dist),
        "--version",
        version,
        cwd=dist.parent,
        check=False,
    )


def test_wheel_and_sdist_versions_must_match_release(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    write_dist(dist, "0.2.133")

    result = validate_artifacts(dist, "0.2.133")

    assert result.returncode == 0, result.stdout + result.stderr


def test_mismatched_artifact_version_is_rejected(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    write_dist(dist, "0.2.132")

    result = validate_artifacts(dist, "0.2.133")

    assert result.returncode != 0
    assert "expected 0.2.133" in result.stdout + result.stderr
