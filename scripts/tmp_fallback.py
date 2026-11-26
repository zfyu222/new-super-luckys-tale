"""Add missing translated glyphs to a global fallback for the game's legacy TMP."""

import argparse
import csv
from pathlib import Path
import shutil
import tempfile

import cv2
from fontTools.ttLib import TTFont
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator

PROJECT = Path(__file__).resolve().parents[1]
FONT = PROJECT.parents[1] / "Tools/Fonts/NotoSC/NotoSansSC-variable.ttf"
RESOURCES = Path("nslt_Data/resources.assets")
SHARED = Path("nslt_Data/sharedassets0.assets")
SETTINGS_ID = 1616
FALLBACK_ID = 29
VERSION = "2017.4.36f1"
GLYPH_SIZE = 104
PADDING = 5


def load(path, generator, *, in_memory=False):
    env = UnityPy.load(path.read_bytes() if in_memory else str(path))
    env.typetree_generator = generator
    return {obj.path_id: obj for obj in env.objects}


def text_tree(obj, nodes):
    result = obj.read_typetree(nodes=nodes)
    raw = obj.get_raw_data()
    obj.save_typetree(result, nodes=nodes)
    if obj.get_raw_data() != raw:
        raise ValueError(f"Type tree changes original object {obj.path_id}")
    return result


def atlas_glyphs(alpha, characters, font_file):
    font = ImageFont.truetype(str(font_file), GLYPH_SIZE)
    font.set_variation_by_axes([560])
    with TTFont(font_file) as tt:
        coverage = tt.getBestCmap()
    missing = sorted(set(characters) - coverage.keys())
    if missing:
        raise ValueError(f"Font has no glyphs for {''.join(map(chr, missing))}")
    old_width, old_height = alpha.size
    # Select a width from a conservative upper bound on glyph shelf packing.
    cell = GLYPH_SIZE + 2 * PADDING + 2
    capacity = (old_width // cell) * ((old_height - GLYPH_SIZE - PADDING) // cell)
    width = old_width if len(characters) <= capacity else old_width * 2
    atlas = Image.new("L", (width, old_height * 2))
    atlas.paste(alpha, (0, 0))
    # Leave a blank band below the old atlas for original out-of-bounds spaces.
    x, y, shelf = 0, old_height + GLYPH_SIZE + PADDING, 0
    glyphs = []
    for codepoint in sorted(characters):
        char = chr(codepoint)
        left, top, right, bottom = font.getbbox(char, anchor="ls")
        w, h = max(right - left, 1), max(bottom - top, 1)
        tile_w, tile_h = w + 2 * PADDING, h + 2 * PADDING
        if x + tile_w > width:
            x, y, shelf = 0, y + shelf + 1, 0
        if y + tile_h > atlas.height:
            raise ValueError("Translated glyphs exceed the fallback atlas capacity")
        mask = Image.new("L", (tile_w, tile_h))
        ImageDraw.Draw(mask).text((PADDING-left, PADDING-top), char, fill=255, font=font, anchor="ls")
        inside = (np.asarray(mask) >= 128).astype("uint8")
        inner = cv2.distanceTransform(inside, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        outer = cv2.distanceTransform(1-inside, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        signed = inner - outer + 0.5 - inside
        sdf = np.clip(np.rint(127.5 + signed * (127.5 / PADDING)), 0, 255).astype("uint8")
        atlas.paste(Image.fromarray(sdf), (x, y))
        glyphs.append(dict(id=codepoint, x=x+PADDING, y=y+PADDING, width=w, height=h,
                           xOffset=left, yOffset=-top, xAdvance=font.getlength(char), scale=1.0))
        x += tile_w + 1
        shelf = max(shelf, tile_h)
    return atlas, glyphs


def non_latin(csv_path):
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        return {ord(c) for row in csv.reader(handle) for text in row for c in text
                if ord(c) >= 0x2000 and c.isprintable() and not c.isspace()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, default=PROJECT / "Game")
    parser.add_argument("--translated", type=Path, required=True)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--font", type=Path, default=FONT)
    args = parser.parse_args()

    generator = TypeTreeGenerator(VERSION)
    generator.load_local_game(str(args.game))
    original_settings = load(args.game / RESOURCES, generator)[SETTINGS_ID]
    settings_nodes = original_settings._get_typetree_node(None)
    resources = load(args.resources, generator, in_memory=True)
    settings_obj = resources[SETTINGS_ID]
    settings = text_tree(settings_obj, settings_nodes)
    if settings["m_Name"] != "TMP Settings" or settings["m_defaultFontAsset"]["m_FileID"] != 2:
        raise ValueError("Unexpected global TMP settings")
    if settings_obj.assets_file.externals[1].name.lower() != SHARED.name:
        raise ValueError("TMP fallback external file reference changed")
    pointer = {"m_FileID": 2, "m_PathID": FALLBACK_ID}
    if pointer not in settings["m_fallbackFontAssets"]:
        settings["m_fallbackFontAssets"].append(pointer)
    settings_obj.save_typetree(settings, nodes=settings_nodes)

    shared = load(args.game / SHARED, generator)
    font_obj = shared[FALLBACK_ID]
    font_nodes = font_obj._get_typetree_node(None)
    data = text_tree(font_obj, font_nodes)
    if data["m_Name"] != "JapaneseGameplayFontTMP":
        raise ValueError("Unexpected fallback font asset")
    existing = {g["id"] for g in data["m_glyphInfoList"]}
    wanted = non_latin(args.translated)
    texture_obj = shared[data["atlas"]["m_PathID"]]
    texture = texture_obj.parse_as_object()
    if texture.m_TextureFormat != 1 or texture.m_MipCount != 1:
        raise ValueError("Unexpected type of fallback font atlas")
    alpha = texture.image.getchannel("A")
    atlas, glyphs = atlas_glyphs(alpha, wanted - existing, args.font)
    rgba = Image.new("RGBA", atlas.size)
    rgba.putalpha(atlas)
    texture.set_image(rgba, target_format=1)
    texture.save()
    data["m_glyphInfoList"].extend(glyphs)
    data["m_fontInfo"].update(AtlasWidth=atlas.width, AtlasHeight=atlas.height,
                              CharacterCount=len(data["m_glyphInfoList"]))
    font_obj.save_typetree(data, nodes=font_nodes)
    material = shared[data["material"]["m_PathID"]].parse_as_object()
    dimensions = {"_TextureWidth": float(atlas.width), "_TextureHeight": float(atlas.height)}
    material.m_SavedProperties.m_Floats = [
        (name, dimensions.get(name, val)) for name, val in material.m_SavedProperties.m_Floats]
    material.save()

    if args.destination.exists():
        raise FileExistsError(args.destination)
    with tempfile.TemporaryDirectory(dir=args.destination.parent) as temp:
        stage = Path(temp)
        for rel, obj in ((RESOURCES, settings_obj), (SHARED, font_obj)):
            output = stage / rel
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(obj.assets_file.save())
        new_settings = load(stage / RESOURCES, generator, in_memory=True)[SETTINGS_ID].read_typetree(nodes=settings_nodes)
        new_shared = load(stage / SHARED, generator, in_memory=True)
        new_font = new_shared[FALLBACK_ID].read_typetree(nodes=font_nodes)
        rebuilt = new_shared[texture_obj.path_id].parse_as_object().image.getchannel("A")
        if (pointer not in new_settings["m_fallbackFontAssets"]
                or not wanted.issubset({g["id"] for g in new_font["m_glyphInfoList"]})
                or rebuilt.tobytes() != atlas.tobytes()):
            raise ValueError("Fallback failed glyph coverage or atlas round-trip verification")
        shutil.copytree(stage, args.destination)
    print(f"Verified fallback for {len(wanted)} characters, including {len(glyphs)} added glyphs.")


if __name__ == "__main__":
    main()
