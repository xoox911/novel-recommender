#!/usr/bin/env python3
"""按匹配度对小说候选打分并排序。

用法:
    python rank_novels.py candidates.json --profile profile.json
    python rank_novels.py candidates.json --profile profile.json --json

脚本只做加权计算与排序，不做语义判断。
标签是否命中、口碑落在哪一档，需在检索阶段人工判定后写入 candidates.json。

退出码:
    0  正常
    1  文件不存在 / JSON 解析失败
    2  输入字段校验失败（会列出全部错误位置）
"""

import argparse
import json
import sys
import unicodedata
from pathlib import Path

W_GENRE = 30
W_SIMILARITY = 20
W_LENGTH = 15
W_PLATFORM = 15
W_UPDATE = 5
W_REPUTATION = 15

PLATFORM_SCORE = {"primary": 15, "secondary": 8, "none": 0}
UPDATE_SCORE = {"exact": 5, "acceptable": 3, "mismatch": 0}
REPUTATION_SCORE = {
    "strong_positive": 15,
    "positive_quiet": 11,
    "polarized_style": 9,
    "polarized_flaw": 5,
    "single_source": 4,
    "mostly_negative": 2,
}
REPUTATION_ALIASES = {
    "multi_positive": "strong_positive",
    "mixed": "polarized_style",
    "single": "single_source",
}

CREDIBILITY_LABEL = {
    "verified": "已核实",
    "pending": "待核实",
    "incomplete": "信息不全",
    "unknown": "来源不明",
}

STATUS_VALUES = ("active", "read", "rejected", "excluded")
STATUS_LABEL = {
    "read": "已读/在读",
    "rejected": "已否决",
    "excluded": "已过滤",
}
DEFAULT_REGION_CAP = 3


class InputError(Exception):
    """单个字段的校验错误。"""


def _configure_stdout():
    """Windows 控制台中文输出兼容。"""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _dwidth(text):
    """计算终端显示宽度，中文占两格。"""
    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _pad(text, width):
    """按显示宽度左对齐补空格。"""
    text = str(text)
    gap = width - _dwidth(text)
    return text + " " * max(gap, 0)


def _truncate(text, width):
    """按显示宽度截断，超出补省略号。"""
    text = str(text)
    if _dwidth(text) <= width:
        return text
    out = ""
    used = 0
    for ch in text:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + cw > width - 2:
            break
        out += ch
        used += cw
    return out + ".."


def _need_number(value, field, where, allow_none=False):
    if value is None:
        if allow_none:
            return None
        raise InputError(f"{where}：缺少必填字段 {field}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(
            f"{where}：{field} 应为数字，实际为 {value!r}（{type(value).__name__}）"
        )
    return float(value)


def _need_int(value, field, where, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(
            f"{where}：{field} 应为整数，实际为 {value!r}（{type(value).__name__}）"
        )
    if minimum is not None and value < minimum:
        raise InputError(f"{where}：{field} 不能小于 {minimum}，实际为 {value}")
    return value


def validate_profile(raw):
    """校验 profile，返回清洗后的字典。"""
    if not isinstance(raw, dict):
        raise InputError("profile.json 必须是 JSON 对象，不能是数组或其他类型")

    low = _need_number(raw.get("target_word_min"), "target_word_min", "profile", allow_none=True)
    high = _need_number(raw.get("target_word_max"), "target_word_max", "profile", allow_none=True)
    if low is not None and high is not None and low > high:
        raise InputError(f"profile：target_word_min（{low}）大于 target_word_max（{high}）")

    has_ref = raw.get("has_reference_work", False)
    if not isinstance(has_ref, bool):
        raise InputError("profile：has_reference_work 必须是 true 或 false")

    denom = raw.get("tag_denominator")
    if denom is not None:
        denom = _need_int(denom, "tag_denominator", "profile", minimum=1)

    region_cap = raw.get("region_cap", DEFAULT_REGION_CAP)
    if region_cap is not None:
        region_cap = _need_int(region_cap, "region_cap", "profile", minimum=0)

    return {
        "target_word_min": low,
        "target_word_max": high,
        "has_reference_work": has_ref,
        "tag_denominator": denom,
        "region_cap": region_cap,
        "note": raw.get("note"),
    }


def validate_candidate(idx, raw):
    """校验单条候选，返回清洗后的字典。"""
    where = f"第 {idx + 1} 部候选"
    if not isinstance(raw, dict):
        raise InputError(f"{where}：不是 JSON 对象")

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise InputError(f"{where}：缺少有效 title")
    where = f"第 {idx + 1} 部《{title}》"

    main = raw.get("main_genre_match")
    if not isinstance(main, bool):
        raise InputError(f"{where}：main_genre_match 应为 true/false，实际为 {main!r}")

    hits = _need_int(raw.get("sub_tag_hits"), "sub_tag_hits", where, minimum=0)

    word = _need_number(raw.get("word_count"), "word_count", where, allow_none=True)
    if word is not None and word <= 0:
        raise InputError(f"{where}：word_count 必须大于 0，实际为 {word}")

    platform = raw.get("platform_match")
    if platform not in PLATFORM_SCORE:
        raise InputError(
            f"{where}：platform_match 取值非法 {platform!r}，"
            f"只能是 {'/'.join(PLATFORM_SCORE)}"
        )

    update = raw.get("update_match")
    if update not in UPDATE_SCORE:
        raise InputError(
            f"{where}：update_match 取值非法 {update!r}，"
            f"只能是 {'/'.join(UPDATE_SCORE)}"
        )

    reputation = raw.get("reputation")
    reputation = REPUTATION_ALIASES.get(reputation, reputation)
    if reputation not in REPUTATION_SCORE:
        raise InputError(
            f"{where}：reputation 取值非法 {raw.get('reputation')!r}，"
            f"只能是 {'/'.join(REPUTATION_SCORE)}"
        )

    credibility = raw.get("credibility", "unknown")
    if credibility not in CREDIBILITY_LABEL:
        raise InputError(
            f"{where}：credibility 取值非法 {credibility!r}，"
            f"只能是 {'/'.join(CREDIBILITY_LABEL)}"
        )

    similarity = raw.get("similarity")
    if similarity is not None:
        similarity = _need_number(similarity, "similarity", where)
        if similarity < 0 or similarity > W_SIMILARITY:
            raise InputError(
                f"{where}：similarity 应在 0–{W_SIMILARITY} 之间，实际为 {similarity}"
            )

    denom = raw.get("tag_denominator")
    if denom is not None:
        denom = _need_int(denom, "tag_denominator", where, minimum=1)

    already_read = raw.get("already_read", False)
    if not isinstance(already_read, bool):
        raise InputError(f"{where}：already_read 应为 true/false")

    status = raw.get("status", "active")
    if not isinstance(status, str) or status not in STATUS_VALUES:
        raise InputError(
            f"{where}：status 取值非法 {status!r}，只能是 {'/'.join(STATUS_VALUES)}"
        )
    if already_read:
        status = "read"

    region = raw.get("region")
    if region is not None and not isinstance(region, str):
        raise InputError(f"{where}：region 应为字符串（地理或时代背景），实际为 {region!r}")

    aliases = raw.get("aliases") or []
    if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
        raise InputError(f"{where}：aliases 应为字符串数组")

    return {
        "title": title.strip(),
        "aliases": [a.strip() for a in aliases if a.strip()],
        "author": raw.get("author"),
        "main_genre_match": main,
        "sub_tag_hits": hits,
        "similarity": similarity,
        "word_count": word,
        "platform_match": platform,
        "update_match": update,
        "reputation": reputation,
        "credibility": credibility,
        "tag_denominator": denom,
        "status": status,
        "region": (region or "").strip(),
        "note": raw.get("note"),
    }


def score_length(word_count, low, high):
    """篇幅契合度。区间内满分，区间外 30% 内给 8 分。"""
    if low is None and high is None:
        return W_LENGTH
    if word_count is None:
        return 0
    in_band = True
    if low is not None and word_count < low:
        in_band = False
    if high is not None and word_count > high:
        in_band = False
    if in_band:
        return W_LENGTH

    lo_bound = low * 0.7 if low is not None else None
    hi_bound = high * 1.3 if high is not None else None
    if lo_bound is not None and word_count < lo_bound:
        return 0
    if hi_bound is not None and word_count > hi_bound:
        return 0
    return 8


def score_genre(item, profile):
    """题材契合度。提供标签总数时按命中比例折算，全命中即满分。

    主类型未命中时不给基础分，且总分封顶 20——说明这本书只是"相关"，不是"本类型"。
    """
    main_hit = item["main_genre_match"]
    base = 10 if main_hit else 0
    hits = item["sub_tag_hits"]
    denom = item.get("tag_denominator") or profile.get("tag_denominator")
    if denom:
        ratio = min(hits / denom, 1.0)
        genre = base + (W_GENRE - base) * ratio
    else:
        genre = base + hits * 4
    genre = max(0.0, min(genre, W_GENRE))
    if not main_hit:
        genre = min(genre, 20.0)
    return round(genre, 1)


def score_candidate(item, profile):
    """返回 (明细字典, 归一化总分)。"""
    genre = score_genre(item, profile)

    has_ref = profile["has_reference_work"]
    similarity = 0.0
    if has_ref:
        similarity = item.get("similarity") or 0.0

    length = score_length(
        item["word_count"],
        profile["target_word_min"],
        profile["target_word_max"],
    )
    platform = PLATFORM_SCORE[item["platform_match"]]
    update = UPDATE_SCORE[item["update_match"]]
    reputation = REPUTATION_SCORE[item["reputation"]]

    raw = genre + similarity + length + platform + update + reputation
    full = W_GENRE + W_LENGTH + W_PLATFORM + W_UPDATE + W_REPUTATION
    if has_ref:
        full += W_SIMILARITY
    score = round(raw / full * 100, 1) if full else 0.0

    detail = {
        "genre": genre,
        "similarity": round(similarity, 1),
        "length": length,
        "platform": platform,
        "update": update,
        "reputation": reputation,
    }
    return detail, score


def rank(candidates, profile):
    """打分并按总分降序排序。同分依次比较题材分、篇幅分、书名，保证结果可复现。"""
    results = []
    for item in candidates:
        detail, score = score_candidate(item, profile)
        results.append({"item": item, "detail": detail, "score": score})
    results.sort(
        key=lambda r: (
            r["score"],
            r["detail"]["genre"],
            r["detail"]["length"],
            r["item"]["title"],
        ),
        reverse=True,
    )
    return results


def _norm_name(name):
    """书名归一化：去空白、转小写，用于识别同名与不同译名。"""
    return "".join(str(name).split()).lower()


def dedupe_by_alias(results):
    """同一本书换了名字重复出现时，只保留分数更高的一条。

    results 已按分数降序，所以先出现的即高分版本。
    """
    seen = {}
    kept, dup = [], []
    for r in results:
        names = [_norm_name(r["item"]["title"])]
        names += [_norm_name(a) for a in r["item"].get("aliases") or []]
        names = [n for n in names if n]
        if any(n in seen for n in names):
            r["dup_of"] = next(seen[n] for n in names if n in seen)
            dup.append(r)
        else:
            kept.append(r)
            for n in names:
                seen[n] = r["item"]["title"]
    return kept, dup


def diversify(results, cap):
    """主题分散：同一地理/时代背景最多保留 cap 本。

    被挤出的候选不丢弃，返回给调用方单列，方便用户需要时替换回来。
    """
    if not cap:
        return results, []
    counter = {}
    kept, held = [], []
    for r in results:
        region = r["item"].get("region") or ""
        if not region:
            kept.append(r)
            continue
        used = counter.get(region, 0)
        if used < cap:
            kept.append(r)
            counter[region] = used + 1
        else:
            held.append(r)
    return kept, held


def print_table(results, profile, dropped, dup_alias=None, held=None):
    dup_alias = dup_alias or []
    held = held or []
    print()
    head = profile.get("note")
    if head:
        print(f"偏好摘要：{head}")
    print(f"排序结果（共 {len(results)} 部，按匹配度降序）")
    if dropped:
        detail = "、".join(f"{STATUS_LABEL[k]} {v} 部" for k, v in dropped.items())
        print(f"已剔除：{detail}")
    if not profile["has_reference_work"]:
        print("说明：未提供参考作品，相似度维度不计分，总分按 80 分制归一化到 100")
    print()

    has_ref = profile["has_reference_work"]
    cols = [
        ("#", 3),
        ("书名", 22),
        ("匹配度", 8),
        ("题材", 6),
        ("相似", 6),
        ("篇幅", 6),
        ("平台", 6),
        ("更新", 6),
        ("口碑", 6),
        ("可信度", 10),
    ]
    print(" ".join(_pad(name, w) for name, w in cols))
    print("-" * (sum(w for _, w in cols) + len(cols) - 1))

    for idx, r in enumerate(results, 1):
        item = r["item"]
        d = r["detail"]
        sim_cell = d["similarity"] if has_ref else "—"
        row = [
            _pad(idx, 3),
            _pad(_truncate(item["title"], 22), 22),
            _pad(r["score"], 8),
            _pad(d["genre"], 6),
            _pad(sim_cell, 6),
            _pad(d["length"], 6),
            _pad(d["platform"], 6),
            _pad(d["update"], 6),
            _pad(d["reputation"], 6),
            _pad(CREDIBILITY_LABEL[item["credibility"]], 10),
        ]
        print(" ".join(row))

    print()
    print("-" * 40)

    no_word = [r for r in results if r["item"]["word_count"] is None]
    if no_word:
        print("字数缺失，无法判断篇幅契合，必须标「信息不全」：")
        for r in no_word:
            print(f"  - {r['item']['title']}")

    out_of_band = [
        r for r in results
        if r["item"]["word_count"] is not None and r["detail"]["length"] == 0
    ]
    if out_of_band:
        print("篇幅超出目标区间 30% 以上，按规则应已在硬过滤阶段剔除：")
        for r in out_of_band:
            print(f"  - {r['item']['title']}（{r['item']['word_count']} 万字）")

    pending = [r for r in results if r["item"]["credibility"] != "verified"]
    if pending:
        print("可信度未达已核实，输出时必须保留标注：")
        for r in pending:
            print(f"  - {r['item']['title']}：{CREDIBILITY_LABEL[r['item']['credibility']]}")

    if len(results) < 10:
        print(f"警告：仅 {len(results)} 部，低于 10 部下限。"
              f"按 SKILL.md 规则应回补检索，最多 2 轮；仍不足则在输出开头说明缺口与原因。")

    if dup_alias:
        print("同名或不同译名重复，已合并为分数更高的一条：")
        for r in dup_alias:
            print(f"  - {r['item']['title']}（与《{r['dup_of']}》为同一本）")

    if held:
        print(f"因主题重复暂缓（同一背景达 {profile.get('region_cap')} 本上限），"
              f"需要时可替换回主清单：")
        for r in held:
            region = r["item"].get("region") or "未标背景"
            print(f"  - {r['item']['title']}（{region}，{r['score']} 分）")


def main():
    _configure_stdout()
    parser = argparse.ArgumentParser(description="按匹配度对小说候选打分排序")
    parser.add_argument("candidates", help="候选作品 JSON 文件路径")
    parser.add_argument("--profile", required=True, help="偏好画像 JSON 文件路径")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON 而非表格")
    args = parser.parse_args()

    cand_path = Path(args.candidates)
    prof_path = Path(args.profile)
    for p in (cand_path, prof_path):
        if not p.exists():
            print(f"错误：文件不存在 — {p}")
            return 1

    try:
        cand_data = json.loads(cand_path.read_text(encoding="utf-8"))
        profile_raw = json.loads(prof_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"错误：JSON 解析失败 — {exc}")
        return 1

    if isinstance(cand_data, dict):
        raw_list = cand_data.get("candidates")
    elif isinstance(cand_data, list):
        raw_list = cand_data
    else:
        raw_list = None
    if not isinstance(raw_list, list) or not raw_list:
        print('错误：未找到候选作品。JSON 应为 {"candidates": [...]} 或直接为数组，且不能为空。')
        return 1

    try:
        profile = validate_profile(profile_raw)
    except InputError as exc:
        print(f"输入错误：{exc}")
        return 2

    cleaned = []
    errors = []
    for idx, raw in enumerate(raw_list):
        try:
            cleaned.append(validate_candidate(idx, raw))
        except InputError as exc:
            errors.append(str(exc))

    if errors:
        print(f"输入错误：共 {len(errors)} 处，未开始排序。")
        for err in errors:
            print(f"  - {err}")
        return 2

    kept = [c for c in cleaned if c["status"] == "active"]
    dropped = {
        key: sum(1 for c in cleaned if c["status"] == key)
        for key in STATUS_LABEL
    }
    dropped = {k: v for k, v in dropped.items() if v}
    if not kept:
        print("错误：剔除已读 / 已否决 / 已过滤的候选后，没有剩余作品可排序。")
        return 1

    results = rank(kept, profile)
    results, dup_alias = dedupe_by_alias(results)
    results, held = diversify(results, profile.get("region_cap"))

    if args.json:
        payload = {
            "profile_note": profile["note"],
            "has_reference_work": profile["has_reference_work"],
            "dropped": dropped,
            "merged_duplicates": [
                {"title": r["item"]["title"], "same_as": r["dup_of"]} for r in dup_alias
            ],
            "held_by_region": [
                {"title": r["item"]["title"], "region": r["item"].get("region"), "score": r["score"]}
                for r in held
            ],
            "count": len(results),
            "results": [
                {
                    "title": r["item"]["title"],
                    "author": r["item"].get("author"),
                    "region": r["item"].get("region"),
                    "score": r["score"],
                    "breakdown": r["detail"],
                    "credibility": CREDIBILITY_LABEL[r["item"]["credibility"]],
                    "note": r["item"].get("note"),
                }
                for r in results
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_table(results, profile, dropped, dup_alias, held)

    return 0


if __name__ == "__main__":
    sys.exit(main())
