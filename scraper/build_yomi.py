#!/usr/bin/env python3
"""読み表 docs/data/yomi.json に scraper/yomi_extra.tsv の用語を加える。

読み表は [[読み(ひらがな), "表記|表記|…"], …] を読みの順に並べたもの。
基になる一般語の読み表に、相続税・贈与税・財産評価の用語の読みを追加して書き戻す。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "docs/data/yomi.json"
EXTRA = Path(__file__).resolve().parent / "yomi_extra.tsv"

rows = json.loads(TABLE.read_text(encoding="utf-8"))
table = {r: s.split("|") for r, s in rows}
added = 0
for line in EXTRA.read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    reading, surface = line.split("\t")
    words = table.setdefault(reading, [])
    if surface not in words:
        words.append(surface)
        added += 1
out = [[r, "|".join(table[r])] for r in sorted(table)]
TABLE.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"{added} 語を追加（{len(out)} 件）")
