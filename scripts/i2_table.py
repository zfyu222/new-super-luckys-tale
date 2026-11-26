"""Extract and rebuild the I2 language table in Steam build 10670184."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import struct
import sys
import tempfile

import UnityPy
from UnityPy.streams import EndianBinaryReader

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parents[1] / "Tools" / "localization"))
from workflow_resource_occurrences import export_occurrences, project_resolutions, sha

ASSET = "nslt_Data/resources.assets"
OBJECT_ID = 1841
FORMAT_ONLY = re.compile(r"<[^<>]+>|\[/?[A-Za-z][A-Za-z0-9_]*\]")
FORMAT_TAG = re.compile(r"(?<!\()\[(/?)([A-Za-z][A-Za-z0-9_]*)\](?!\))")
RESOURCE_ROWS = {"FONTS", "UI-MENU", "LuckysTale-Bold SDF", "LuckysTale-BoldUS SDF", "LuckysTale-Body SDF"}


def table(path):
    environment = UnityPy.load(str(path))
    obj = next(obj for obj in environment.objects if obj.path_id == OBJECT_ID)
    if obj.type.name != "MonoBehaviour" or obj.assets_file.unity_version != "2017.4.36f1":
        raise ValueError("Unexpected I2 language source object")
    raw = obj.get_raw_data()
    reader = EndianBinaryReader(raw, endian="<")
    reader.Position = 32
    for _ in range(4):
        reader.read_aligned_string()
    reader.Position += 8
    terms = []
    term_count = reader.read_int()
    for _ in range(term_count):
        key = reader.read_aligned_string()
        kind = reader.read_int()
        description = reader.read_aligned_string()
        fields = {}
        for name in ("Languages", "Languages_Touch"):
            values = []
            for _ in range(reader.read_int()):
                start = reader.Position
                source = reader.read_aligned_string()
                values.append((start, reader.Position, source))
            fields[name] = values
        flag_count = reader.read_int()
        flags = reader.read_bytes(flag_count)
        reader.align_stream()
        terms.append((key, kind, description, fields, flags))
    languages = [(reader.read_aligned_string(), reader.read_aligned_string())
                 for _ in range(reader.read_int())]
    if term_count != 2341 or languages[1] != ("English (U.S.)", "en-US"):
        raise ValueError("Unexpected I2 table layout")
    return obj, raw, terms


def occurrences(terms):
    for index, (key, kind, description, fields, _) in enumerate(terms):
        if kind != 0 or key in RESOURCE_ROWS or key.startswith("FormattingStyles/"):
            continue
        for name, values in fields.items():
            if len(values) < 2:
                continue
            start, end, source = values[1]
            if not any(c.isalpha() for c in FORMAT_ONLY.sub("", source)):
                continue
            group = key.split("/", 1)[0] if "/" in key else "Interface"
            resource = f"{ASSET}#{OBJECT_ID}/mTerms/{index}/{name}/en-US/{key}"
            yield dict(resource=resource, source=source, group=group, note=description,
                       text_type="dialogue" if group.startswith("Chapter") else "game text"), start, end


def verify_markup(source, target, paired, location):
    for marker in ("<page>", "([", "])"):
        if source.count(marker) != target.count(marker):
            raise ValueError(f"Runtime marker {marker} changed at {location}")
    source_tags = Counter(FORMAT_TAG.findall(source))
    target_tags = Counter(FORMAT_TAG.findall(target))
    if target_tags != source_tags:
        raise ValueError(f"Runtime tags changed at {location}")
    stack = []
    for close, name in FORMAT_TAG.findall(target):
        if name not in paired:
            continue
        if not close:
            stack.append(name)
        elif not stack or stack.pop() != name:
            raise ValueError(f"Malformed runtime styles at {location}")
    if stack:
        raise ValueError(f"Unclosed runtime styles at {location}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("extract", "rebuild"))
    parser.add_argument("--game", type=Path, default=PROJECT / "Game")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    obj, raw, terms = table(args.game / ASSET)
    rows = list(occurrences(terms))
    source = PROJECT / f"{PROJECT.name}_text.csv"
    if args.command == "extract":
        mapping = source.with_suffix(".mapping.json")
        source_rows = [row for row, _, _ in rows]
        if mapping.exists() and not source.exists():
            with tempfile.TemporaryDirectory() as directory:
                generated = Path(directory) / source.name
                recovered = generated.with_suffix(".mapping.json")
                count = export_occurrences(source_rows, generated, recovered)
                if json.loads(mapping.read_text(encoding="utf-8")) != json.loads(recovered.read_text(encoding="utf-8")):
                    raise ValueError("The local game's source differs from the committed mapping")
                with source.open("xb") as handle:
                    handle.write(generated.read_bytes())
        else:
            count = export_occurrences(source_rows, source, mapping)
        context = {str(number): {key: val for key, val in row.items() if key != "source" and val}
                   for number, (row, _, _) in enumerate(rows, 1)}
        source.with_suffix(".context.json").write_text(
            json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(count, Counter(row["group"] for row, _, _ in rows))
        return
    if args.destination is None:
        parser.error("rebuild requires --destination")
    translated = source.with_name(f"{PROJECT.name}_text_translated.csv")
    report = json.loads((PROJECT / "TranslateFiles/reports/final_validation.json").read_text(encoding="utf-8"))
    if (report.get("status") != "passed" or report.get("semantic_review") != "full"
            or report.get("records") != len(rows) or report.get("source_sha256") != sha(source)
            or report.get("translation_sha256") != sha(translated)):
        raise ValueError("Translation does not match the formally reviewed export")
    resolver = project_resolutions(PROJECT, source, translated)
    edits = []
    paired = {tag for row, _, _ in rows for close, tag in FORMAT_TAG.findall(row["source"]) if close}
    for row, start, end in rows:
        target = resolver.resolve(row["resource"], row["source"])
        verify_markup(row["source"], target, paired, row["resource"])
        encoded = target.encode("utf-8")
        edits.append((start, end, struct.pack("<i", len(encoded)) + encoded + b"\0" * (-len(encoded) % 4)))
    resolver.finish()
    rebuilt = bytearray()
    previous = 0
    for start, end, encoded in edits:
        rebuilt.extend(raw[previous:start])
        rebuilt.extend(encoded)
        previous = end
    rebuilt.extend(raw[previous:])
    obj.set_raw_data(bytes(rebuilt))
    target_path = args.destination / ASSET
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("xb") as handle:
        handle.write(obj.assets_file.save())
    _, checked_raw, _ = table(target_path)
    if checked_raw != bytes(rebuilt):
        raise ValueError("I2 language source did not round-trip")
    print(f"Verified {len(edits)} replacements in {target_path}")


if __name__ == "__main__":
    main()
