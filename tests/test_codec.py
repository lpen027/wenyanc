import unittest

from wenyanc import codec
from wenyanc.translator import _clean, detect_lang

SAMPLE = "壬寅年春工長李四議改爐誤差三分一部費八十六萬期四十五日"


class TestCodec(unittest.TestCase):
    def test_roundtrip_all(self):
        for algo in codec.ALGOS:
            for gbk in (True, False):
                blob = codec.encode(SAMPLE, "zh", algo=algo, use_gbk=gbk)
                text, lang = codec.decode(blob)
                self.assertEqual(text, SAMPLE, f"{algo} gbk={gbk}")
                self.assertEqual(lang, "zh")

    def test_gbk_smaller(self):
        b_gbk = codec.encode(SAMPLE, "zh", algo="raw", use_gbk=True)
        b_utf = codec.encode(SAMPLE, "zh", algo="raw", use_gbk=False)
        self.assertLess(len(b_gbk), len(b_utf))

    def test_gbk_fallback_on_rare_chars(self):
        rare = "㐀㐁㐂"  # GBK 之外
        blob = codec.encode(rare, "zh", algo="raw", use_gbk=True)
        self.assertEqual(codec.decode(blob)[0], rare)

    def test_bad_magic(self):
        with self.assertRaises(ValueError):
            codec.decode(b"XXXX" + b"\0" * 20)

    def test_truncation_detected(self):
        blob = codec.encode(SAMPLE, "zh", algo="lzma")
        with self.assertRaises(Exception):
            codec.decode(blob[:-6])


class TestClean(unittest.TestCase):
    def test_think_block(self):
        lt, gt = chr(60), chr(62)
        tag_open = lt + "think" + gt
        tag_close = lt + "/think" + gt
        self.assertEqual(_clean(tag_open + "思考" + tag_close + "\n\n实际答案。"), "实际答案。")
        # 只有开标记、没有闭合：只剥标记，保留其后正文
        self.assertEqual(_clean(tag_open + "思考" + "\n\n实际答案。"), "思考实际答案。")

    def test_meta_prefix_stripped_not_whole_line(self):
        self.assertEqual(_clean("译文如下：水泵失败。"), "水泵失败。")

    def test_passthrough(self):
        self.assertEqual(_clean("水泵於五月十二失败。"), "水泵於五月十二失败。")


class TestDetectLang(unittest.TestCase):
    def test_scripts(self):
        self.assertEqual(detect_lang("子曰學而時習之"), "zh")
        self.assertEqual(detect_lang("これは日本語の文章です"), "ja")
        self.assertEqual(detect_lang("Привет как дела"), "ru")
        self.assertEqual(detect_lang("مرحبا بالعالم"), "ar")

    def test_latin_disambiguation(self):
        self.assertEqual(detect_lang("Le président de la coopérative a demandé une étude"), "fr")
        self.assertEqual(detect_lang("El puerto de Valparaíso cambió el sistema de turnos"), "es")
        self.assertEqual(detect_lang("The team began building a system that remembers"), "en")


if __name__ == "__main__":
    unittest.main()
