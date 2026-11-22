#!/usr/bin/env python3
"""今日（日本時間）すでに Facebook に投稿したかを、このワークフローの実行ログから確かめる。

    python3 social/already_posted.py

GitHub の予約は何時間も遅れて起動することがあり、強制投稿と重なると同じテーマを二重に投稿してしまう。
そこで、今日作られたこのワークフローの実行（いま動いている実行を除く）のジョブログに
facebook_post.py が出す「posted: 」の行があれば投稿済みとみなし、GITHUB_OUTPUT に skip=true を書く。

環境変数（GitHub Actions が用意する）: GITHUB_TOKEN（actions: read）, GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_OUTPUT
確認に失敗したときは、その日の投稿が抜けないよう投稿を続ける（skip=false）。
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
WORKFLOW = "facebook-post.yml"
POSTED = re.compile(r"^\S*\s?posted: ", re.M)


def jst_midnight_utc(now=None):
    """今日（日本時間）の0時を UTC の ISO 形式で返す。"""
    now = now or datetime.now(timezone.utc)
    d = now.astimezone(JST).date()
    return datetime(d.year, d.month, d.day, tzinfo=JST).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def has_posted_line(log_text):
    return bool(POSTED.search(log_text))


def already_posted(repo, token, current_run_id, since):
    import requests

    api = "https://api.github.com/repos/" + repo
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
    runs = requests.get(api + "/actions/workflows/" + WORKFLOW + "/runs",
                        params={"created": ">=" + since, "per_page": 50}, headers=headers, timeout=30)
    runs.raise_for_status()
    for run in runs.json().get("workflow_runs", []):
        if str(run["id"]) == str(current_run_id):
            continue
        jobs = requests.get(api + "/actions/runs/" + str(run["id"]) + "/jobs", headers=headers, timeout=30)
        jobs.raise_for_status()
        for job in jobs.json().get("jobs", []):
            log = requests.get(api + "/actions/jobs/" + str(job["id"]) + "/logs", headers=headers, timeout=60)
            if log.ok and has_posted_line(log.text):
                return run["html_url"]
    return None


def main():
    skip = False
    try:
        url = already_posted(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"],
                             os.environ.get("GITHUB_RUN_ID", ""), jst_midnight_utc())
        if url:
            skip = True
            print("今日はすでに投稿済みのため、投稿しません（" + url + "）")
        else:
            print("今日はまだ投稿していません。投稿します。")
    except Exception as e:  # noqa: BLE001  確認に失敗しても投稿は抜かさない
        print("投稿済みかの確認に失敗したため、投稿を続けます：" + str(e), file=sys.stderr)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write("skip=" + ("true" if skip else "false") + "\n")


if __name__ == "__main__":
    main()
