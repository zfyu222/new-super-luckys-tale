"""Isolate the painted fox tail on the reviewed primary title texture."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw

TAIL_OUTLINE = [
    (194, 824), (194, 793), (202, 741), (215, 684), (241, 630), (273, 584),
    (313, 546), (353, 521), (404, 500), (469, 485), (530, 480), (608, 480),
    (655, 472), (700, 459), (736, 444), (761, 422), (780, 391), (796, 348),
    (804, 328), (813, 343), (823, 378), (826, 416), (824, 446), (816, 489),
    (800, 531), (775, 568), (742, 600), (698, 627), (645, 651), (586, 671),
    (521, 687), (452, 711), (387, 733), (327, 758), (270, 785), (222, 810),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cleanup", type=Path)
    args = parser.parse_args()
    path = args.cleanup / "IMAGE_PATCH_MANIFEST.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    matches = [row for row in data["entries"] if any(
        src["provenance"]["texture_name"] == "Logo" for src in row["sources"])]
    entry, = matches
    file, = (item for item in data["files"] if item["image_id"] == entry["image_id"])
    source = Path(file["source"])
    if sha(source) != file["source_sha256"] or entry["image_id"] != (
            "88205c4fd9e5b604e5894089fbedc53367b6e01f74d8d18d2e13515896f3ce02"):
        raise ValueError("Hand-traced tail applies only to the reviewed source logo")
    with Image.open(source) as source_image:
        original = source_image.convert("RGBA")
    marking = Image.new("L", (original.width * 3, original.height * 3))
    ImageDraw.Draw(marking).polygon([(3*x, 3*y) for x, y in TAIL_OUTLINE], fill=255)
    preserved = marking.resize(original.size, Image.Resampling.LANCZOS)
    rgb = np.asarray(original, dtype=np.int16)[..., :3]
    red, green, blue = rgb.transpose(2, 0, 1)
    paint = ((red > 132) & (red >= green + 12) & (red >= blue + 64))
    white_tip = (rgb.min(axis=2) > 210) & (red >= blue - 24)
    palette = Image.fromarray(((paint | white_tip) * 255).astype("uint8"))
    preserved = ImageChops.multiply(preserved, palette)
    alpha = ImageChops.multiply(original.getchannel("A"), preserved)
    clean = original.copy()
    clean.putalpha(alpha)
    mask = ImageChops.subtract(original.getchannel("A"), alpha).point(lambda a: 255 if a else 0)
    target, mask_target = args.cleanup / file["path"], args.cleanup / file["mask"]
    clean.save(target)
    mask.save(mask_target)
    file["sha256"], file["mask_sha256"] = sha(target), sha(mask_target)
    entry["rendering"]["cleanup_note"] = "手绘路径分离原图狐尾和英文标题，清字后保持原狐尾像素与白色尾尖。"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
