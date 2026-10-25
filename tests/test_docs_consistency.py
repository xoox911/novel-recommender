"""文档与脚本的口径一致性测试。

权重表、口碑六档、可信度四档、候选 status 同时出现在 SKILL.md、README.md
和 scripts/rank_novels.py。这三处靠人眼同步迟早漂移，这里把它们锁死：
改代码漏改文档，或改文档漏改代码，都直接测试失败。
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import rank_novels as rn  # noqa: E402

# 文档里的维度名 -> 脚本常量名
WEIGHT_KEYS = {
    "题材与标签契合": "W_GENRE",
    "与参考作品相似度": "W_SIMILARITY",
    "篇幅契合": "W_LENGTH",
    "平台可及性": "W_PLATFORM",
    "舆论质量": "W_REPUTATION",
    "更新状态匹配": "W_UPDATE",
}


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _table(text, header):
    """取出以 header 开头的表格的数据行，跳过表头与分隔行。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == header:
            rows = []
            for row in lines[i + 2 :]:
                if not row.startswith("|"):
                    break
                rows.append([c.strip() for c in row.strip("|").split("|")])
            return rows
    raise AssertionError(f"找不到表格表头：{header}")


def _num(cell):
    found = re.search(r"\d+", cell.replace("*", ""))
    if not found:
        raise AssertionError(f"单元格里没有数字：{cell}")
    return int(found.group())


class TestWeightTables(unittest.TestCase):
    def test_skill_md_weights_match_script(self):
        rows = _table(_read("SKILL.md"), "| 维度 | 权重 | 评分要点 |")
        self.assertEqual(len(rows), 6, "阶段五权重表应有 6 行")
        for name, value, *_ in rows:
            key = WEIGHT_KEYS.get(name.strip("*"))
            self.assertIsNotNone(key, f"未知的权重维度：{name}")
            self.assertEqual(_num(value), getattr(rn, key), f"{name} 与 {key} 不一致")

    def test_readme_weights_match_script(self):
        rows = _table(_read("README.md"), "| 维度 | 权重 | 计分方式 |")
        self.assertEqual(len(rows), 6, "README 打分模型表应有 6 行")
        for name, value, *_ in rows:
            key = WEIGHT_KEYS.get(name.strip("*"))
            self.assertIsNotNone(key, f"未知的权重维度：{name}")
            self.assertEqual(_num(value), getattr(rn, key), f"{name} 与 {key} 不一致")

    def test_weights_sum_to_100(self):
        total = sum(getattr(rn, key) for key in WEIGHT_KEYS.values())
        self.assertEqual(total, 100)


class TestReputationTiers(unittest.TestCase):
    def test_skill_md_six_tiers(self):
        rows = _table(_read("SKILL.md"), "| 档位 | 判定条件 | 分数 |")
        self.assertEqual(len(rows), 6, "舆论质量应为六档")
        doc = {r[0].strip("*"): _num(r[2]) for r in rows}
        self.assertEqual(doc, rn.REPUTATION_SCORE)

    def test_readme_scores_match_script(self):
        text = _read("README.md")
        pattern = r"`(" + "|".join(rn.REPUTATION_SCORE) + r")` (\d+)"
        found = dict(re.findall(pattern, text))
        self.assertEqual(len(found), 6, "README 应完整列出六档分值且各出现一次")
        self.assertEqual({k: int(v) for k, v in found.items()}, rn.REPUTATION_SCORE)


class TestEnumValues(unittest.TestCase):
    def test_credibility_labels(self):
        rows = _table(_read("SKILL.md"), "| 标记 | 触发条件 |")
        self.assertEqual(len(rows), 4, "信息标注应为四档")
        labels = {r[0].strip("* ") for r in rows}
        self.assertEqual(labels, set(rn.CREDIBILITY_LABEL.values()))

    def test_status_values(self):
        rows = _table(_read("SKILL.md"), "| status | 含义 | 后续行为 |")
        self.assertEqual([r[0] for r in rows], list(rn.STATUS_VALUES))

    def test_platform_match_values(self):
        self.assertEqual(tuple(rn.PLATFORM_SCORE), ("primary", "secondary", "none"))
        text = _read("references/output-template.md")
        self.assertIn("primary / secondary / none", text)


class TestReferenceTopology(unittest.TestCase):
    def test_skill_links_resolve(self):
        for rel in re.findall(r"\]\((references/[^)]+)\)", _read("SKILL.md")):
            self.assertTrue((ROOT / rel).exists(), f"SKILL.md 指向的文件不存在：{rel}")

    def test_references_do_not_cross_link(self):
        for path in sorted((ROOT / "references").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            hits = re.findall(r"\]\((?:\./)?[\w-]+\.md\)", text)
            self.assertEqual(hits, [], f"{path.name} 里引用了其他 reference：{hits}")


if __name__ == "__main__":
    unittest.main()
