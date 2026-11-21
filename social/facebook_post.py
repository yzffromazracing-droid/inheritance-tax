#!/usr/bin/env python3
"""辞書のテーマを1日1件、Facebookページに投稿する。

    python3 social/facebook_post.py [--dry-run] [--date=YYYY-MM-DD] [--image=画像.png]

環境変数:
    FB_PAGE_ID           : 投稿先のFacebookページID
    FB_PAGE_ACCESS_TOKEN : ページアクセストークン（pages_manage_posts 権限）
    FB_GRAPH_VERSION     : Graph APIのバージョン（任意。既定 v23.0）

投稿するのは、辞書タブの「事業承継」「相続税」「贈与税」「財産評価」の各テーマ（説明・表・関係する通達と記事）。
テーマは日付（日本時間）から決まり、4つのタブを順に巡るので、約4か月で全テーマを一巡する。
--image を指定し、そのファイルがあれば写真付きで投稿する（本文は写真の説明文になる）。
--dry-run またはトークン未設定のときは投稿せず本文を表示するだけ。
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs/data/dictionary.json"
JST = timezone(timedelta(hours=9))

TAB_ORDER = ["shoukei", "sozoku", "zoyo", "zaisan"]
HASHTAGS = {
    "shoukei": ["#事業承継", "#事業承継税制"],
    "sozoku": ["#相続税", "#相続"],
    "zoyo": ["#贈与税", "#生前贈与"],
    "zaisan": ["#財産評価", "#相続税"],
}
KIND_LABEL = {
    "kihon": "相続税法基本通達", "hyoka": "財産評価基本通達", "so": "措置法通達", "kobetsu": "個別通達",
    "ta": "タックスアンサー", "qa": "質疑応答事例", "bk": "文書回答事例",
}
# 関係する通達・記事を選ぶときの種別の順（読みやすい記事を先に）
KIND_ORDER = ["ta", "kihon", "hyoka", "so", "qa", "kobetsu", "bk"]
MAX_TABLE_ROWS = 8
MAX_RELATED = 3


def load_data(path=DATA):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def topics(data):
    """投稿するテーマの一覧。タブごとの一覧を、事業承継→相続税→贈与税→財産評価の順に1件ずつ交互に並べる。"""
    per_tab = []
    for tab in TAB_ORDER:
        spec = data["bunrui"][tab]
        per_tab.append([
            {"tab": tab, "tab_label": spec["label"], "cls": c["key"], "cls_label": c["label"], "topic": t, "index": n}
            for c in spec["classes"] for n, t in enumerate(c["topics"])
        ])
    out = []
    for i in range(max(len(x) for x in per_tab)):
        out.extend(x[i] for x in per_tab if i < len(x))
    return out


def day_index(d: date) -> int:
    return (d - date(1970, 1, 1)).days


def pick(data, d: date):
    ts = topics(data)
    return ts[day_index(d) % len(ts)]


def related_items(data, entry, limit=MAX_RELATED):
    """テーマに割り当てられた通達・記事から、種別が偏らないように選ぶ。"""
    tab, cls, name = entry["tab"], entry["cls"], entry["topic"]["name"]
    hits = [i for i in data["items"] if i.get("tags", {}).get(tab, {}).get(cls) == name]
    picked = []
    for kind in KIND_ORDER:
        first = next((i for i in hits if i["kind"] == kind), None)
        if first:
            picked.append(first)
        if len(picked) >= limit:
            break
    return picked, len(hits)


def table_lines(tb):
    lines = []
    if tb.get("caption"):
        lines.append("〔" + tb["caption"] + "〕")
    for row in tb["rows"][:MAX_TABLE_ROWS]:
        lines.append("・" + row[0] + ("：" + "／".join(row[1:]) if len(row) > 1 else ""))
    if len(tb["rows"]) > MAX_TABLE_ROWS:
        lines.append("（ほか" + str(len(tb["rows"]) - MAX_TABLE_ROWS) + "行は辞書で）")
    return lines


def build_message(data, entry):
    """投稿の本文。辞書の公開ページの URL は載せない。"""
    t = entry["topic"]
    lines = ["【今日の相続税区分】" + t["name"], "", "▶ 区分：" + entry["tab_label"] + "｜" + entry["cls_label"], "", t["desc"]]

    tables = ([t["table"]] if t.get("table") else []) + t.get("tables", [])
    if tables:
        lines += ["", "■ " + ("早見表" if entry["cls"] == "hyoka_hayami" else "表")]
        for tb in tables:
            lines += table_lines(tb)
    note = t.get("note") or (t.get("table") or {}).get("note")
    if note:
        lines += ["", "※ " + note]

    related, total = related_items(data, entry)
    if related:
        lines += ["", "■ 関係する通達・記事" + ("（全" + str(total) + "件）" if total > len(related) else "")]
        for i in related:
            no = (" " + i["number"]) if i.get("number") else ""
            lines.append("・" + KIND_LABEL[i["kind"]] + no + "「" + i["title"] + "」")
    links = t.get("links", [])
    if links and not related:
        lines += ["", "■ 関連ページ"]
        for link in links[:2]:
            lines.append("・" + link["title"] + " " + link["url"])

    lines += ["", " ".join(HASHTAGS[entry["tab"]] + ["#税務"])]
    return "\n".join(lines)


# ---------------------------------------------------------------- Facebook への投稿

def graph_base(version):
    return "https://graph.facebook.com/" + (version or "v23.0")


def resolve_token(page_id, token, version):
    """トークンの持ち主と FB_PAGE_ID が合っているかをログに出し、投稿に使うトークンを返す。

    個人（ユーザー）のトークンで、そのユーザーが FB_PAGE_ID のページを管理している場合は、ページのトークンを取り出して使う。
    ログは公開されることがあるので、持ち主の名前やIDは出さない。
    """
    import requests

    base = graph_base(version)
    try:
        me = requests.get(base + "/me", params={"fields": "id", "access_token": token}, timeout=30).json()
        if "error" in me:
            print("トークンの確認：使えません（" + me["error"].get("message", "") + "）", file=sys.stderr)
            return token
        if str(me.get("id")) == str(page_id).strip():
            print("トークンの確認：持ち主と FB_PAGE_ID が一致")
            return token
        accounts = requests.get(base + "/me/accounts", params={"fields": "id,access_token", "limit": 100, "access_token": token},
                                timeout=30).json()
        page = next((a for a in accounts.get("data", []) if str(a.get("id")) == str(page_id).strip()), None)
        if page and page.get("access_token"):
            print("トークンの確認：個人（ユーザー）のトークンです。管理しているページのトークンを取り出して投稿します。"
                  "ユーザーのトークンには期限があるので、FB_PAGE_ACCESS_TOKEN をページのアクセストークンに入れ替えてください。")
            return page["access_token"]
        print("トークンの確認：持ち主と FB_PAGE_ID が不一致（このトークンで管理できるページの中に FB_PAGE_ID のページがありません）")
    except Exception as e:  # noqa: BLE001  確認に失敗しても投稿は試す
        print("トークンの確認に失敗：" + str(e), file=sys.stderr)
    return token


def post(page_id, token, message, version=None, image=None):
    import requests

    base = graph_base(version) + "/" + page_id.strip()
    if image:
        with open(image, "rb") as fh:
            res = requests.post(base + "/photos", data={"caption": message, "access_token": token},
                                files={"source": (Path(image).name, fh, "image/png")}, timeout=120)
    else:
        res = requests.post(base + "/feed", data={"message": message, "access_token": token}, timeout=60)
    try:
        body = res.json()
    except ValueError:
        body = {}
    if not res.ok or "error" in body:
        err = body.get("error", {})
        raise RuntimeError("Facebook API error " + str(res.status_code) + ": " + (err.get("message") or res.text[:300]))
    return body


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date() if s else datetime.now(JST).date()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="投稿せずに本文を表示する")
    ap.add_argument("--date", help="この日（日本時間）のテーマを使う（YYYY-MM-DD）")
    ap.add_argument("--image", help="写真付きで投稿するときの画像（PNG）")
    args = ap.parse_args()

    data = load_data()
    entry = pick(data, parse_date(args.date))
    message = build_message(data, entry)

    image = args.image
    if image and not Path(image).exists():
        print(image + " がないため写真なしで投稿します。", file=sys.stderr)
        image = None

    page_id = os.environ.get("FB_PAGE_ID", "")
    token = os.environ.get("FB_PAGE_ACCESS_TOKEN", "")
    if args.dry_run or not page_id or not token:
        if not args.dry_run:
            print("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN が未設定のため投稿せず本文を表示します。", file=sys.stderr)
        print(message)
        return

    version = os.environ.get("FB_GRAPH_VERSION")
    token = resolve_token(page_id, token, version)
    result = post(page_id, token, message, version, image)
    print("posted: " + str(result.get("post_id") or result.get("id")) + "（" + entry["topic"]["name"] + ("・写真付き" if image else "") + "）")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
