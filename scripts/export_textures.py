"""Export Unity Texture2D images with source IDs for OCR and reinsertion."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import UnityPy

PROJECT = Path(__file__).resolve().parents[1]


def sources(game):
    data = game / "nslt_Data"
    return sorted([*data.glob("*.assets"), *data.glob("level[0-9]*"),
                   *(data / "StreamingAssets/Bundles/Windows").iterdir()])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=PROJECT / "Game")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    images = args.out / "images"
    images.mkdir(parents=True, exist_ok=False)
    provenance = {}
    skipped = Counter()
    errors = []
    for path in sources(args.game):
        if not path.is_file():
            continue
        rel = path.relative_to(args.game).as_posix()
        before = len(provenance)
        try:
            environment = UnityPy.load(str(path))
            for obj in environment.objects:
                if obj.type.name != "Texture2D":
                    continue
                try:
                    texture = obj.parse_as_object()
                    if min(texture.m_Width, texture.m_Height) < 20:
                        skipped["axis_below_20px"] += 1
                        continue
                    if re.search(r"(?:^|[_ .-])(?:normal|normals|heightmap|occlusion|lightmap)(?:$|[_ .-])",
                                 texture.m_Name, re.I):
                        skipped["texture_name_marks_noncolor_map"] += 1
                        continue
                    key = f"{rel}/{obj.assets_file.name}/{obj.path_id}"
                    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
                    label = re.sub(r"[^a-zA-Z0-9_-]+", "_", texture.m_Name)[:65]
                    name = f"{label}-{digest}.png"
                    if name in provenance:
                        raise ValueError(f"Duplicate texture identity {key}")
                    texture.image.save(images / name)
                    provenance[name] = {
                        "engine": "Unity", "target_path": rel, "serialized_file": obj.assets_file.name,
                        "path_id": str(obj.path_id), "texture_name": texture.m_Name,
                        "format": texture.m_TextureFormat, "mip_count": texture.m_MipCount,
                    }
                except Exception as exc:
                    errors.append({"file": rel, "path_id": obj.path_id, "error": str(exc)})
        except Exception as exc:
            errors.append({"file": rel, "error": str(exc)})
        print(rel, len(provenance) - before, len(errors), flush=True)
    (args.out / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    (args.out / "export_report.json").write_text(
        json.dumps({"exported": len(provenance), "skipped": skipped, "errors": errors}, indent=2),
        encoding="utf-8")
    print("Exported", len(provenance), "errors", len(errors), flush=True)


if __name__ == "__main__":
    main()
