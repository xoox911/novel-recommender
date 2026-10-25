"""rank_novels.py 的回归测试。

只依赖标准库，运行方式：
    python -m unittest discover -s tests -v
    python tests/test_rank_novels.py

每个用例对应代码审核报告里的一个具体缺陷，防止修复被后续改动破坏。
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, suppress
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import rank_novels as rn  # noqa: E402


def _cand(title, **over):
    """构造一条最小合法候选，可覆盖任意字段。"""
    base = {
        "title": title,
        "main_genre_match": True,
        "sub_tag_hits": 3,
        "word_count": 200,
        "platform_match": "primary",
        "update_match": "exact",
        "reputation": "strong_positive",
        "credibility": "verified",
    }
    base.update(over)
    return base


def _profile(**over):
    base = {
        "target_word_min": 100,
        "target_word_max": 300,
        "has_reference_work": False,
    }
    base.update(over)
    return base


class TmpJson:
    """临时 JSON 文件上下文，自动清理。"""

    def __init__(self):
        self.paths = []

    def write(self, obj, encoding="utf-8", raw=None):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        p = Path(path)
        data = raw if raw is not None else json.dumps(obj, ensure_ascii=False)
        p.write_text(data, encoding=encoding)
        self.paths.append(p)
        return p

    def cleanup(self):
        for p in self.paths:
            with suppress(OSError):
                p.unlink()


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = TmpJson()

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, cand, profile, *extra):
        """跑一遍 main，返回 (exit_code, stdout)。"""
        cp = self.tmp.write(cand)
        pp = self.tmp.write(profile)
        buf = io.StringIO()
        argv = sys.argv
        sys.argv = ["rank_novels.py", str(cp), "--profile", str(pp), *extra]
        try:
            with redirect_stdout(buf):
                code = rn.main()
        finally:
            sys.argv = argv
        return code, buf.getvalue()


class TestP0NaN(BaseCase):
    """P0-1：NaN / Infinity 不得穿过校验。"""

    def test_nan_similarity_rejected(self):
        cand = {"candidates": [_cand("书A", similarity="__NAN__")]}
        raw = json.dumps(cand, ensure_ascii=False).replace('"__NAN__"', "NaN")
        cp = self.tmp.write(None, raw=raw)
        pp = self.tmp.write(_profile(has_reference_work=True))
        buf = io.StringIO()
        argv = sys.argv
        sys.argv = ["x", str(cp), "--profile", str(pp)]
        try:
            with redirect_stdout(buf):
                code = rn.main()
        finally:
            sys.argv = argv
        out = buf.getvalue()
        self.assertEqual(code, 1, "NaN 输入应返回 1，实际 stdout=" + out)
        self.assertIn("非法字面量", out)
        self.assertNotIn("nan", out.lower().split("非法字面量")[0])

    def test_infinity_word_count_rejected(self):
        cand = {"candidates": [_cand("书A", word_count="__INF__")]}
        raw = json.dumps(cand, ensure_ascii=False).replace('"__INF__"', "Infinity")
        cp = self.tmp.write(None, raw=raw)
        pp = self.tmp.write(_profile())
        buf = io.StringIO()
        argv = sys.argv
        sys.argv = ["x", str(cp), "--profile", str(pp)]
        try:
            with redirect_stdout(buf):
                code = rn.main()
        finally:
            sys.argv = argv
        self.assertEqual(code, 1)
        self.assertIn("非法字面量", buf.getvalue())

    def test_need_number_rejects_non_finite(self):
        with self.assertRaises(rn.InputError) as ctx:
            rn._need_number(float("nan"), "similarity", "第 1 部")
        self.assertIn("有限数值", str(ctx.exception))
        with self.assertRaises(rn.InputError):
            rn._need_number(float("inf"), "word_count", "第 1 部")


class TestP0Status(BaseCase):
    """P0-2：already_read 不得覆盖显式的 status。"""

    def test_rejected_not_overwritten(self):
        cand = {
            "candidates": [
                _cand("活跃书"),
                _cand("弃书", status="rejected", already_read=True),
            ]
        }
        code, out = self.run_main(cand, _profile())
        self.assertEqual(code, 2, "冲突应报错而非静默改判")
        self.assertIn("冲突", out)

    def test_already_read_alone_means_read(self):
        cand = {
            "candidates": [
                _cand("活跃书"),
                _cand("旧标记", already_read=True),
            ]
        }
        code, out = self.run_main(cand, _profile())
        self.assertEqual(code, 0)
        self.assertIn("已读/在读 1 部", out)

    def test_rejected_alone_counted_as_rejected(self):
        cand = {
            "candidates": [
                _cand("活跃书"),
                _cand("弃书", status="rejected"),
            ]
        }
        code, out = self.run_main(cand, _profile())
        self.assertEqual(code, 0)
        self.assertIn("已否决 1 部", out)
        self.assertNotIn("已读/在读", out)


class TestP0Sort(BaseCase):
    """P0-3：同分排序的书名 tie-breaker 必须是升序。"""

    def test_title_ascending_for_ties(self):
        """同分按书名升序：布(U+5E03) < 查(U+67E5) < 阿(U+963F)。"""
        cand = {"candidates": [_cand("阿尔法"), _cand("查理"), _cand("布拉沃")]}
        code, out = self.run_main(cand, _profile())
        self.assertEqual(code, 0)
        order = [t for _, t in sorted((out.index(t), t) for t in ("阿尔法", "布拉沃", "查理"))]
        self.assertEqual(
            order, ["布拉沃", "查理", "阿尔法"], "同分应按书名升序，而不是 reverse=True 造成的降序"
        )

    def test_tiebreak_affects_region_cap_predictably(self):
        cand = {
            "candidates": [
                _cand("正常书A", region="战国"),
                _cand("正常书B", region="战国"),
            ]
        }
        code, out = self.run_main(cand, _profile(region_cap=1))
        self.assertEqual(code, 0)
        main_part, held_part = out.split("因主题重复暂缓")
        self.assertIn("正常书A", main_part, "书名靠前的一条优先进榜")
        self.assertIn("正常书B", held_part, "书名靠后的一条被主题分散暂缓")


class TestP0Alias(BaseCase):
    """P0-4：别名判重必须支持链式传递。"""

    def test_three_level_alias_chain(self):
        cand = {
            "candidates": [
                _cand("甲"),
                _cand("乙", aliases=["甲"]),
                _cand("丙", aliases=["乙"]),
            ]
        }
        code, out = self.run_main(cand, _profile(), "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1, "甲乙丙是同一本书，应合并为 1 条")
        self.assertEqual(len(payload["merged_duplicates"]), 2)

    def test_keeps_higher_score(self):
        cand = {
            "candidates": [
                _cand("低分版", sub_tag_hits=0),
                _cand("高分版", sub_tag_hits=3, aliases=["低分版"]),
            ]
        }
        code, out = self.run_main(cand, _profile(), "--json")
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["title"], "高分版")

    def test_book_title_marks_ignored(self):
        """书名号必须被忽略：中文书名几乎总带《》，别名常写裸名。"""
        cand = {
            "candidates": [
                _cand("《巨企、殖民地与星舰》", sub_tag_hits=4, aliases=["我是太空垃圾佬"]),
                _cand("《我是太空垃圾佬》", sub_tag_hits=3),
            ]
        }
        code, out = self.run_main(cand, _profile(), "--json")
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1, "带书名号的同名作品应合并成 1 条")

    def test_norm_name_strips_wrappers(self):
        self.assertEqual(rn._norm_name("《巨企》"), rn._norm_name("巨企"))
        self.assertEqual(rn._norm_name("「书名」"), rn._norm_name("书名"))
        self.assertEqual(rn._norm_name("  书 名  "), "书名")


class TestP0IO(BaseCase):
    """P0-5：编码与 IO 异常必须给出可读提示，不能裸崩。"""

    def test_gbk_file_reports_readable_error(self):
        # 必须含中文，纯 ASCII 内容在 GBK/UTF-8 下字节一致，不会触发解码错误
        cp = self.tmp.write(None, raw='{"candidates":[{"title":"中文书名"}]}', encoding="gbk")
        pp = self.tmp.write(_profile())
        buf = io.StringIO()
        argv = sys.argv
        sys.argv = ["x", str(cp), "--profile", str(pp)]
        try:
            with redirect_stdout(buf):
                code = rn.main()
        finally:
            sys.argv = argv
        self.assertEqual(code, 1)
        self.assertIn("UTF-8", buf.getvalue())

    def test_directory_path_reports_readable_error(self):
        pp = self.tmp.write(_profile())
        buf = io.StringIO()
        argv = sys.argv
        sys.argv = ["x", str(Path(tempfile.gettempdir())), "--profile", str(pp)]
        try:
            with redirect_stdout(buf):
                code = rn.main()
        finally:
            sys.argv = argv
        self.assertEqual(code, 1)
        self.assertIn("错误", buf.getvalue())

    def test_json_error_reports_line_column(self):
        cp = self.tmp.write(None, raw='{"candidates": [ {,} ]}')
        pp = self.tmp.write(_profile())
        buf = io.StringIO()
        argv = sys.argv
        sys.argv = ["x", str(cp), "--profile", str(pp)]
        try:
            with redirect_stdout(buf):
                code = rn.main()
        finally:
            sys.argv = argv
        self.assertEqual(code, 1)
        self.assertIn("行", buf.getvalue())


class TestScoring(unittest.TestCase):
    """打分模型本身。"""

    def test_weights_sum_to_100(self):
        total = (
            rn.W_GENRE
            + rn.W_SIMILARITY
            + rn.W_LENGTH
            + rn.W_PLATFORM
            + rn.W_UPDATE
            + rn.W_REPUTATION
        )
        self.assertEqual(total, 100)

    def test_no_reference_normalizes_to_100(self):
        item = dict(
            _cand("满分书", sub_tag_hits=3),
            similarity=None,
            tag_denominator=3,
            status="active",
            region="",
            aliases=[],
            note=None,
            author=None,
        )
        item["main_genre_match"] = True
        item["reputation"] = "strong_positive"
        profile = rn.validate_profile(_profile(tag_denominator=3))
        _, score = rn.score_candidate(item, profile)
        self.assertEqual(score, 100.0)

    def test_genre_cap_when_main_missed(self):
        """主类型未命中时题材分封顶 20，即使子标签全中。"""
        item = dict(
            _cand("相关书", main_genre_match=False, sub_tag_hits=5),
            tag_denominator=5,
            similarity=None,
            status="active",
            region="",
            aliases=[],
            note=None,
            author=None,
        )
        profile = rn.validate_profile(_profile(tag_denominator=5))
        self.assertEqual(rn.score_genre(item, profile), rn.GENRE_CAP_NO_MAIN)

    def test_length_band(self):
        self.assertEqual(rn.score_length(200, 100, 300), rn.W_LENGTH)
        self.assertEqual(rn.score_length(80, 100, 300), rn.LENGTH_PARTIAL_SCORE)
        self.assertEqual(rn.score_length(50, 100, 300), 0)
        self.assertEqual(rn.score_length(500, 100, 300), 0)
        self.assertEqual(rn.score_length(None, 100, 300), 0)
        self.assertEqual(rn.score_length(None, None, None), rn.W_LENGTH)


class TestValidation(BaseCase):
    """字段校验与清洗。"""

    def test_word_count_unit_confusion_rejected(self):
        cand = {"candidates": [_cand("单位错", word_count=2100000)]}
        code, out = self.run_main(cand, _profile())
        self.assertEqual(code, 2)
        self.assertIn("疑似把", out)

    def test_control_chars_stripped(self):
        cand = {"candidates": [_cand("恶意\x1b[2J\x1b[31m书名\x1b[0m")]}
        code, out = self.run_main(cand, _profile())
        self.assertEqual(code, 0)
        self.assertNotIn("\x1b", out, "ANSI 转义不应出现在输出里")
        self.assertIn("恶意[2J[31m书名[0m", out)

    def test_author_type_checked(self):
        cand = {"candidates": [_cand("书A", author={"name": "某人"})]}
        code, out = self.run_main(cand, _profile())
        self.assertEqual(code, 2)
        self.assertIn("author", out)

    def test_region_cap_null_falls_back_to_default(self):
        p = rn.validate_profile(_profile(region_cap=None))
        self.assertEqual(p["region_cap"], rn.DEFAULT_REGION_CAP)

    def test_region_cap_zero_disables(self):
        p = rn.validate_profile(_profile(region_cap=0))
        self.assertEqual(p["region_cap"], 0)
        kept, held = rn.diversify([{"item": {"region": "战国"}, "score": 1}] * 5, 0)
        self.assertEqual(len(kept), 5)
        self.assertEqual(held, [])

    def test_all_errors_reported_at_once(self):
        cand = {
            "candidates": [
                _cand("书A", platform_match="PRIMARY"),
                _cand("书B", reputation="bogus"),
                _cand("书C", update_match="maybe"),
            ]
        }
        code, out = self.run_main(cand, _profile())
        self.assertEqual(code, 2)
        self.assertIn("共 3 处", out)


class TestHardFilter(BaseCase):
    """P1-8：篇幅与可及性硬过滤必须在脚本内落地。"""

    def test_out_of_band_auto_dropped(self):
        cand = {
            "candidates": [
                _cand("正常书", word_count=200),
                _cand("超长书", word_count=1000),
            ]
        }
        code, out = self.run_main(cand, _profile(), "--json")
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["title"], "正常书")
        self.assertEqual(payload["auto_filtered_out_of_band"][0]["title"], "超长书")

    def test_unknown_word_count_kept(self):
        cand = {"candidates": [_cand("字未知", word_count=None)]}
        code, out = self.run_main(cand, _profile(), "--json")
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1, "字数未知不参与篇幅硬过滤")

    def test_inaccessible_split_out(self):
        cand = {
            "candidates": [
                _cand("可读书"),
                _cand("仅实体", platform_match="none"),
            ]
        }
        code, out = self.run_main(cand, _profile(), "--json")
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["inaccessible"][0]["title"], "仅实体")

    def test_all_filtered_returns_error(self):
        cand = {"candidates": [_cand("仅实体", platform_match="none")]}
        code, out = self.run_main(cand, _profile())
        self.assertEqual(code, 1)
        self.assertIn("没有剩余作品", out)


class TestCheckMode(BaseCase):
    """--check：只校验不排序，方便边填边验。"""

    def test_check_ok(self):
        cand = {"candidates": [_cand("书A"), _cand("书B")]}
        code, out = self.run_main(cand, _profile(), "--check")
        self.assertEqual(code, 0)
        self.assertIn("校验通过", out)
        self.assertNotIn("排序结果", out)

    def test_check_reports_errors(self):
        cand = {"candidates": [_cand("书A", sub_tag_hits=-1)]}
        code, out = self.run_main(cand, _profile(), "--check")
        self.assertEqual(code, 2)


class TestReputationAlias(BaseCase):
    """P1-4：别名映射要给出复核提示，不能静默抬分。"""

    def test_multi_positive_warns(self):
        cand = {"candidates": [_cand("书A", reputation="multi_positive")]}
        code, out = self.run_main(cand, _profile())
        self.assertEqual(code, 0)
        self.assertIn("multi_positive", out)
        self.assertIn("请复核", out)

    def test_mixed_warns(self):
        cand = {"candidates": [_cand("书A", reputation="mixed")]}
        code, out = self.run_main(cand, _profile())
        self.assertIn("语义模糊", out)


class TestSilentFailures(BaseCase):
    """漏填字段与处理次序：这些情况都能"算出一个分"，但结果不可信。"""

    def test_missing_similarity_warns(self):
        """有参考作品却没填 similarity，必须提示按 0 分计。"""
        cand = {"candidates": [_cand("甲书", sources=["https://example.com/a"])]}
        code, out = self.run_main(cand, _profile(has_reference_work=True), "--check")
        self.assertEqual(code, 0)
        self.assertIn("未填 similarity", out)

    def test_no_similarity_warning_without_reference(self):
        cand = {"candidates": [_cand("甲书", sources=["https://example.com/a"])]}
        code, out = self.run_main(cand, _profile(), "--check")
        self.assertNotIn("未填 similarity", out)

    def test_missing_sources_warns(self):
        """缺 sources 就无法追溯来源页面，不能静默放行。"""
        cand = {"candidates": [_cand("甲书")]}
        code, out = self.run_main(cand, _profile(), "--check")
        self.assertIn("未填 sources", out)

    def test_sources_carried_to_json(self):
        cand = {"candidates": [_cand("甲书", sources=["https://example.com/a"])]}
        code, out = self.run_main(cand, _profile(), "--json")
        payload = json.loads(out)
        self.assertEqual(payload["results"][0]["sources"], ["https://example.com/a"])

    def test_same_book_across_platform_merged(self):
        """同一本书一条可读、一条下架时，不得在主榜和延伸参考各出现一次。"""
        cand = {
            "candidates": [
                _cand("太空垃圾佬", sources=["u"]),
                _cand(
                    "巨企、殖民地与星舰",
                    aliases=["太空垃圾佬"],
                    platform_match="none",
                    sources=["u"],
                ),
            ]
        }
        code, out = self.run_main(cand, _profile(), "--json")
        payload = json.loads(out)
        self.assertEqual(payload["count"] + len(payload["inaccessible"]), 1, "同一本书只应保留一条")
        self.assertEqual(len(payload["merged_duplicates"]), 1)

    def test_region_whitespace_normalized(self):
        """背景只差一个空格时不能被当成两个地区，否则分散上限形同虚设。"""
        cand = {
            "candidates": [
                _cand("A", region="日本战国", sources=["u"]),
                _cand("B", region="日本 战国", sources=["u"]),
                _cand("C", region="日本战国", sources=["u"]),
            ]
        }
        code, out = self.run_main(cand, _profile(region_cap=2), "--json")
        payload = json.loads(out)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["held_by_region"]), 1)

    def test_region_fullwidth_normalized(self):
        self.assertEqual(rn._norm_region("日本 战国"), rn._norm_region("日本战国"))
        self.assertEqual(rn._norm_region("ＷＷＩＩ"), rn._norm_region("wwii"))
        self.assertEqual(rn._norm_region("  二战德国 "), "二战德国")

    def test_note_length_relaxed(self):
        """偏好摘要属于长文本，1000 字以内不应被当成脏数据拒绝。"""
        cand = {"candidates": [_cand("书", note="注" * 900, sources=["u"])]}
        code, out = self.run_main(cand, _profile(), "--check")
        self.assertEqual(code, 0, out)

        cand_long = {"candidates": [_cand("书", note="注" * 1001, sources=["u"])]}
        code, out = self.run_main(cand_long, _profile(), "--check")
        self.assertEqual(code, 2)
        self.assertIn("超过", out)

    def test_sub_tag_over_denominator_warns(self):
        cand = {"candidates": [_cand("书", sub_tag_hits=9, tag_denominator=3, sources=["u"])]}
        code, out = self.run_main(cand, _profile(), "--check")
        self.assertEqual(code, 0)
        self.assertIn("大于标签总数", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
