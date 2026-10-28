#!/usr/bin/env python3
"""国税庁ホームページから相続税関係の通達・タックスアンサー・質疑応答事例を収集し、
辞書データ (docs/data/dictionary.json) を生成する。

使い方:
    python3 scraper/build_dictionary.py [--cache DIR] [--out FILE] [--delay SEC]

取得したHTMLは --cache のディレクトリに保存され、再実行時は再利用される。
"""
import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urldefrag

import requests
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

import bunrui
import changes

BASE = "https://www.nta.go.jp"

# 通達（目次ページ）
TSUTATSU_SOURCES = [
    ("kihon", "相続税法基本通達", "/law/tsutatsu/kihon/sisan/sozoku2/01.htm"),
    ("hyoka", "財産評価基本通達", "/law/tsutatsu/kihon/sisan/hyoka_new/01.htm"),
    ("so", "租税特別措置法（相続税法の特例関係）通達", "/law/tsutatsu/kobetsu/sozoku/sochiho/080708/01.htm"),
]
# 個別通達（目次ページ）
KOBETSU_SOURCES = [
    ("相続税関係", "/law/tsutatsu/kobetsu/sozoku/souzoku.htm"),
    ("財産評価関係", "/law/tsutatsu/kobetsu/hyoka/zaisan.htm"),
]
KOBETSU_SKIP = ("/law/sozoku/kaisei/",)  # 申請・届出様式の制定（様式の一覧のみ）
# 文書回答事例（項目別の目次ページ）
BUNSHO_SOURCES = [
    ("相続税", "/law/bunshokaito/sozoku/05_1.htm"),
    ("贈与税", "/law/bunshokaito/zoyo/06_1.htm"),
    ("財産の評価", "/law/bunshokaito/hyoka/07_1.htm"),
]
MAX_SUBPAGES = 20
# タックスアンサー（コード一覧のセクションID）
TAXANSWER_INDEX = "/taxes/shiraberu/taxanswer/code/index.htm"
TAXANSWER_SECTIONS = ["code04", "code05", "code06"]  # 相続税・贈与税・財産の評価
# 質疑応答事例（目次ページ）
SHITSUGI_SOURCES = [
    ("相続税・贈与税", "/law/shitsugi/sozoku/01.htm"),
    ("財産の評価", "/law/shitsugi/hyoka/01.htm"),
]

session = requests.Session()
session.headers["User-Agent"] = "inheritance-tax-dictionary/1.0 (personal research)"


class Fetcher:
    def __init__(self, cache_dir: Path, delay: float):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay

    def get(self, url: str) -> BeautifulSoup | None:
        url = urldefrag(url)[0]
        key = hashlib.sha1(url.encode()).hexdigest()
        path = self.cache_dir / f"{key}.html"
        if path.exists():
            raw = path.read_bytes()
        else:
            raw = None
            for attempt in range(4):
                try:
                    r = session.get(url, timeout=30, allow_redirects=True)
                    if "/error/404" in r.url or r.status_code == 404:
                        print(f"  404: {url}", file=sys.stderr)
                        return None
                    r.raise_for_status()
                    raw = r.content
                    break
                except requests.RequestException as e:
                    print(f"  retry {attempt + 1}: {url} ({e})", file=sys.stderr)
                    time.sleep(2 ** (attempt + 1))
            if raw is None:
                return None
            path.write_bytes(raw)
            time.sleep(self.delay)
        return BeautifulSoup(decode(raw), "lxml")


def decode(raw: bytes) -> str:
    head = raw[:3000].lower()
    m = re.search(rb'charset=["\']?([\w-]+)', head)
    enc = m.group(1).decode() if m else "utf-8"
    if enc.replace("-", "_") in ("shift_jis", "sjis", "x_sjis"):
        enc = "cp932"
    return raw.decode(enc, errors="replace")


def clean(s: str) -> str:
    s = s.replace("　", "　")
    s = re.sub(r"[ \t\r\n\xa0]+", " ", s)
    return s.strip()


def body_area(soup: BeautifulSoup) -> Tag:
    return soup.find(id="bodyArea") or soup.body


# ---------------------------------------------------------------- HTML整形

ALLOWED = {"p", "br", "strong", "b", "table", "thead", "tbody", "tr", "th", "td",
           "ul", "ol", "li", "h2", "h3", "h4", "h5", "a", "sup", "sub", "span", "div",
           "dl", "dt", "dd", "caption", "img"}
KEEP_ATTRS = ("colspan", "rowspan")  # 出力が実行ごとに変わらないよう順序を固定


def simplify(nodes, page_url: str) -> str:
    """表示用に属性を落とした簡易HTMLへ変換する。"""
    out = []
    for n in nodes:
        out.append(_simplify(n, page_url))
    html = "".join(out)
    html = re.sub(r"\s*\n\s*", "\n", html)
    return html.strip()


def _simplify(n, page_url):
    if isinstance(n, NavigableString):
        if n.__class__.__name__ in ("Comment", "Doctype", "Declaration", "ProcessingInstruction"):
            return ""
        return escape(str(n))
    if not isinstance(n, Tag):
        return ""
    name = n.name.lower()
    if name in ("script", "style", "noscript", "form", "input", "button"):
        return ""
    inner = "".join(_simplify(c, page_url) for c in n.children)
    if name == "img":
        alt = clean(n.get("alt", ""))
        src = urljoin(page_url, n.get("src", ""))
        return f'<span class="img">［図：<a href="{escape(src)}" target="_blank" rel="noopener">{escape(alt) or "画像"}</a>］</span>'
    if name not in ALLOWED:
        return inner
    if name in ("span", "div"):
        return inner if name == "span" else f"<div>{inner}</div>"
    attrs = ""
    if name == "a":
        href = n.get("href")
        if not href or href.startswith("javascript") or not inner.strip():
            return inner
        attrs = f' href="{escape(urljoin(page_url, href))}" target="_blank" rel="noopener"'
    if name == "p":
        cls = [c for c in n.get("class", []) if c.startswith("indent")]
        if cls:
            attrs = f' class="{cls[0]}"'
    for k in KEEP_ATTRS:
        if n.get(k):
            attrs += f' {k}="{escape(n.get(k))}"'
    if name == "br":
        return "<br>"
    return f"<{name}{attrs}>{inner}</{name}>"


def escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def text_of(nodes) -> str:
    parts = []
    for n in nodes:
        if isinstance(n, Tag):
            parts.append(n.get_text(" "))
        elif isinstance(n, NavigableString) and not isinstance(n, Comment):
            parts.append(str(n))
    return clean(" ".join(parts))


# ---------------------------------------------------------------- 目次解析

def parse_index(soup: BeautifulSoup, page_url: str, heading_rule):
    """目次ページを文書順に走査し、(番号, タイトル, URL, 区分パス) を返す。"""
    area = body_area(soup)
    path = {}
    entries = []
    for el in area.find_all(["h2", "h3", "h4", "p"]):
        if el.find_parent(class_="page-header") or "page-top-link" in el.get("class", []):
            continue
        lv = heading_rule(el)
        if lv:
            level, title = lv
            path = {k: v for k, v in path.items() if k < level}
            path[level] = title
            continue
        a = el.find("a", href=True)
        if not a or el.name != "p":
            continue
        href = a["href"]
        if href.startswith("#") or "bunshokaito" in href:
            continue
        url = urljoin(page_url, href)
        title = clean(a.get_text())
        number = clean(el.get_text().split(a.get_text())[0]) if a.get_text() else ""
        if title in ("前文・説明文", "前文", "詳細はこちら"):
            continue
        entries.append({
            "number": number,
            "title": title,
            "url": url,
            "category": [path[k] for k in sorted(path)],
        })
    return entries


def strip_brackets(s: str) -> str:
    s = clean(s)
    return re.sub(r"^[（(〔［\[]+|[）)〕］\]]+$", "", s).strip()


def tsutatsu_heading(el: Tag):
    text = clean(el.get_text())
    if not text or el.find("a", href=re.compile(r"^(?!#)")):
        # 見出しにリンクがある場合は項目（ただし前文リンクは除外済み）
        if el.name == "p":
            return None
    if el.name in ("h2", "h3") or (el.name == "p" and el.find("strong") and
                                   clean(el.find("strong").get_text()) == text):
        if re.match(r"^第[0-9０-９一二三四五六七八九十]+章", text):
            return (1, text)
        if re.match(r"^第[0-9０-９一二三四五六七八九十]+節", text):
            return (2, text)
        if re.match(r"^第[0-9０-９一二三四五六七八九十]+款", text):
            return (3, text)
        inner = strip_brackets(text)
        # 〔保険金関係〕などの小見出しは条の下に置く（措置法通達の〔措置法第○条…関係〕は条の見出し）
        if text.startswith("〔") and not re.match(r"^(旧)?措置法", inner):
            return (5, inner)
        if inner.endswith("関係"):
            return (4, inner)
        if el.name in ("h2", "h3"):
            return (1, text)
        return (4, strip_brackets(text))
    return None


def shitsugi_heading(el: Tag):
    text = clean(el.get_text())
    if not text:
        return None
    if el.name == "p" and el.find("a", href=True) and not el.get("id"):
        return None
    if el.name == "h2" or (el.name == "p" and el.get("align") == "center"):
        return (1, strip_brackets(text))
    if el.name in ("h3", "h4") or (el.name == "p" and el.get("id")):
        return (2, strip_brackets(text))
    return None


# ---------------------------------------------------------------- 詳細ページ

def find_anchor(area: Tag, anchor: str):
    el = area.find(id=anchor) or area.find(attrs={"name": anchor})
    return el


NUM_RE = re.compile(r"^\s*([0-9０-９][0-9０-９の・共\-－−‐―ー]*[0-9０-９])")


def norm_num(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[－−‐―ー‑–—]", "-", s)
    return re.sub(r"\s+", "", s)


def page_children(area: Tag):
    header = area.find(class_="page-header")
    container = header.parent if header else area
    for c in container.children:
        if not isinstance(c, Tag):
            continue
        if "page-top-link" in (c.get("class") or []):
            break
        if c.name in ("footer", "script", "ol") or "page-header" in (c.get("class") or []) or "skip" in (c.get("class") or []):
            continue
        yield c


def segment_tsutatsu(soup: BeautifulSoup, url: str):
    """通達ページを番号付き項目ごとに分割し {正規化番号: 項目} を返す。"""
    area = body_area(soup)
    segs = {}
    cur = None
    pending = None  # 直前の見出し要素
    last_heading = ""
    for c in page_children(area):
        if c.name in ("h2", "h3"):
            pending = c
            last_heading = strip_brackets(c.get_text())
            cur = None
            continue
        strong = c.find("strong") if c.name == "p" else None
        m = NUM_RE.match(clean(c.get_text())) if strong is not None and clean(c.get_text()).startswith(clean(strong.get_text())[:1]) else None
        if m and "indent1" in (c.get("class") or []) or (m and not c.get("class")):
            num = norm_num(m.group(1))
            nodes = ([pending] if pending is not None else []) + [c]
            cur = {"heading": last_heading, "nodes": nodes}
            segs.setdefault(num, cur)
            pending = None
            continue
        if cur is not None:
            cur["nodes"].append(c)
        elif pending is not None:
            pass
    return {k: {"heading": v["heading"], "html": simplify(v["nodes"], url), "text": text_of(v["nodes"])}
            for k, v in segs.items()}


def is_anchor_only(el) -> bool:
    """本文を持たないアンカー要素（<a id=..>単独や、それだけを含む<p>）か。"""
    if not isinstance(el, Tag):
        return False
    if el.name == "a" and (el.get("id") or el.get("name")) and not clean(el.get_text()):
        return True
    if el.name == "p" and not clean(el.get_text()) and el.find("a", attrs={"name": True}) or (
            el.name == "p" and not clean(el.get_text()) and el.find("a", id=True)):
        return True
    return False


def tsutatsu_detail(soup: BeautifulSoup, url: str):
    area = body_area(soup)
    _, frag = urldefrag(url)
    h1 = area.find("h1")
    page_title = clean(h1.get_text()) if h1 else ""
    start = find_anchor(area, frag) if frag else None
    if start is not None:
        # アンカーを含む見出し要素から次の見出し（または次のアンカー）まで
        head = start if start.name in ("h2", "h3") else start.find_parent(["h2", "h3"])
        if head is None:
            block = start.find_parent("p") or start
            head = block if is_anchor_only(block) is False else block.find_next_sibling(["h2", "h3", "p"])
        nodes = [head] if head is not None else []
        for sib in (head.find_next_siblings() if head is not None else []):
            if sib.name in ("h1", "h2", "h3") or is_anchor_only(sib):
                break
            if "page-top-link" in (sib.get("class") or []):
                break
            nodes.append(sib)
        heading = clean(head.get_text()) if head is not None and head.name in ("h2", "h3") else ""
    else:
        nodes = content_nodes(area)
        heading = ""
    return {"pageTitle": page_title, "heading": strip_brackets(heading),
            "html": simplify(nodes, url), "text": text_of(nodes)}


def content_nodes(area: Tag, stop_h2=()):
    """h1以降の本文ノード（ページ先頭へリンクや指定見出しで打ち切り）。"""
    header = area.find(class_="page-header")
    container = header.parent if header else area
    nodes = []
    started = header is None
    for c in container.children:
        if c is header:
            started = True
            continue
        if not started:
            continue
        if isinstance(c, Tag):
            if "page-top-link" in (c.get("class") or []):
                break
            if c.name == "h2" and clean(c.get_text()) in stop_h2:
                break
            if c.name in ("footer", "script"):
                break
        nodes.append(c)
    # 本文がさらに入れ子divにある場合
    if len([n for n in nodes if isinstance(n, Tag)]) == 1 and isinstance(nodes[0], Tag) and nodes[0].name == "div":
        return content_nodes(nodes[0], stop_h2)
    return nodes


def taxanswer_detail(soup: BeautifulSoup, url: str):
    area = body_area(soup)
    h1 = area.find("h1")
    title = clean(h1.get_text()) if h1 else ""
    nodes = content_nodes(area, stop_h2=("関連リンク", "QAリンク", "お問い合わせ先", "税の情報・手続・用紙"))
    nodes = [n for n in nodes if not (isinstance(n, Tag) and n.get("id") == "pagetop")]
    asof = ""
    m = re.search(r"［(.+?現在法令等)］|\[(.+?現在法令等)\]", text_of(nodes))
    if m:
        asof = m.group(1) or m.group(2)
    return {"pageTitle": title, "asof": asof, "html": simplify(nodes, url), "text": text_of(nodes)}


def shitsugi_detail(soup: BeautifulSoup, url: str):
    area = body_area(soup)
    h1 = area.find("h1")
    title = clean(h1.get_text()) if h1 else ""
    nodes = content_nodes(area)
    text = text_of(nodes)
    asof = ""
    m = re.search(r"([令平][和成][0-9０-９元一二三四五六七八九十]+年[0-9０-９一二三四五六七八九十]+月[0-9０-９一二三四五六七八九十]+日現在)", text)
    if m:
        asof = m.group(1)
    return {"pageTitle": title, "asof": asof, "html": simplify(nodes, url), "text": text}


def multi_page(f, url: str):
    """本文ページと、同じフォルダにある別紙・続きのページ（HTML）をまとめて取り出す。"""
    soup = f.get(url)
    if soup is None:
        return None
    base_dir = urldefrag(url)[0].rsplit("/", 1)[0] + "/"
    pages = [(url, soup)]
    seen = {urldefrag(url)[0]}
    queue = [soup]
    while queue and len(pages) < MAX_SUBPAGES:
        area = body_area(queue.pop(0))
        for a in area.find_all("a", href=True):
            if a.find_parent("ol") or a.find_parent(class_="breadcrumb"):
                continue
            u = urldefrag(urljoin(url, a["href"]))[0]
            if u in seen or not u.startswith(base_dir) or not u.endswith(".htm"):
                continue
            seen.add(u)
            sp = f.get(u)
            if sp is None:
                continue
            pages.append((u, sp))
            queue.append(sp)
            if len(pages) >= MAX_SUBPAGES:
                break
    html, text = [], []
    for i, (u, sp) in enumerate(pages):
        area = body_area(sp)
        nodes = [n for n in content_nodes(area) if not (isinstance(n, NavigableString) and "InstanceEnd" in str(n))]
        if i > 0:
            h1 = area.find("h1")
            if h1:
                html.append(f"<h2>{escape(clean(h1.get_text()))}</h2>")
                text.append(clean(h1.get_text()))
        html.append(simplify(nodes, u))
        text.append(text_of(nodes))
    return {"html": "\n".join(html), "text": " ".join(text)}


# ---------------------------------------------------------------- メイン

def make_id(prefix, url):
    path, frag = urldefrag(url)
    slug = re.sub(r"^https://www\.nta\.go\.jp/", "", path)
    slug = re.sub(r"\.htm$", "", slug)
    return f"{prefix}:{slug}" + (f"#{frag}" if frag else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=".cache/nta")
    ap.add_argument("--out", default="docs/data/dictionary.json")
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only-if-changed", action="store_true",
                    help="前回のデータと内容が同じなら書き込まない（取得日だけの更新をしない）")
    ap.add_argument("--report", help="変更の要約（Markdown）の出力先。変更がなければ作らない")
    ap.add_argument("--history", default="docs/data/updates.json", help="更新記録の出力先（--only-if-changed のとき）")
    ap.add_argument("--max-drop", type=float, default=0.03,
                    help="前回より項目数がこの割合を超えて減ったら、取得の失敗とみなして中止する")
    args = ap.parse_args()
    f = Fetcher(Path(args.cache), args.delay)

    items = []

    # --- 通達
    for kind, name, idx in TSUTATSU_SOURCES:
        idx_url = BASE + idx
        print(f"[通達] {name}", file=sys.stderr)
        entries = parse_index(f.get(idx_url), idx_url, tsutatsu_heading)
        pages = sorted({urldefrag(e["url"])[0] for e in entries})
        with ThreadPoolExecutor(args.workers) as ex:
            soups = dict(zip(pages, ex.map(f.get, pages)))
        segs_by_page = {u: segment_tsutatsu(sp, u) for u, sp in soups.items() if sp is not None}
        all_segs = {}
        for segs in segs_by_page.values():
            for k, v in segs.items():
                all_segs.setdefault(k, v)
        for e in entries:
            page = urldefrag(e["url"])[0]
            soup = soups.get(page)
            if soup is None:
                continue
            num = norm_num(e["number"])
            seg = segs_by_page.get(page, {}).get(num) or all_segs.get(num)
            d = seg if seg and num else tsutatsu_detail(soup, e["url"])
            if not d["text"]:
                d = tsutatsu_detail(soup, e["url"])
            items.append({
                "id": make_id("tsutatsu", e["url"]),
                "kind": kind,
                "type": "通達",
                "source": name,
                "number": e["number"],
                "title": e["title"],
                "category": e["category"],
                "url": e["url"],
                "html": d["html"],
                "text": d["text"],
            })
        print(f"  {len(entries)} 件", file=sys.stderr)

    # --- タックスアンサー
    idx_url = BASE + TAXANSWER_INDEX
    soup = f.get(idx_url)
    for sec in TAXANSWER_SECTIONS:
        h2 = soup.find("h2", id=sec)
        sec_name = clean(h2.get_text())
        print(f"[タックスアンサー] {sec_name}", file=sys.stderr)
        entries = []
        sub = ""
        for el in h2.find_all_next(["h2", "h3", "a"]):
            if el.name == "h2":
                break
            if el.name == "h3":
                sub = clean(el.get_text())
                continue
            href = el.get("href", "")
            if "/taxanswer/" not in href or href.startswith("#"):
                continue
            label = clean(el.get_text())
            m = re.match(r"^(\d{4})\s*(.*)$", label)
            entries.append({"number": m.group(1) if m else "", "title": m.group(2) if m else label,
                            "url": urljoin(idx_url, href), "category": [sec_name] + ([sub] if sub else [])})
        urls = [e["url"] for e in entries]
        with ThreadPoolExecutor(args.workers) as ex:
            soups = list(ex.map(f.get, urls))
        for e, s in zip(entries, soups):
            if s is None:
                continue
            d = taxanswer_detail(s, e["url"])
            items.append({
                "id": make_id("taxanswer", e["url"]),
                "kind": "ta",
                "type": "タックスアンサー",
                "source": f"タックスアンサー（{sec_name}）",
                "number": f"No.{e['number']}" if e["number"] else "",
                "title": e["title"],
                "category": e["category"],
                "url": e["url"],
                "asof": d["asof"],
                "html": d["html"],
                "text": d["text"],
            })
        print(f"  {len(entries)} 件", file=sys.stderr)

    # --- 質疑応答事例
    for name, idx in SHITSUGI_SOURCES:
        idx_url = BASE + idx
        print(f"[質疑応答事例] {name}", file=sys.stderr)
        entries = parse_index(f.get(idx_url), idx_url, shitsugi_heading)
        entries = [e for e in entries if "/law/shitsugi/" in e["url"]]
        with ThreadPoolExecutor(args.workers) as ex:
            soups = list(ex.map(f.get, [e["url"] for e in entries]))
        for e, s in zip(entries, soups):
            if s is None:
                continue
            d = shitsugi_detail(s, e["url"])
            items.append({
                "id": make_id("shitsugi", e["url"]),
                "kind": "qa",
                "type": "質疑応答事例",
                "source": f"質疑応答事例（{name}）",
                "number": e["number"],
                "title": e["title"],
                "category": e["category"],
                "url": e["url"],
                "asof": d["asof"],
                "html": d["html"],
                "text": d["text"],
            })
        print(f"  {len(entries)} 件", file=sys.stderr)

    # --- 個別通達
    for name, idx in KOBETSU_SOURCES:
        idx_url = BASE + idx
        print(f"[個別通達] {name}", file=sys.stderr)
        entries = []
        for tr in body_area(f.get(idx_url)).select("table tr"):
            tds = tr.find_all("td")
            a = tds[1].find("a", href=True) if len(tds) > 1 else None
            if not a or any(k in a["href"] for k in KOBETSU_SKIP):
                continue
            dates = re.findall(r"（[^）]*?日[^）]*?）", clean(tds[0].get_text()))
            entries.append({"title": clean(a.get_text()), "url": urljoin(idx_url, a["href"]),
                            "date": dates[0].strip("（）") if dates else "",
                            "revised": dates[1].strip("（）") if len(dates) > 1 else ""})
        with ThreadPoolExecutor(args.workers) as ex:
            details = list(ex.map(lambda e: multi_page(f, e["url"]), entries))
        for e, d in zip(entries, details):
            if d is None:
                continue
            items.append({
                "id": make_id("kobetsu", e["url"]),
                "kind": "kobetsu",
                "type": "通達",
                "source": "個別通達",
                "number": "",
                "title": e["title"],
                "category": [name],
                "url": e["url"],
                "date": e["date"],
                "asof": e["revised"],
                "html": d["html"],
                "text": d["text"],
            })
        print(f"  {len(entries)} 件", file=sys.stderr)

    # --- 文書回答事例
    for name, idx in BUNSHO_SOURCES:
        idx_url = BASE + idx
        print(f"[文書回答事例] {name}", file=sys.stderr)
        entries = []
        heading = ""
        for el in body_area(f.get(idx_url)).find_all(["h2", "h3", "h4", "h5", "table"]):
            if el.name != "table":
                heading = strip_brackets(el.get_text())
                continue
            row = {clean(tr.find("th").get_text()): tr.find("td") for tr in el.find_all("tr") if tr.find("th") and tr.find("td")}
            a = row.get("照会事項") and row["照会事項"].find("a", href=True)
            if not a:
                continue
            entries.append({"title": clean(a.get_text()), "url": urljoin(idx_url, a["href"]),
                            "date": clean(row["回答年月日"].get_text()) if "回答年月日" in row else "",
                            "dept": clean(row["回答部署"].get_text()) if "回答部署" in row else "",
                            "category": [name] + ([heading] if heading else [])})
        with ThreadPoolExecutor(args.workers) as ex:
            details = list(ex.map(lambda e: multi_page(f, e["url"]), entries))
        for e, d in zip(entries, details):
            if d is None:
                continue
            items.append({
                "id": make_id("bunsho", e["url"]),
                "kind": "bk",
                "type": "文書回答事例",
                "source": f"文書回答事例（{name}）",
                "number": "",
                "title": e["title"],
                "category": e["category"],
                "url": e["url"],
                "date": e["date"],
                "dept": e["dept"],
                "html": d["html"],
                "text": d["text"],
            })
        print(f"  {len(entries)} 件", file=sys.stderr)

    # 重複ID除去（同じ事例が複数区分に掲載される場合は区分を統合）
    merged = {}
    for it in items:
        if it["id"] in merged:
            cats = merged[it["id"]].setdefault("altCategories", [])
            if it["category"] != merged[it["id"]]["category"] and it["category"] not in cats:
                cats.append(it["category"])
            continue
        merged[it["id"]] = it
    items = list(merged.values())
    for it in items:
        it["tags"] = bunrui.classify(it)
        del it["text"]  # 検索用の本文は画面側で html から作る

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    data = {"generated": today, "count": len(items),
            "sourceNote": "出典：国税庁ホームページ（https://www.nta.go.jp/）",
            "bunrui": bunrui.export(), "items": items}

    if args.only_if_changed and out.exists():
        prev = json.loads(out.read_text(encoding="utf-8"))
        # 一部のページが取れずに項目が大きく減った場合は、データを壊さないよう中止する
        if len(items) < len(prev["items"]) * (1 - args.max_drop):
            sys.exit(f"項目数が {len(prev['items'])} → {len(items)} に減りました。取得に失敗した可能性があるため更新を中止します。")
        diff = changes.compare(prev["items"], items)
        bunrui_changed = prev.get("bunrui") != data["bunrui"]
        if not changes.has_changes(diff) and not bunrui_changed:
            print("変更なし（データは書き換えません）", file=sys.stderr)
            return
        print(f"変更あり：追加{len(diff['added'])}件・削除{len(diff['removed'])}件・更新{len(diff['changed'])}件", file=sys.stderr)
        hist_path = Path(args.history)
        history = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else []
        history.insert(0, changes.history_entry(today, diff, bunrui_changed))
        hist_path.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
        if args.report:
            Path(args.report).write_text(changes.report(today, diff, len(items), bunrui_changed), encoding="utf-8")

    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({len(items)} items, {out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)


if __name__ == "__main__":
    main()
