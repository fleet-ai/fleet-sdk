#!/usr/bin/env python3
"""Verify that the publishable wheel and sdist match the approved release."""

from __future__ import annotations

import argparse
import email
import sys
import tarfile
import zipfile
from pathlib import Path


def metadata_version(contents: bytes) -> str:
    message = email.message_from_bytes(contents)
    version = message.get("Version")
    if not version:
        raise ValueError("package metadata has no Version field")
    return version


def wheel_version(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        metadata_files = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise ValueError(f"{path.name} contains {len(metadata_files)} METADATA files")
        return metadata_version(archive.read(metadata_files[0]))


def sdist_version(path: Path) -> str:
    with tarfile.open(path, "r:gz") as archive:
        metadata_files = [
            member
            for member in archive.getmembers()
            if member.name.endswith("/PKG-INFO")
            and len(Path(member.name).parts) == 2
        ]
        if len(metadata_files) != 1:
            raise ValueError(f"{path.name} contains {len(metadata_files)} PKG-INFO files")
        extracted = archive.extractfile(metadata_files[0])
        if extracted is None:
            raise ValueError(f"could not read metadata from {path.name}")
        return metadata_version(extracted.read())


def validate(dist_dir: Path, expected_version: str) -> None:
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError(
            f"expected exactly one wheel and one sdist, found {len(wheels)} wheel(s) and {len(sdists)} sdist(s)"
        )

    versions = {
        wheels[0].name: wheel_version(wheels[0]),
        sdists[0].name: sdist_version(sdists[0]),
    }
    mismatches = {name: version for name, version in versions.items() if version != expected_version}
    if mismatches:
        details = ", ".join(f"{name}={version}" for name, version in mismatches.items())
        raise ValueError(f"artifact version mismatch: expected {expected_version}; {details}")

    print(f"Validated fleet-python {expected_version}: {wheels[0].name}, {sdists[0].name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    try:
        validate(args.dist_dir, args.version)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
