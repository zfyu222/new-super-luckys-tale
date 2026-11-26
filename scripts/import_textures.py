"""Reinsert visually approved textures into the Steam build's Unity resources."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import sys

from PIL import Image
import UnityPy

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parents[1] / "Tools/image_text"))
from core import pixel_hash


def relative_path(value):
    path = Path(value)
    if path.is_absolute() or path.drive or ".." in path.parts or not path.parts:
        raise ValueError(f"Invalid manifest path {value!r}")
    return path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path, original_dir):
    env = UnityPy.Environment(path=str(original_dir))
    root = env.load_file(path.read_bytes(), name=str(original_dir / path.name))
    return root, {(Path(obj.assets_file.name).name, obj.path_id): obj for obj in env.objects
                  if obj.type.name == "Texture2D"}


def texture_edit(obj, origin, replacement, source_image):
    texture = obj.parse_as_object()
    if texture.m_Name != origin["texture_name"] or pixel_hash(texture.image.convert("RGBA")) != source_image:
        raise ValueError(f"Original texture differs from reviewed snapshot: {texture.m_Name}/{obj.path_id}")
    if replacement.size != (texture.m_Width, texture.m_Height):
        raise ValueError(f"Dimensions changed: {texture.m_Name}")
    mip_count = texture.m_MipCount or 1
    # Use uncompressed RGBA32 for reviewed pixels, keeping the original mip count.
    # UnityPy's generic encoder caps small mip levels, so append levels explicitly.
    texture.set_image(replacement, target_format=4)
    pixels = [texture.image_data]
    for level in range(1, mip_count):
        size = (max(1, replacement.width >> level), max(1, replacement.height >> level))
        scaled = replacement.resize(size, Image.Resampling.LANCZOS)
        pixels.append(scaled.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes())
    texture.image_data = b"".join(pixels)
    texture.m_CompleteImageSize = len(texture.image_data)
    texture.m_MipCount = mip_count
    if texture.m_MipMap is not None:
        texture.m_MipMap = mip_count > 1
    texture.save()
    return mip_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=PROJECT / "Game")
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--base", type=Path, help="Previously rebuilt text/font resources")
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    manifest_file = args.patch / "IMAGE_PATCH_MANIFEST.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if (manifest.get("mode") != "texture"
            or manifest.get("visual_review", {}).get("status") != "static_pass"):
        raise ValueError("An approved visual texture payload is required")
    source_sets = {}
    for entry in manifest["entries"]:
        key = entry["image_id"]
        if source_sets.setdefault(key, entry["sources"]) != entry["sources"]:
            raise ValueError(f"Inconsistent source provenance for {key}")
    groups = defaultdict(dict)
    for row in manifest["files"]:
        png = args.patch / relative_path(row["path"])
        if sha(png.read_bytes()) != row["sha256"]:
            raise ValueError(f"Reviewed texture changed: {png}")
        for source in source_sets[row["image_id"]]:
            origin = source["provenance"]
            path = relative_path(origin["target_path"])
            key = (Path(origin["serialized_file"]).name, int(origin["path_id"]))
            if key in groups[path]:
                raise ValueError(f"Duplicate replacement for {path}/{key}")
            groups[path][key] = origin, png, row["image_id"]
    if args.destination.exists():
        raise FileExistsError(args.destination)
    if args.base:
        shutil.copytree(args.base, args.destination)
    else:
        args.destination.mkdir(parents=True)
    records = []
    for path, edits in sorted(groups.items()):
        original = args.game / path
        target = args.destination / path
        layer = target if target.exists() else original
        root, objects = load(layer, original.parent)
        expected = {}
        for key, (origin, png, source_image) in edits.items():
            with Image.open(png) as handle:
                replacement = handle.convert("RGBA")
            transparent = replacement.getchannel("A").point(lambda alpha: 255 if alpha == 0 else 0)
            replacement.paste((0, 0, 0, 0), (0, 0, replacement.width, replacement.height), transparent)
            count = texture_edit(objects[key], origin, replacement, source_image)
            expected[key] = (pixel_hash(replacement), count)
        bundle = root.__class__.__name__ == "BundleFile"
        payload = root.save(packer="lz4") if bundle else root.save()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        _, read_back = load(target, original.parent)
        for key, (expected_id, mip_count) in expected.items():
            texture = read_back[key].parse_as_object()
            if pixel_hash(texture.image.convert("RGBA")) != expected_id or texture.m_MipCount != mip_count:
                raise ValueError(f"Texture did not round-trip: {path}/{key}")
        records.append(dict(path=path.as_posix(), textures=len(expected), original_sha256=sha(original.read_bytes()),
                            patched_sha256=sha(payload)))
        print(path, len(expected), flush=True)
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
