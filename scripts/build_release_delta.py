"""Build the Windows release from a tested payload and matching original files."""

import argparse
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parents[1]
RELEASE_SKILL = WORKSPACE / ".agents/skills/game-release-patch/scripts"
UPSTREAM = "https://github.com/jmacd/xdelta/releases/tag/v3.2.2"
UPSTREAM_SHA256 = "d48f7651d86b78fdca397057b46601f89131f37219675df736db70af44ec3379"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path, value, encoding="utf-8"):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding=encoding)


def load_packager():
    spec = importlib.util.spec_from_file_location("release_packager", RELEASE_SKILL / "create_release_patch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_once(script, original, replacement):
    if script.count(original) != 1:
        raise ValueError(f"Shared installer changed at expected insertion point: {original}")
    return script.replace(original, replacement)


def make_installer():
    template = (RELEASE_SKILL / "player_installer.ps1").read_text(encoding="utf-8-sig")
    fragment = (PROJECT / "scripts/player_vcdiff.ps1").read_text(encoding="utf-8")
    template = replace_once(template, "        $newPaths=@{}", fragment + "\n        $newPaths=@{}")
    template = replace_once(
        template,
        "            if((Digest (Within $root $file.archive_path)) -ne $file.sha256)"
        " { throw '补丁文件不完整，请重新解压。' }",
        "",
    )
    template = replace_once(
        template,
        "            CopyChecked (Within $root $file.archive_path) (Within $root $file.path) $file.sha256",
        "            if($materialized.ContainsKey($file.path)) {\n"
        "                CopyChecked $materialized[$file.path] (Within $root $file.path) $file.sha256\n"
        "            } elseif((Digest (Within $root $file.path)) -ne $file.sha256) {\n"
        "                throw '游戏文件在安装期间发生变化。'\n"
        "            }",
    )
    return replace_once(
        template, "finally { if($lock) { $lock.Dispose() } }",
        """finally {
    try {
        if($deltaStage -and [IO.Directory]::Exists($deltaStage)) {
            foreach($directory in [IO.Directory]::GetDirectories($deltaStage)) {
                $slot=Within $deltaStage ([IO.Path]::GetFileName($directory))
                foreach($name in @('original.bin','patch.bin','result.bin')) {
                    [IO.File]::Delete((Within $slot $name))
                }
                [IO.Directory]::Delete($slot)
            }
            [IO.Directory]::Delete($deltaStage)
        }
    } finally { if($lock) { $lock.Dispose() } }
}""",
    )


def run_xdelta(executable, *args):
    env = {key: value for key, value in os.environ.items() if key.upper() != "XDELTA"}
    subprocess.run([str(executable), *map(str, args)], env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--payload-manifest", type=Path, required=True)
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--deltas", type=Path, required=True)
    parser.add_argument("--xdelta-zip", type=Path, required=True)
    parser.add_argument("--license", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    opts = parser.parse_args()
    for name, value in vars(opts).items():
        if isinstance(value, Path):
            setattr(opts, name, value.resolve())
    shared = load_packager()
    sha = shared.sha256
    config = load_json(opts.config)
    tested = load_json(opts.payload_manifest)
    rows = tested["files"]
    pairs = [(opts.payload / row["path"], PurePosixPath(row["path"])) for row in rows]
    shared.check_custom_quality(PROJECT, pairs, config["game_version"], config["platform"])
    if config["launch_mode"] != "original_exe" or config["game_version"] != tested["steam_build"]:
        raise ValueError("Release config does not match the tested Steam build")
    if config["version"] != shared.next_version(PROJECT / "Dispatch", config["chinese_name"]):
        raise ValueError("Release version does not match the next Dispatch version")
    zip_name = f'{config["chinese_name"]}_子非鱼汉化{config["version"]}.zip'
    archive = PROJECT / "Dispatch" / zip_name
    staged = PROJECT / "Dispatch/Files"
    if archive.exists() or staged.exists():
        raise FileExistsError("Keep the existing Dispatch staging directory and release intact")
    for row in rows:
        if sha(opts.originals / row["path"]) != row["original_sha256"]:
            raise ValueError(f'Original changed: {row["path"]}')
    if sha(opts.xdelta_zip) != UPSTREAM_SHA256:
        raise ValueError("Xdelta ZIP does not match the pinned official release")
    if opts.dry_run:
        print(archive)
        for source, dest in pairs:
            print(f"{source} -> 汉化文件/{dest}.vcdiff -> {dest}")
        return

    with tempfile.TemporaryDirectory(prefix="nslt-release-") as tmp:
        scratch = Path(tmp)
        with zipfile.ZipFile(opts.xdelta_zip) as source:
            member, = [entry for entry in source.namelist() if PurePosixPath(entry).name == "xdelta3.exe"]
            (scratch / "xdelta3.exe").write_bytes(source.read(member))
        decoder = encoder = scratch / "xdelta3.exe"
        files = []
        deltas = []
        for row in rows:
            rel = row["path"]
            delta = opts.deltas / f"{rel}.vcdiff"
            if not delta.is_file():
                delta.parent.mkdir(parents=True, exist_ok=True)
                candidate = scratch / "candidate.vcdiff"
                run_xdelta(encoder, "-e", "-A", "-B", "268435456", "-s",
                           opts.originals / rel, opts.payload / rel, candidate)
                shutil.move(candidate, delta)
            restored = scratch / "restored.bin"
            run_xdelta(decoder, "-d", "-s", opts.originals / rel, delta, restored)
            if sha(restored) != row["patched_sha256"]:
                raise ValueError(f"Delta did not reconstruct the tested asset: {rel}")
            restored.unlink()
            deltas.append((row, delta))
        staged.mkdir()
        for row, delta in deltas:
            rel = row["path"]
            target = staged / "汉化文件" / f"{rel}.vcdiff"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(delta, target)
            files.append({"path": rel, "archive_path": target.relative_to(staged).as_posix(),
                          "sha256": row["patched_sha256"], "source_sha256": row["original_sha256"],
                          "delta_sha256": sha(target), "size": target.stat().st_size})
        helper = staged / "汉化工具"
        helper.mkdir()
        shutil.copyfile(decoder, helper / decoder.name)
        shutil.copyfile(opts.license, helper / "xdelta-LICENSE.txt")
        (helper / "xdelta-NOTICE.txt").write_text(
            f"Xdelta 3.2.2. Copyright (C) Joshua MacDonald. Apache License 2.0.\n{UPSTREAM}\n",
            encoding="utf-8")
        (helper / "patch.ps1").write_text(make_installer(), encoding="utf-8-sig")
        save_json(helper / "config.json", {
            "exe": config["exe"], "exe_sha256": config["exe_sha256"],
            "steam_app_id": config["steam_app_id"], "decoder_sha256": sha(decoder),
            "originals": [{"path": row["path"], "sha256": row["source_sha256"]} for row in files],
            "legacy": [{"path": row["path"], "sha256": row["sha256"]} for row in files],
        }, "utf-8-sig")
        for action, label in (("install", "安装汉化"), ("uninstall", "卸载汉化")):
            (staged / f"{label}.cmd").write_text(
                '@echo off\nchcp 65001 >nul\npowershell.exe -NoProfile -ExecutionPolicy Bypass '
                f'-File "%~dp0汉化工具\\patch.ps1" -Action {action}\n'
                'if errorlevel 1 echo 操作失败，请查看上方提示。\npause\n', encoding="utf-8", newline="\r\n")
        auxiliary = [{"path": path.relative_to(staged).as_posix(), "sha256": sha(path), "size": path.stat().st_size}
                     for path in sorted([*helper.iterdir(), *staged.glob("*.cmd")])]
        guide = argparse.Namespace(**config, title=f'[子非鱼Ai汉化]《{config["chinese_name"]}》/《{config["english_name"]}》',
                                   download_url=f'https://github.com/{config["repository"]}/releases/',
                                   feedback_url=config.get("feedback_url"), feedback_name=config.get("feedback_name"))
        (staged / "补丁说明.txt").write_text(shared.make_guide(guide, config["version"], ""), encoding="utf-8-sig")
        manifest = {"archive": zip_name, "created": config["release_date"], "version": config["version"],
                    "files": files, "auxiliary": auxiliary, "install_mode": "vcdiff"}
        save_json(staged / "PATCH_MANIFEST.json", manifest)
        payload_sums = {row["archive_path"]: row["delta_sha256"] for row in files}
        payload_sums.update({row["path"]: row["sha256"] for row in auxiliary})
        for name in ("补丁说明.txt", "PATCH_MANIFEST.json"):
            payload_sums[name] = sha(staged / name)
        (staged / "SHA256SUMS.txt").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in sorted(payload_sums.items())), encoding="utf-8")
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as package:
            for name in sorted([*payload_sums, "SHA256SUMS.txt"]):
                package.write(staged / name, name)
    print(archive)


if __name__ == "__main__":
    main()
