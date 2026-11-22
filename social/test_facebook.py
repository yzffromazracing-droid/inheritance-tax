"""Facebook 投稿スクリプトのテスト（python3 -m unittest discover -s social）。"""
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import already_posted as ap  # noqa: E402
import facebook_image as fi  # noqa: E402
import facebook_post as fp  # noqa: E402

DATA = fp.load_data()


class TopicsTest(unittest.TestCase):
    def test_every_topic_once_per_cycle(self):
        ts = fp.topics(DATA)
        total = sum(len(c["topics"]) for tab in fp.TAB_ORDER for c in DATA["bunrui"][tab]["classes"])
        self.assertEqual(len(ts), total)
        keys = {(t["tab"], t["cls"], t["index"]) for t in ts}
        self.assertEqual(len(keys), len(ts))

    def test_consecutive_days_rotate_tabs(self):
        start = date(2026, 11, 20)
        tabs = [fp.pick(DATA, start + timedelta(days=i))["tab"] for i in range(4)]
        self.assertEqual(len(set(tabs)), 4)

    def test_cycle_repeats(self):
        n = len(fp.topics(DATA))
        d = date(2026, 11, 20)
        self.assertEqual(fp.pick(DATA, d)["topic"]["name"], fp.pick(DATA, d + timedelta(days=n))["topic"]["name"])

    def test_index_points_to_topic(self):
        for t in fp.topics(DATA):
            cls = next(c for c in DATA["bunrui"][t["tab"]]["classes"] if c["key"] == t["cls"])
            self.assertEqual(cls["topics"][t["index"]]["name"], t["topic"]["name"])


class MessageTest(unittest.TestCase):
    def test_message_contents(self):
        for t in fp.topics(DATA):
            msg = fp.build_message(DATA, t)
            self.assertIn("【今日の相続税区分】" + t["topic"]["name"], msg)
            self.assertNotIn("github.io", msg)
            self.assertNotIn("#sub=", msg)
            self.assertIn(fp.HASHTAGS[t["tab"]][0], msg)
            self.assertLess(len(msg), 5000)

    def test_table_rows_in_message(self):
        t = next(x for x in fp.topics(DATA) if x["topic"]["name"] == "相続税の税率（速算表）")
        msg = fp.build_message(DATA, t)
        self.assertIn("・1,000万円以下：10％／－", msg)
        self.assertIn("・6億円超：55％／7,200万円", msg)

    def test_related_items_mixed_kinds(self):
        t = next(x for x in fp.topics(DATA) if x["topic"]["name"] == "相続税額の2割加算")
        picked, total = fp.related_items(DATA, t)
        self.assertEqual(len({i["kind"] for i in picked}), len(picked))
        self.assertGreaterEqual(total, len(picked))

    def test_related_items_have_nta_links(self):
        t = next(x for x in fp.topics(DATA) if x["topic"]["name"] == "相続税額の2割加算")
        msg = fp.build_message(DATA, t)
        picked, _ = fp.related_items(DATA, t)
        for i in picked:
            self.assertIn("　" + i["url"], msg)
            self.assertTrue(i["url"].startswith("https://www.nta.go.jp/"))


class PostTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        class Res:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return {"id": "1", "post_id": "1_2"}

        def fake_post(url, data=None, files=None, timeout=None):
            self.calls.append((url, data, files))
            return Res()

        self.saved = sys.modules.get("requests")
        sys.modules["requests"] = types.SimpleNamespace(post=fake_post)

    def tearDown(self):
        if self.saved is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = self.saved

    def test_photo_post(self):
        img = Path(__file__).resolve().parent / "test_facebook.py"  # 中身は問わない
        fp.post("123 ", "tok", "本文", "v23.0", str(img))
        url, data, files = self.calls[0]
        self.assertEqual(url, "https://graph.facebook.com/v23.0/123/photos")
        self.assertEqual(data, {"caption": "本文", "access_token": "tok"})
        self.assertIn("source", files)

    def test_text_post(self):
        fp.post("123", "tok", "本文")
        url, data, files = self.calls[0]
        self.assertEqual(url, "https://graph.facebook.com/v23.0/123/feed")
        self.assertEqual(data["message"], "本文")
        self.assertIsNone(files)


class ImageTest(unittest.TestCase):
    def test_svg_valid_for_every_topic(self):
        for t in fp.topics(DATA):
            svg = fi.build_svg(DATA, t)
            ET.fromstring(svg)

    def test_wrap_keeps_ascii_words(self):
        lines = fi.wrap("後継者不在でも引き継げるM&A", 13, 3)
        self.assertTrue(any("M&A" in line for line in lines))
        self.assertEqual("".join(lines), "後継者不在でも引き継げるM&A")

    def test_wrap_no_open_bracket_at_line_end(self):
        lines = fi.wrap("相続時精算課税の税率（20％）", 12, 2)
        self.assertFalse(any(line.endswith("（") for line in lines))
        self.assertEqual("".join(lines), "相続時精算課税の税率（20％）")

    def test_wrap_truncates(self):
        lines = fi.wrap("あ" * 100, 10, 2)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("…"))


class AlreadyPostedTest(unittest.TestCase):
    def test_jst_midnight(self):
        from datetime import datetime, timezone
        # 日本時間 11/21 23:57（UTC 14:57）は 11/21 の0時（UTC 11/20 15:00）から数える
        self.assertEqual(ap.jst_midnight_utc(datetime(2026, 11, 21, 14, 57, tzinfo=timezone.utc)), "2026-11-20T15:00:00Z")
        # 日本時間 11/22 0:30（UTC 11/21 15:30）は 11/22 の0時から
        self.assertEqual(ap.jst_midnight_utc(datetime(2026, 11, 21, 15, 30, tzinfo=timezone.utc)), "2026-11-21T15:00:00Z")

    def test_posted_line(self):
        log = "2026-11-22T08:48:33.2235396Z トークンの確認：持ち主と FB_PAGE_ID が一致\n" \
              "2026-11-22T08:48:33.2236296Z posted: ***_122123939181506173（暦年課税の基礎控除（110万円）・写真付き）\n"
        self.assertTrue(ap.has_posted_line(log))
        self.assertFalse(ap.has_posted_line("2026-11-22T08:48:33Z 【今日の相続税区分】暦年課税の基礎控除\n"))


if __name__ == "__main__":
    unittest.main()
