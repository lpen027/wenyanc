import os
import tempfile
import unittest

from wenyanc import pack as P

TEXTS = [
    "二〇二五年三月，宁波一厂议改热处理线。返修率三点八分。",
    "周工主其事，记三月炉温曲线，费八十六万元。",
    "网带炉传送带跑偏，供应商两调乃解。",
    "二〇二四年二月，鹿特丹四人造记忆系统，索引二百四十毫秒。",
    "系统存原话，不存摘要。",
]
# 规模测试用：30 条互不相同的句子（含量级不同的数字，避免被字典吃成极端值）
BULK = ["二〇二%d年%d月，第%d厂议改第%d车间，返修率%d点%d分，费%d万元，工期%d日。"
        % (i % 10, i % 12 + 1, i, i % 7, i % 9, i % 10, i * 3 + 1, i % 40 + 5)
        for i in range(30)]


class TestPack(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "a.wypack")
        self.info = P.pack(
            [{"text": t, "lang": "zh", "tags": ["测试"], "src": "s%d" % i}
             for i, t in enumerate(TEXTS)],
            self.path,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_count_and_layout(self):
        head = P.read_head(self.path)
        self.assertEqual(head["count"], len(TEXTS))
        self.assertEqual(len(head["entries"]), len(TEXTS))

    def test_index_stays_slim_when_many(self):
        path = os.path.join(self.dir, "bulk.wypack")
        info = P.pack([{"text": t, "src": "s"} for t in BULK], path)
        self.assertLessEqual(info["index_pct"], 40.0,
                             "索引占 %.1f%%（%d 条）" % (info["index_pct"], len(BULK)))

    def test_roundtrip_each_entry(self):
        head = P.read_head(self.path)
        stream = P._stream(self.path, head)
        for i, t in enumerate(TEXTS):
            self.assertEqual(P.get(self.path, i, head, stream)["text"], t)

    def test_id_formats(self):
        head = P.read_head(self.path)
        stream = P._stream(self.path, head)
        self.assertEqual(P.get(self.path, "n001", head, stream)["text"], TEXTS[1])
        self.assertEqual(P.get(self.path, "1", head, stream)["text"], TEXTS[1])

    def test_meta_preserved(self):
        e = P.get(self.path, 0)
        self.assertEqual(e["lang"], "zh")
        self.assertEqual(e["src"], "s0")
        self.assertIn("测试", e["tags"])
        self.assertRegex(e["ts"], r"^\d{4}-\d{2}-\d{2}T")

    def test_search_any_and_all(self):
        self.assertTrue(len(P.search(self.path, ["周工", "鹿特丹"])) >= 2)
        self.assertEqual(P.search(self.path, ["周工", "鹿特丹"], mode="all"), [])
        hits = P.search(self.path, ["返修"], mode="all")
        self.assertEqual(len(hits), 1)
        self.assertIn("返修", hits[0]["text"])

    def test_unpack_writes_files(self):
        out = os.path.join(self.dir, "out")
        files = P.unpack(self.path, out)
        self.assertEqual(len(files), len(TEXTS))
        with open(files[0], encoding="utf-8") as f:
            self.assertEqual(f.read(), TEXTS[0])

    def test_pack_smaller_than_separate_when_many(self):
        from wenyanc import codec
        path = os.path.join(self.dir, "bulk.wypack")
        info = P.pack([{"text": t, "src": "s"} for t in BULK], path)
        sep = sum(len(codec.encode(t, "zh", algo="auto")) for t in BULK)
        self.assertLess(info["total_bytes"], sep,
                        "pack %d B vs 逐条 %d B" % (info["total_bytes"], sep))


if __name__ == "__main__":
    unittest.main()
