#!/usr/bin/env python3
"""Facebook投稿に添える図解カード（1080×1080）をSVGで作り、PNGに変換する。

    python3 social/facebook_image.py <出力.png|出力.svg> [--date=YYYY-MM-DD]

PNGへの変換には rsvg-convert（librsvg2-bin）と日本語フォント（fonts-noto-cjk）が必要。
GitHub Actions ではワークフローでインストールする。
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import facebook_post as fp  # noqa: E402

SIZE = 1080
FONT = "'Noto Sans CJK JP', 'Noto Sans JP', 'IPAGothic', 'WenQuanYi Zen Hei', sans-serif"

# 辞書タブの色（docs/style.css の色に合わせる）
COLORS = {
    "shoukei": {"main": "#1d4ed8", "bg": "#e8effe", "soft": "#c3d4fb"},
    "sozoku": {"main": "#c2410c", "bg": "#fff1e8", "soft": "#fdd9c2"},
    "zoyo": {"main": "#15803d", "bg": "#e9f8ee", "soft": "#bfe8cc"},
    "zaisan": {"main": "#0f766e", "bg": "#e3f5f2", "soft": "#b6e3db"},
}

# 行頭に来てはいけない文字
NO_START = "、。，．・：；？！）」』】〕ー～ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ％"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def char_width(ch):
    """全角を1、半角を0.55として幅を数える。"""
    return 0.55 if ord(ch) < 0x100 or "｡" <= ch <= "ﾟ" else 1


def text_width(s):
    return sum(char_width(c) for c in s)


# 行末に来てはいけない文字
NO_END = "（「『【〔(［"

# 「M&A」「1,681」のような半角の英数字と記号の続きは途中で折り返さない
ASCII_RUN = re.compile(r"[A-Za-z0-9&.,%＆]+|.")


def wrap(s, max_width, max_lines):
    """1行あたり max_width（全角文字数）で折り返し、max_lines を超えたら「…」で切る。"""
    lines, cur, w = [], "", 0.0
    for tok in ASCII_RUN.findall(s):
        cw = text_width(tok)
        if w + cw > max_width and cur and tok[0] not in NO_START:
            # 行末に来てはいけない開き括弧は次の行へ送る
            carry = ""
            while cur and cur[-1] in NO_END:
                carry = cur[-1] + carry
                cur = cur[:-1]
            if cur:
                lines.append(cur)
            cur, w = carry, text_width(carry)
        cur += tok
        w += cw
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while text_width(last) > max_width - 1:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def text(x, y, s, size, fill="#1f2937", weight=None, anchor=None):
    attrs = f'x="{x}" y="{y}" font-size="{size}" fill="{fill}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    if anchor:
        attrs += f' text-anchor="{anchor}"'
    return f"<text {attrs}>{esc(s)}</text>"


def build_svg(data, entry):
    c = COLORS[entry["tab"]]
    t = entry["topic"]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}" font-family="{FONT}">',
        f'<rect width="100%" height="100%" fill="{c["bg"]}"/>',
        '<rect x="40" y="40" width="1000" height="1000" rx="36" fill="#fff"/>',
        f'<rect x="40" y="40" width="1000" height="16" rx="8" fill="{c["main"]}"/>',
        text(96, 132, "今日の相続税区分", 36, c["main"], 700),
    ]

    # 区分（タブ｜区分名）のバッジ
    badge = entry["tab_label"] + "｜" + entry["cls_label"]
    badge_w = round(text_width(badge) * 34 + 56)
    out.append(f'<rect x="96" y="160" width="{badge_w}" height="62" rx="31" fill="{c["main"]}"/>')
    out.append(text(96 + badge_w / 2, 203, badge, 34, "#fff", 700, "middle"))

    # テーマ名（長い名前は文字を小さくして3行まで）
    long = text_width(t["name"]) > 28
    name_size = 56 if long else 68
    y = 300 + (0 if long else 10)
    # 行頭禁則で1文字はみ出しても枠に収まるよう、1行の文字数は枠の幅より1文字少なくする
    for line in wrap(t["name"], 14 if long else 12, 3 if long else 2):
        out.append(text(96, y, line, name_size, "#1f2937", 700))
        y += name_size + 16

    # 表は、先頭の行が切らずに収まるときだけ載せる（1列目と最後の列）。収まらなければ説明文を載せ、
    # 表が短くて余白があるときは、表の下に説明文を続ける
    tables = ([t["table"]] if t.get("table") else []) + t.get("tables", [])
    y += 10
    out.append(f'<rect x="96" y="{y}" width="888" height="3" fill="{c["soft"]}"/>')
    y += 60
    tb = tables[0] if tables else None
    # 下の余白に入る行数まで（1行60px、見出しがあればその分を引く）
    max_rows = int((960 - y - (52 if tb and tb.get("caption") else 0)) // 60) if tb else 0
    rows = tb["rows"][:max_rows] if tb else []
    fits = rows and all(text_width(r[0]) <= 15 and (len(r) < 2 or text_width(r[-1]) <= 12) for r in rows)
    if fits:
        if tb.get("caption"):
            out.append(text(96, y, tb["caption"], 32, "#6b7280", 700))
            y += 52
        for i, row in enumerate(rows):
            if i % 2 == 0:
                out.append(f'<rect x="96" y="{y - 40}" width="888" height="56" rx="8" fill="{c["bg"]}"/>')
            out.append(text(116, y, row[0], 34))
            if len(row) > 1:
                out.append(text(964, y, row[-1], 34, c["main"], 700, "end"))
            y += 60
        if len(tb["rows"]) > len(rows) or len(tables) > 1:
            out.append(text(116, y, "…続きは辞書で", 28, "#6b7280"))
            y += 50
        y += 30
    room = int((960 - y) // 58)
    if room >= 2:
        for line in wrap(t["desc"], 22, room):
            out.append(text(96, y, line, 38))
            y += 58

    # フッター
    out.append(text(984, 1010, "相続税区分辞書", 28, c["main"], 700, "end"))
    out.append("</svg>")
    return "\n".join(out)


def render_png(svg, out_file):
    tmp = Path(str(out_file).removesuffix(".png") + ".svg")
    tmp.write_text(svg, encoding="utf-8")
    subprocess.run(["rsvg-convert", "-w", str(SIZE), "-h", str(SIZE), "-o", str(out_file), str(tmp)], check=True)
    tmp.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", help="出力ファイル（.png または .svg）")
    ap.add_argument("--date", help="この日（日本時間）のテーマを使う（YYYY-MM-DD）")
    args = ap.parse_args()
    data = fp.load_data()
    entry = fp.pick(data, fp.parse_date(args.date))
    svg = build_svg(data, entry)
    if args.out.endswith(".svg"):
        Path(args.out).write_text(svg, encoding="utf-8")
    else:
        render_png(svg, args.out)
    print(args.out + "（" + entry["topic"]["name"] + "）")


if __name__ == "__main__":
    main()
