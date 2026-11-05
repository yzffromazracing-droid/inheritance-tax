#!/usr/bin/env python3
"""読み表 docs/data/yomi.json に用語の読みを加える。

読み表は [[読み(ひらがな), "表記|表記|…"], …] を読みの順に並べたもの。画面の検索で、ひらがな・カタカナの
検索語を、読みがその語で始まる表記に置き換えて検索するのに使う。

    python3 scraper/build_yomi.py              # scraper/yomi_extra.tsv の用語を加える
    python3 scraper/build_yomi.py --from-data  # さらに辞書データ中の用語の読みを形態素解析で加える

--from-data は SudachiPy（pip install sudachipy sudachidict_core）を使い、辞書データ
（docs/data/dictionary.json）のタイトル・目次の見出し・区分とテーマの説明・本文に出てくる、漢字を含む名詞の読みを加える。
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "docs/data/yomi.json"
DATA = ROOT / "docs/data/dictionary.json"
EXTRA = Path(__file__).resolve().parent / "yomi_extra.tsv"

KANJI = re.compile(r"[㐀-鿿々〆ヶ]")
KANA = re.compile(r"^[ぁ-ゖー]+$")
MAX_CHUNK = 4000  # SudachiPy は1回に解析できる文字列の長さに上限があるため、分けて渡す


def to_hiragana(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def texts_from_data(data):
    """読みを付ける対象の文字列（タイトル・見出し・区分とテーマ・本文）。"""
    for item in data["items"]:
        yield item["title"]
        yield from item.get("category", [])
        yield re.sub(r"<[^>]+>", "\n", item.get("html", ""))
    for tab in data.get("bunrui", {}).values():
        for cls in tab["classes"]:
            yield cls["label"]
            yield cls["desc"]
            for t in cls["topics"]:
                yield t["name"]
                yield t["desc"]
                for tb in [t.get("table")] + t.get("tables", []):
                    if tb:
                        yield " ".join(tb["head"])
                        yield from (" ".join(r) for r in tb["rows"])
                for link in t.get("links", []):
                    yield link["title"]


def chunks(text):
    for line in re.split(r"[\n。]", text):
        line = line.strip()
        while line:
            yield line[:MAX_CHUNK]
            line = line[MAX_CHUNK:]


def readings_from_data(data):
    """(表記, 読み) の組。名詞の長い単位と、その中の短い単位、続いた名詞をつないだ語の読みを返す。"""
    from sudachipy import dictionary, tokenizer  # GitHub Actions など、インストールできる環境でだけ使う

    tok = dictionary.Dictionary(dict="core").create()
    mode_c = tokenizer.Tokenizer.SplitMode.C
    mode_a = tokenizer.Tokenizer.SplitMode.A
    seen = set()

    def word(surface, reading):
        reading = to_hiragana(reading)
        if not KANJI.search(surface) or not KANA.match(reading) or len(reading) < 2:
            return
        if (surface, reading) not in seen:
            seen.add((surface, reading))
            yield surface, reading

    for text in texts_from_data(data):
        for part in chunks(text):
            run = []  # 続いた名詞（「未分割」の「未」のような接頭辞、「建築中」の「中」のような接尾辞も含める）
            for m in tok.tokenize(part, mode_c):
                pos = m.part_of_speech()[0]
                if pos not in ("名詞", "接頭辞", "接尾辞"):
                    run = []
                    continue
                if pos == "名詞":
                    yield from word(m.surface(), m.reading_form())
                    for sub in m.split(mode_a):
                        yield from word(sub.surface(), sub.reading_form())
                run.append(m)
                # 2〜3語の名詞の並び（例：小規模＋宅地＋等）も1語として加える
                for n in (2, 3):
                    if len(run) >= n:
                        ms = run[-n:]
                        surface = "".join(x.surface() for x in ms)
                        if len(surface) <= 12:
                            yield from word(surface, "".join(x.reading_form() for x in ms))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-data", action="store_true", help="辞書データ中の用語の読みを形態素解析で加える")
    args = ap.parse_args()

    rows = json.loads(TABLE.read_text(encoding="utf-8"))
    table = {r: s.split("|") for r, s in rows}

    def add(reading, surface):
        words = table.setdefault(reading, [])
        if surface in words:
            return 0
        words.append(surface)
        return 1

    added = 0
    for line in EXTRA.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        reading, surface = line.split("\t")
        added += add(reading, surface)
    print(f"yomi_extra.tsv から {added} 語を追加")

    if args.from_data:
        data = json.loads(DATA.read_text(encoding="utf-8"))
        n = sum(add(reading, surface) for surface, reading in readings_from_data(data))
        print(f"辞書データから {n} 語を追加")
        added += n

    out = [[r, "|".join(table[r])] for r in sorted(table)]
    TABLE.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"計 {added} 語を追加（{len(out)} 件）")


if __name__ == "__main__":
    main()
