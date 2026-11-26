"""Validate, back up and synchronize a built payload with the local Steam copy."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
BUILD_ID = "10670184"


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def allowed(path):
    if path.is_absolute() or path.drive or ".." in path.parts or not path.parts:
        return False
    if len(path.parts) == 2 and path.parts[0] == "nslt_Data":
        return bool(re.fullmatch(r"(resources|sharedassets\d+)\.assets|level\d+", path.name))
    return (len(path.parts) == 5 and path.parts[:4] == ("nslt_Data", "StreamingAssets", "Bundles", "Windows")
            and bool(re.fullmatch(r"[A-Za-z0-9_.-]+", path.name)))


def confirm_game(game):
    if not (game / "nslt.exe").is_file():
        raise ValueError(f"Cannot find nslt.exe in {game}")
    manifest = game.parent.parent / "appmanifest_1038300.acf"
    matches = re.findall(r'"buildid"\s+"(\d+)"', manifest.read_text(encoding="utf-8-sig"), re.I)
    if matches != [BUILD_ID]:
        raise ValueError(f"Game version must be Steam build {BUILD_ID}, found {matches}")
    process = subprocess.run(["tasklist.exe", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq nslt.exe"],
                             capture_output=True, check=True)
    if b'"nslt.exe"' in process.stdout.lower():
        raise RuntimeError("Close New Super Lucky's Tale before synchronizing resources.")


def install(game, payload, manifest, backup):
    if manifest["steam_build"] != BUILD_ID or not manifest["files"]:
        raise ValueError("Payload manifest uses an incompatible build or has no files")
    changes = []
    seen = set()
    for row in manifest["files"]:
        rel = Path(row["path"])
        if not allowed(rel) or rel.as_posix().casefold() in seen:
            raise ValueError(f"Unexpected or duplicate game path: {rel}")
        seen.add(rel.as_posix().casefold())
        original, new = game / rel, payload / rel
        if not original.resolve().is_relative_to(game) or not new.resolve().is_relative_to(payload):
            raise ValueError(f"Path escapes the game or payload directory: {rel}")
        if digest(new) != row["patched_sha256"]:
            raise ValueError(f"Patched file no longer matches the build: {rel}")
        current = digest(original)
        if current == row["patched_sha256"]:
            # A preceding attempt may already have installed this exact payload.
            if digest(backup / rel) != row["original_sha256"]:
                raise ValueError(f"Can't verify the existing original backup: {rel}")
            continue
        if current != row["original_sha256"]:
            raise ValueError(f"Original game file changed since preflight: {rel}")
        changes.append((rel, row))

    with tempfile.TemporaryDirectory(prefix="nslt-localization-", dir=game) as tmp:
        stage = Path(tmp)
        for rel, row in changes:
            saved, staged = backup / rel, stage / rel
            saved.parent.mkdir(parents=True, exist_ok=True)
            staged.parent.mkdir(parents=True, exist_ok=True)
            if not saved.exists():
                with (game / rel).open("rb") as source, saved.open("xb") as destination:
                    shutil.copyfileobj(source, destination)
            if digest(saved) != row["original_sha256"]:
                raise ValueError(f"Could not validate original backup: {rel}")
            shutil.copyfile(payload / rel, staged)
            if digest(staged) != row["patched_sha256"]:
                raise ValueError(f"Could not stage patched file: {rel}")
        confirm_game(game)
        replaced = []
        try:
            for rel, row in changes:
                if digest(game / rel) != row["original_sha256"]:
                    raise ValueError(f"Original changed during staging: {rel}")
                os.replace(stage / rel, game / rel)
                replaced.append((rel, row))
            for row in manifest["files"]:
                if digest(game / row["path"]) != row["patched_sha256"]:
                    raise ValueError(f"Installed file failed verification: {row['path']}")
        except BaseException:
            for rel, row in reversed(replaced):
                restore = stage / rel
                shutil.copyfile(backup / rel, restore)
                if digest(restore) != row["original_sha256"]:
                    raise ValueError(f"Could not revalidate original before restoring: {rel}")
                os.replace(restore, game / rel)
            raise
    return {"verified": len(manifest["files"]), "updated": len(changes), "backup": str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=PROJECT / "Game")
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    game, payload, backup = args.game.resolve(), args.payload.resolve(), args.backup.resolve()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if backup.is_relative_to(game) or payload.is_relative_to(game):
        raise ValueError("Keep build payload and backups in the localization project")
    confirm_game(game)
    lock = game / ".nslt-localization-install.lock"
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    try:
        print(json.dumps(install(game, payload, manifest, backup), ensure_ascii=False))
    finally:
        lock.unlink()


if __name__ == "__main__":
    main()
