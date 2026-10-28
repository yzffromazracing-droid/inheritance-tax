"""前回の辞書データと今回取得したデータを比べ、追加・削除・更新された項目をまとめる。"""

# 比べる項目のフィールド（取得日などは含めない）
FIELDS = ("title", "number", "category", "url", "asof", "date", "dept", "html", "tags")

KIND_LABEL = {
    "kihon": "相続税法基本通達", "hyoka": "財産評価基本通達", "so": "措置法通達", "kobetsu": "個別通達",
    "ta": "タックスアンサー", "qa": "質疑応答事例", "bk": "文書回答事例",
}


def compare(old_items, new_items) -> dict:
    old = {i["id"]: i for i in old_items}
    new = {i["id"]: i for i in new_items}
    added = [new[k] for k in new if k not in old]
    removed = [old[k] for k in old if k not in new]
    changed = [new[k] for k in new if k in old and any(old[k].get(f) != new[k].get(f) for f in FIELDS)]
    return {"added": added, "removed": removed, "changed": changed}


def has_changes(diff) -> bool:
    return any(diff[k] for k in ("added", "removed", "changed"))


def _brief(item):
    return {"id": item["id"], "kind": item["kind"], "number": item.get("number", ""), "title": item["title"], "url": item["url"]}


def history_entry(day, diff, bunrui_changed=False) -> dict:
    """docs/data/updates.json に追記する 1 回分の更新記録。"""
    return {
        "date": day,
        "added": [_brief(i) for i in diff["added"]],
        "removed": [_brief(i) for i in diff["removed"]],
        "changed": [_brief(i) for i in diff["changed"]],
        "bunruiChanged": bunrui_changed,
    }


def report(day, diff, total, bunrui_changed=False, limit=40) -> str:
    """コミットメッセージに使う変更の要約。"""
    a, r, c = len(diff["added"]), len(diff["removed"]), len(diff["changed"])
    lines = [f"国税庁データの更新（{day}取得）：追加{a}件・削除{r}件・更新{c}件", "",
             f"収録 {total:,} 件。"]
    if bunrui_changed:
        lines.append("区分・テーマの整理表も変わっています。")
    for key, label in (("added", "追加"), ("removed", "削除"), ("changed", "更新")):
        items = diff[key]
        if not items:
            continue
        lines += ["", f"## {label}（{len(items)}件）"]
        for i in items[:limit]:
            no = f" {i['number']}" if i.get("number") else ""
            lines.append(f"- [{KIND_LABEL.get(i['kind'], i['kind'])}{no}] {i['title']}")
        if len(items) > limit:
            lines.append(f"- ほか {len(items) - limit} 件")
    untagged = [i for i in diff["added"] if not i.get("tags")]
    if untagged:
        lines += ["", f"## 区分に割り当てられなかった追加項目（{len(untagged)}件）",
                  "scraper/bunrui.py の規則に当てはまらず、通達タブ・国税庁の記事タブにだけ表示されます。"]
        lines += [f"- [{KIND_LABEL.get(i['kind'], i['kind'])}] {i['title']}" for i in untagged[:limit]]
    return "\n".join(lines) + "\n"
