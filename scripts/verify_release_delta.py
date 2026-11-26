"""Replay install, upgrade and uninstall in a disposable Steam-shaped fixture."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import zipfile


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--temp-parent", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="NSLT 汉化 测试 ", dir=args.temp_parent) as temp:
        game = Path(temp) / "游戏 目录"
        game.mkdir()
        with zipfile.ZipFile(args.zip) as package:
            require(package.testzip() is None, "ZIP CRC check failed")
            members = package.namelist()
            require(len(members) == len(set(members)), "Duplicate ZIP members")
            require(all(not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts
                        and "\\" not in n and ":" not in n for n in members), "Unsafe archive member")
            sums = dict(line.split("  ", 1)[::-1] for line in
                        package.read("SHA256SUMS.txt").decode("utf-8").splitlines())
            require(set(members) == set(sums) | {"SHA256SUMS.txt"}, "ZIP has unlisted members")
            package.extractall(game)
        for path, sha in sums.items():
            require(digest(game / path) == sha, f"Archive checksum mismatch: {path}")
        manifest = json.loads((game / "PATCH_MANIFEST.json").read_text(encoding="utf-8"))
        files = manifest["files"]
        require(all(row["path"] not in members and row["archive_path"].endswith(".vcdiff")
                    and sums[row["archive_path"]] == row["delta_sha256"] for row in files),
                "Unexpected game resource in player archive")

        shutil.copyfile(args.exe, game / "nslt.exe")
        for row in files:
            target = game / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.originals / row["path"], target)
        save = game / "nslt_Data/test-save.ini"
        save.write_bytes(b"untouched fixture")
        state_path = game / ".zfy-localization/state.json"

        def check_game(field):
            for row in files:
                require(digest(game / row["path"]) == row[field], f'{field}: {row["path"]}')
            require(save.read_bytes() == b"untouched fixture", "Unrelated file changed")

        def action(name, success=True):
            exe = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            run = subprocess.run([str(exe), "-NoProfile", "-ExecutionPolicy", "Bypass",
                                  "-File", str(game / "汉化工具/patch.ps1"), "-Action", name, "-NoLaunch"],
                                 cwd=game, capture_output=True)
            if (run.returncode == 0) != success:
                raise RuntimeError(f"Unexpected {name} result: {run.returncode}, {run.stdout!r}, {run.stderr!r}")
            return run.stdout

        check_game("source_sha256")
        action("install")
        check_game("sha256")
        before = [(game / row["path"]).stat().st_mtime_ns for row in files]
        action("install")
        check_game("sha256")
        require(before == [(game / row["path"]).stat().st_mtime_ns for row in files], "Repeat install rewrote the game")

        # An older script-managed payload differs, but has the same pristine backups.
        prior = files[0]
        target = game / prior["path"]
        target.write_bytes(b"simulated previous version")
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        record = next(row for row in state["records"] if row["path"] == prior["path"])
        record["installed"] = digest(target)
        state_path.write_text(json.dumps(state), encoding="utf-8-sig")
        action("install")
        check_game("sha256")

        action("uninstall")
        check_game("source_sha256")
        action("uninstall")
        check_game("source_sha256")

        delta = game / files[-1]["archive_path"]
        with delta.open("r+b") as handle:
            original_byte = handle.read(1)
            handle.seek(0)
            handle.write(bytes([original_byte[0] ^ 1]))
        action("install", success=False)
        check_game("source_sha256")
        with delta.open("r+b") as handle:
            handle.write(original_byte)

        target = game / files[-1]["path"]
        with target.open("r+b") as handle:
            original_byte = handle.read(1)
        # Use a fresh fixture state so no pristine backups can repair the wrong source.
        state_path.unlink()
        for row in files:
            backed_up = game / ".zfy-localization/original" / row["path"]
            backed_up.unlink()
        with target.open("r+b") as handle:
            handle.write(bytes([original_byte[0] ^ 1]))
        wrong_source = digest(target)
        action("install", success=False)
        require(digest(target) == wrong_source, "Wrong-version input was altered")
        for row in files[:-1]:
            require(digest(game / row["path"]) == row["source_sha256"], "Wrong-version preflight changed another file")
        with target.open("r+b") as handle:
            handle.write(original_byte)
        check_game("source_sha256")
    print("Verified ZIP CRC and hashes, Unicode paths, install, repeat, upgrade, uninstall, and rejected inputs.")


if __name__ == "__main__":
    main()
