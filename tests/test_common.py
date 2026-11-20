import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import common  # noqa: E402


class ParseDateTest(unittest.TestCase):
    def test_iso_and_chinese_dates(self):
        self.assertEqual(common.parse_date("2026-11-12"), "2026-11-12")
        self.assertEqual(common.parse_date("2026年11月12日"), "2026-11-12")
        self.assertEqual(common.parse_date("20261112"), "2026-11-12")
        self.assertEqual(common.parse_date(""), "")

    def test_invalid_date_is_empty(self):
        self.assertEqual(common.parse_date("2026-13-40"), "")


class HtmlTest(unittest.TestCase):
    def test_descendant_and_class_selector(self):
        tree = common.parse_html(
            '<div class="a"><p class="b">one</p><p>two</p></div>'
        )
        self.assertEqual(len(tree.select("div.a p")), 2)
        self.assertEqual(len(tree.select("div.a > p.b")), 1)
        self.assertEqual(tree.select_one(".b").text(sep=" "), "one")

    def test_attribute_selector(self):
        tree = common.parse_html('<meta name="author" content="张三">')
        self.assertEqual(common.meta_content(tree, ["author"]), "张三")


class TextTest(unittest.TestCase):
    def test_truncate_keeps_limit(self):
        text = common.truncate("一二三四五六七八九十", limit=5)
        self.assertLessEqual(len(text), 5)
        self.assertTrue(text.endswith("…"))

    def test_first_sentences_does_not_rewrite(self):
        text = "第一句。第二句。第三句。"
        self.assertTrue(common.first_sentences(text, limit=20).startswith("第一句"))


class LoadIndexTest(unittest.TestCase):
    def test_missing_items_raises_given_error(self):
        class Boom(Exception):
            pass

        with self.assertRaises(Boom):
            common.load_index(ROOT / "no-such-index.json", Boom, "hint")


if __name__ == "__main__":
    unittest.main()