#!/usr/bin/env python3
"""按匹配度对小说候选打分并排序。

用法:
    python rank_novels.py candidates.json --profile profile.json
    python rank_novels.py candidates.json --profile profile.json --json
    python rank_novels.py candidates.json --profile profile.json --check

脚本只做加权计算与排序，不做语义判断。
标签是否命中、口碑落在哪一档，需在检索阶段人工判定后写入 candidates.json。

退出码:
    0  正常
    1  文件不存在 / 读取失败 / JSON 解析失败 / 无有效候选
    2  输入字段校验失败（会列出全部错误位置）
"""

import argparse
import contextlib
import json
import math
import sys
import unicodedata
from pathlib import Path

# ---- 权重（与 SKILL.md 阶段五表格一一对应，改这里必须同步改文档）----
W_GENRE = 30
W_SIMILARITY = 20
W_LENGTH = 15
W_PLATFORM = 15
W_UPDATE = 5
W_REPUTATION = 15

# 题材分的内部刻度
GENRE_BASE_ON_MAIN_HIT = 10.0  # 主类型命中给的基础分
GENRE_CAP_NO_MAIN = 20.0  # 主类型未命中时题材分上限（只是"相关"，不是"同类"）
GENRE_PER_HIT_NO_DENOM = 4.0  # 没给标签总数时，每命中一个加几分

# 篇幅分的区间浮动
LENGTH_PARTIAL_SCORE = 8  # 落在目标区间外 30% 以内给的分
LENGTH_BAND_LOW = 0.7  # 下限 × 0.7
LENGTH_BAND_HIGH = 1.3  # 上限 × 1.3

MIN_RECOMMEND_COUNT = 10  # 默认目标产出数；不同预算档位用 --target-count 覆盖
WORD_COUNT_MAX_PLAUSIBLE = 5000  # 万字。单本网文超过这个量级基本是单位填错
TEXT_MAX_LEN = 200  # 书名、作者、标签、背景等短字段上限，防脏数据
NOTE_MAX_LEN = 1000  # 备注与偏好摘要：用户原话容易被截断，单独放宽
URL_MAX_LEN = 500  # 来源链接可能带追踪参数

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

# 旧版字段名 -> (标准取值, 若需提示则给警告文案)
REPUTATION_ALIASES = {
    "multi_positive": (
        "strong_positive",
        "reputation=multi_positive 未确认讨论量，已按 strong_positive 计分，"
        "请复核是否真的有多篇独立长评",
    ),
    "mixed": (
        "polarized_style",
        "reputation=mixed 语义模糊，已按 polarized_style 计分，请复核争议属于口味分歧还是质量硬伤",
    ),
    "single": ("single_source", None),
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

# 剥掉 C0 控制字符（保留 \t 以便清洗后仍可读）与 DEL。
# 书名来自联网检索，属于不可信输入，ANSI 转义会篡改终端显示。
_CONTROL_CHARS = dict.fromkeys([c for c in range(0x20) if c != 0x09] + [0x7F])


class InputError(Exception):
    """单个字段的校验错误。"""


MIN_PYTHON = (3, 10)


def _configure_stdout():
    """Windows 控制台中文输出兼容。"""
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")


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
    if width <= 2:
        return "." * max(width, 0)
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
        raise InputError(f"{where}：{field} 应为数字，实际为 {value!r}（{type(value).__name__}）")
    if not math.isfinite(value):
        raise InputError(
            f"{where}：{field} 不是有限数值（{value!r}）。"
            f"JSON 标准不允许 NaN / Infinity，请改为具体数值或 null"
        )
    return float(value)


def _need_int(value, field, where, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"{where}：{field} 应为整数，实际为 {value!r}（{type(value).__name__}）")
    if minimum is not None and value < minimum:
        raise InputError(f"{where}：{field} 不能小于 {minimum}，实际为 {value}")
    return value


def _clean_text(value, field, where, allow_none=True, max_len=TEXT_MAX_LEN):
    """清理文本字段：剥控制字符、去首尾空白、限制长度。"""
    if value is None:
        if allow_none:
            return None
        raise InputError(f"{where}：缺少必填字段 {field}")
    if not isinstance(value, str):
        raise InputError(f"{where}：{field} 应为字符串，实际为 {value!r}（{type(value).__name__}）")
    text = value.translate(_CONTROL_CHARS).strip()
    if len(text) > max_len:
        raise InputError(f"{where}：{field} 长度 {len(text)} 超过 {max_len} 字符上限，请精简")
    return text


def _reject_constant(name):
    """json.loads 的 parse_constant 钩子，封死 NaN / Infinity / -Infinity。"""
    raise InputError(
        f"JSON 中出现非法字面量 {name}。JSON 标准只允许有限数值，"
        f"请改为具体数值，或对允许缺失的字段填 null"
    )


def _load_json(path, label):
    """读取 JSON 文件。所有失败都转成可读提示，不向上抛裸异常。"""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise InputError(
            f"{label}不是 UTF-8 编码（{path}）。"
            f"请另存为 UTF-8 后重试：记事本 → 另存为 → 编码选 UTF-8；"
            f"VS Code / WPS 同理在保存编码里切换。"
        ) from None
    except IsADirectoryError:
        raise InputError(f"{label}路径是目录而不是文件：{path}") from None
    except OSError as exc:
        raise InputError(f"{label}读取失败（{path}）：{exc.strerror or exc}") from None
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except InputError:
        raise
    except json.JSONDecodeError as exc:
        raise InputError(
            f"{label}JSON 解析失败（{path}）第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}"
        ) from None


def validate_profile(raw):
    """校验 profile，返回清洗后的字典。"""
    if not isinstance(raw, dict):
        raise InputError("profile.json 必须是 JSON 对象，不能是数组或其他类型")

    low = _need_number(raw.get("target_word_min"), "target_word_min", "profile", allow_none=True)
    high = _need_number(raw.get("target_word_max"), "target_word_max", "profile", allow_none=True)
    if low is not None and high is not None and low > high:
        raise InputError(f"profile：target_word_min（{low}）大于 target_word_max（{high}）")
    for name, val in (("target_word_min", low), ("target_word_max", high)):
        if val is not None and val > WORD_COUNT_MAX_PLAUSIBLE:
            raise InputError(
                f"profile：{name}={val} 万字不合常理（单本网文很少超过 "
                f"{WORD_COUNT_MAX_PLAUSIBLE} 万字）。单位是「万字」，210 万字请填 210"
            )

    has_ref = raw.get("has_reference_work", False)
    if not isinstance(has_ref, bool):
        raise InputError("profile：has_reference_work 必须是 true 或 false")

    denom = raw.get("tag_denominator")
    if denom is not None:
        denom = _need_int(denom, "tag_denominator", "profile", minimum=1)

    # region_cap 只接受 int 或 null；null 等同于不设置（回到默认值）
    region_cap = raw.get("region_cap", DEFAULT_REGION_CAP)
    if region_cap is None:
        region_cap = DEFAULT_REGION_CAP
    else:
        region_cap = _need_int(region_cap, "region_cap", "profile", minimum=0)

    return {
        "target_word_min": low,
        "target_word_max": high,
        "has_reference_work": has_ref,
        "tag_denominator": denom,
        "region_cap": region_cap,
        "note": _clean_text(raw.get("note"), "note", "profile", max_len=NOTE_MAX_LEN),
    }


def validate_candidate(idx, raw):
    """校验单条候选，返回 (清洗后的字典, 警告列表)。"""
    warnings = []
    where = f"第 {idx + 1} 部候选"
    if not isinstance(raw, dict):
        raise InputError(f"{where}：不是 JSON 对象")

    title = _clean_text(raw.get("title"), "title", where, allow_none=False)
    if not title:
        raise InputError(f"{where}：缺少有效 title")
    where = f"第 {idx + 1} 部{_quote_title(title)}"

    main = raw.get("main_genre_match")
    if not isinstance(main, bool):
        raise InputError(f"{where}：main_genre_match 应为 true/false，实际为 {main!r}")

    hits = _need_int(raw.get("sub_tag_hits"), "sub_tag_hits", where, minimum=0)

    word = _need_number(raw.get("word_count"), "word_count", where, allow_none=True)
    if word is not None and word <= 0:
        raise InputError(f"{where}：word_count 必须大于 0，实际为 {word}")
    if word is not None and word > WORD_COUNT_MAX_PLAUSIBLE:
        raise InputError(
            f"{where}：word_count={word} 万字不合常理（单本网文很少超过 "
            f"{WORD_COUNT_MAX_PLAUSIBLE} 万字），疑似把「字」当「万字」填了。"
            f"单位是万字，210 万字请填 210"
        )

    platform = raw.get("platform_match")
    if platform not in PLATFORM_SCORE:
        raise InputError(
            f"{where}：platform_match 取值非法 {platform!r}，只能是 {'/'.join(PLATFORM_SCORE)}"
        )

    update = raw.get("update_match")
    if update not in UPDATE_SCORE:
        raise InputError(
            f"{where}：update_match 取值非法 {update!r}，只能是 {'/'.join(UPDATE_SCORE)}"
        )

    reputation_raw = raw.get("reputation")
    if reputation_raw in REPUTATION_ALIASES:
        reputation, msg = REPUTATION_ALIASES[reputation_raw]
        if msg:
            warnings.append(f"{where}：{msg}")
    else:
        reputation = reputation_raw
    if reputation not in REPUTATION_SCORE:
        raise InputError(
            f"{where}：reputation 取值非法 {reputation_raw!r}，只能是 {'/'.join(REPUTATION_SCORE)}"
        )

    credibility = raw.get("credibility", "unknown")
    if credibility not in CREDIBILITY_LABEL:
        raise InputError(
            f"{where}：credibility 取值非法 {credibility!r}，只能是 {'/'.join(CREDIBILITY_LABEL)}"
        )

    similarity = raw.get("similarity")
    if similarity is not None:
        similarity = _need_number(similarity, "similarity", where)
        if similarity < 0 or similarity > W_SIMILARITY:
            raise InputError(f"{where}：similarity 应在 0–{W_SIMILARITY} 之间，实际为 {similarity}")

    denom = raw.get("tag_denominator")
    if denom is not None:
        denom = _need_int(denom, "tag_denominator", where, minimum=1)

    already_read = raw.get("already_read", False)
    if not isinstance(already_read, bool):
        raise InputError(f"{where}：already_read 应为 true/false")

    status_raw = raw.get("status")
    if status_raw is None:
        # 兼容旧字段：没有 status 时才用 already_read 兜底
        status = "read" if already_read else "active"
    else:
        if not isinstance(status_raw, str) or status_raw not in STATUS_VALUES:
            raise InputError(
                f"{where}：status 取值非法 {status_raw!r}，只能是 {'/'.join(STATUS_VALUES)}"
            )
        status = status_raw
        if already_read and status != "read":
            raise InputError(
                f"{where}：already_read 为 true 但 status 是 {status!r}，两者冲突。"
                f"already_read 是旧字段，请删除它只保留 status"
            )

    region = _clean_text(raw.get("region"), "region", where)

    aliases = raw.get("aliases") or []
    if not isinstance(aliases, list):
        raise InputError(f"{where}：aliases 应为字符串数组")
    cleaned_aliases = []
    for i, a in enumerate(aliases):
        text = _clean_text(a, f"aliases[{i}]", where)
        if text:
            cleaned_aliases.append(text)

    sources = raw.get("sources") or []
    if not isinstance(sources, list):
        raise InputError(f"{where}：sources 应为字符串数组，每项是一个来源页面链接")
    cleaned_sources = []
    for i, s in enumerate(sources):
        text = _clean_text(s, f"sources[{i}]", where, max_len=URL_MAX_LEN)
        if text:
            cleaned_sources.append(text)

    return {
        "title": title,
        "aliases": cleaned_aliases,
        "sources": cleaned_sources,
        "author": _clean_text(raw.get("author"), "author", where),
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
        "region": region or "",
        "note": _clean_text(raw.get("note"), "note", where, max_len=NOTE_MAX_LEN),
    }, warnings


def score_length(word_count, low, high):
    """篇幅契合度。区间内满分，区间外 30% 内给部分分。"""
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

    lo_bound = low * LENGTH_BAND_LOW if low is not None else None
    hi_bound = high * LENGTH_BAND_HIGH if high is not None else None
    if lo_bound is not None and word_count < lo_bound:
        return 0
    if hi_bound is not None and word_count > hi_bound:
        return 0
    return LENGTH_PARTIAL_SCORE


def score_genre(item, profile):
    """题材契合度。提供标签总数时按命中比例折算，全命中即满分。

    主类型未命中时不给基础分，且总分封顶 GENRE_CAP_NO_MAIN——说明这本书
    只是"相关"，不是"本类型"。这条封顶规则同步写在 SKILL.md 阶段五。
    """
    main_hit = item["main_genre_match"]
    base = GENRE_BASE_ON_MAIN_HIT if main_hit else 0.0
    hits = item["sub_tag_hits"]
    denom = item.get("tag_denominator") or profile.get("tag_denominator")
    if denom:
        ratio = min(hits / denom, 1.0)
        genre = base + (W_GENRE - base) * ratio
    else:
        genre = base + hits * GENRE_PER_HIT_NO_DENOM
    genre = max(0.0, min(genre, float(W_GENRE)))
    if not main_hit:
        genre = min(genre, GENRE_CAP_NO_MAIN)
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
        # 延伸参考里的作品 platform_match 为 none，总分会被扣掉 15 分。
        # 展示时用不含平台分的分数，避免用户把"读不到"误读成"质量差"。
        "score_without_platform": round((raw - platform) / full * 100, 1) if full else 0.0,
    }
    return detail, score


def rank(candidates, profile):
    """打分并按总分降序排序。同分依次比较题材分、篇幅分、书名，保证结果可复现。

    注意：数值维度取负而不是用 reverse=True，否则书名的字符串比较方向
    也会被反转，同分作品变成按书名倒序。
    """
    results = []
    for item in candidates:
        detail, score = score_candidate(item, profile)
        results.append({"item": item, "detail": detail, "score": score})
    results.sort(
        key=lambda r: (
            -r["score"],
            -r["detail"]["genre"],
            -r["detail"]["length"],
            r["item"]["title"],
        )
    )
    return results


_NAME_WRAPPERS = "《》〈〉「」『』“”‘’\"'()（）[]【】<>"


def _norm_name(name):
    """书名归一化：去空白、转小写、剥掉书名号等包裹符号。

    中文书名几乎总带《》，而别名常写成裸名。不剥掉包裹符号的话
    《巨企、殖民地与星舰》和「我是太空垃圾佬」这类别名永远匹配不上。
    """
    text = "".join(str(name).split()).lower()
    stripped = text.strip(_NAME_WRAPPERS)
    return stripped or text


def _quote_title(title):
    """书名已有书名号就不再重复包裹。"""
    return title if title[:1] in "《〈「『" else f"《{title}》"


def _norm_region(region):
    """背景归一化，用于主题分散计数。

    直接拿原始字符串当 key 时，"日本 战国" 与 "日本战国" 会被算成两个
    不同背景，同一背景的作品就能绕开 region_cap 一起进榜。这里统一做
    全半角折叠与空白剔除，展示用的原文仍保留。
    """
    text = unicodedata.normalize("NFKC", str(region))
    return "".join(text.split()).lower()


def dedupe_by_alias(results):
    """同一本书换了名字重复出现时，只保留分数更高的一条。

    results 已按分数降序，所以先出现的即高分版本。
    别名支持链式传递：A、B(别名A)、C(别名B) 三者会合并成一条，
    判重的候选也会把自己的别名登记到保留项上，否则链会断。
    """
    seen = {}  # 归一化名 -> 最终保留的 title
    kept, dup = [], []
    for r in results:
        names = [_norm_name(r["item"]["title"])]
        names += [_norm_name(a) for a in r["item"].get("aliases") or []]
        names = list(dict.fromkeys(n for n in names if n))
        hit = next((seen[n] for n in names if n in seen), None)
        if hit is not None:
            r["dup_of"] = hit
            dup.append(r)
            for n in names:
                seen.setdefault(n, hit)
        else:
            kept.append(r)
            for n in names:
                seen[n] = r["item"]["title"]
    return kept, dup


def split_inaccessible(results):
    """可及性硬过滤：完全读不到的移出主榜，单列为延伸参考。"""
    kept, blocked = [], []
    for r in results:
        if r["item"]["platform_match"] == "none":
            blocked.append(r)
        else:
            kept.append(r)
    return kept, blocked


def filter_out_of_band(results):
    """篇幅硬过滤：字数已知且已超出目标区间 30% 以上的剔除。

    字数未知的候选不参与本道筛——按 SKILL.md 规则保留并标「信息不全」，
    由打分环节扣篇幅分。
    """
    kept, dropped = [], []
    for r in results:
        item = r["item"]
        if item["word_count"] is not None and r["detail"]["length"] == 0:
            dropped.append(r)
        else:
            kept.append(r)
    return kept, dropped


def diversify(results, cap):
    """主题分散：同一地理/时代背景最多保留 cap 本。

    被挤出的候选不丢弃，返回给调用方单列，方便用户需要时替换回来。
    背景按 _norm_region 归一化后计数，避免写法差异绕过上限。
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
        key = _norm_region(region)
        used = counter.get(key, 0)
        if used < cap:
            kept.append(r)
            counter[key] = used + 1
        else:
            held.append(r)
    return kept, held


def print_table(
    results,
    profile,
    dropped,
    dup_alias=None,
    held=None,
    inaccessible=None,
    auto_dropped=None,
    warnings=None,
    target_count=MIN_RECOMMEND_COUNT,
):
    dup_alias = dup_alias or []
    held = held or []
    inaccessible = inaccessible or []
    auto_dropped = auto_dropped or []
    warnings = warnings or []

    print()
    head = profile.get("note")
    if head:
        print(f"偏好摘要：{head}")
    print(f"排序结果（共 {len(results)} 部，按匹配度降序）")
    # 人工标记的剔除与脚本自动剔除分开报数：混成一个数字会让执行者
    # 分不清是自己标错了 status，还是字数确实越界。
    parts = [f"{STATUS_LABEL[k]} {v} 部" for k, v in dict(dropped).items()]
    if auto_dropped:
        parts.append(f"篇幅越界自动剔除 {len(auto_dropped)} 部")
    if parts:
        print("已剔除：" + "、".join(parts))
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

    if auto_dropped:
        print("篇幅超出目标区间 30% 以上，已按硬过滤规则自动剔除（如需保留请放宽区间）：")
        for r in auto_dropped:
            print(f"  - {r['item']['title']}（{r['item']['word_count']} 万字）")

    if inaccessible:
        print("当前可用平台无法阅读，已移出主清单，作延伸参考不计入推荐数量：")
        for r in inaccessible:
            print(
                f"  - {r['item']['title']}"
                f"（{r['detail']['score_without_platform']} 分，未计平台可及性；"
                f"需换平台或仅实体/已下架）"
            )

    pending = [r for r in results if r["item"]["credibility"] != "verified"]
    if pending:
        print("可信度未达已核实，输出时必须保留标注：")
        for r in pending:
            print(f"  - {r['item']['title']}：{CREDIBILITY_LABEL[r['item']['credibility']]}")

    if len(results) < target_count:
        print(
            f"警告：仅 {len(results)} 部，低于本轮目标 {target_count} 部。"
            f"按 SKILL.md 规则应回补检索，最多 2 轮；仍不足则在输出开头说明缺口与原因。"
        )

    if dup_alias:
        print("同名或不同译名重复，已合并为分数更高的一条：")
        for r in dup_alias:
            print(f"  - {r['item']['title']}（与{_quote_title(r['dup_of'])}为同一本）")

    if held:
        print(
            f"因主题重复暂缓（同一背景达 {profile.get('region_cap')} 本上限），"
            f"需要时可替换回主清单："
        )
        for r in held:
            region = r["item"].get("region") or "未标背景"
            print(f"  - {r['item']['title']}（{region}，{r['score']} 分）")

    if warnings:
        print("字段提示（不阻断，但建议复核）：")
        for w in warnings:
            print(f"  - {w}")


def _result_payload(r):
    return {
        "title": r["item"]["title"],
        "author": r["item"].get("author"),
        "region": r["item"].get("region"),
        "score": r["score"],
        "breakdown": r["detail"],
        "credibility": CREDIBILITY_LABEL[r["item"]["credibility"]],
        "sources": r["item"].get("sources") or [],
        "note": r["item"].get("note"),
    }


def main():
    if sys.version_info < MIN_PYTHON:
        print(
            f"错误：需要 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 或更高版本，"
            f"当前是 {sys.version.split()[0]}（{sys.executable}）"
        )
        return 1
    _configure_stdout()
    parser = argparse.ArgumentParser(description="按匹配度对小说候选打分排序")
    parser.add_argument("candidates", help="候选作品 JSON 文件路径")
    parser.add_argument("--profile", required=True, help="偏好画像 JSON 文件路径")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON 而非表格")
    parser.add_argument("--check", action="store_true", help="只校验输入不排序，便于边填边验")
    parser.add_argument(
        "--target-count",
        type=int,
        default=MIN_RECOMMEND_COUNT,
        help=f"本轮目标产出数，低于该值时提示回补检索。默认 {MIN_RECOMMEND_COUNT}",
    )
    args = parser.parse_args()
    if args.target_count < 1:
        print(f"错误：--target-count 必须是正整数，实际为 {args.target_count}")
        return 2

    cand_path = Path(args.candidates)
    prof_path = Path(args.profile)
    for p in (cand_path, prof_path):
        if not p.exists():
            print(f"错误：文件不存在 — {p}")
            return 1

    try:
        cand_data = _load_json(cand_path, "候选文件")
        profile_raw = _load_json(prof_path, "画像文件")
    except InputError as exc:
        print(f"错误：{exc}")
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
    warnings = []
    for idx, raw in enumerate(raw_list):
        try:
            item, item_warnings = validate_candidate(idx, raw)
            cleaned.append(item)
            warnings.extend(item_warnings)
        except InputError as exc:
            errors.append(str(exc))

    if errors:
        print(f"输入错误：共 {len(errors)} 处，未开始排序。")
        for err in errors:
            print(f"  - {err}")
        return 2

    # 字段间的漏填与自相矛盾：不阻断，但必须让执行者看见。
    # 这三类都是"填错了也能算出一个分"的情形，静默放行会让排序失去意义。
    if profile["has_reference_work"]:
        missing_sim = [c for c in cleaned if c["similarity"] is None]
        if missing_sim:
            names = "、".join(_quote_title(c["title"]) for c in missing_sim)
            warnings.append(
                f"{len(missing_sim)} 部候选未填 similarity（{names}）："
                f"has_reference_work 为 true 时该维度按 0 分计（满分 {W_SIMILARITY}），"
                f"请补填或改画像为 has_reference_work: false"
            )

    no_sources = [c for c in cleaned if c["status"] == "active" and not c["sources"]]
    if no_sources:
        names = "、".join(_quote_title(c["title"]) for c in no_sources)
        warnings.append(
            f"{len(no_sources)} 部候选未填 sources（{names}）："
            f"无法追溯来源页面，按规则应标「来源不明」"
        )

    for c in cleaned:
        denom = c["tag_denominator"] or profile["tag_denominator"]
        if denom and c["sub_tag_hits"] > denom:
            warnings.append(
                f"{_quote_title(c['title'])}：sub_tag_hits={c['sub_tag_hits']} 大于标签总数 "
                f"{denom}，命中比例已按上限截断，请复核标签是否数错"
            )

    if args.check:
        print(f"校验通过：{len(cleaned)} 部候选，画像无异常。")
        if warnings:
            print("字段提示（不阻断，但建议复核）：")
            for w in warnings:
                print(f"  - {w}")
        return 0

    kept = [c for c in cleaned if c["status"] == "active"]
    dropped = {key: sum(1 for c in cleaned if c["status"] == key) for key in STATUS_LABEL}
    dropped = {k: v for k, v in dropped.items() if v}
    if not kept:
        print("错误：剔除已读 / 已否决 / 已过滤的候选后，没有剩余作品可排序。")
        return 1

    results = rank(kept, profile)
    results, auto_dropped = filter_out_of_band(results)
    # 判重必须在拆分可及性之前：否则同一本书换个写法分别落在主榜和
    # 延伸参考里，用户会以为名单漏了书，也会看到重复的两条。
    results, dup_alias = dedupe_by_alias(results)
    results, inaccessible = split_inaccessible(results)
    if not results:
        print(
            "错误：篇幅过滤与可及性过滤后没有剩余作品。"
            "请放宽字数区间，或确认候选是否全部需要切换平台/已下架。"
        )
        return 1
    results, held = diversify(results, profile.get("region_cap"))

    if args.json:
        payload = {
            "profile_note": profile["note"],
            "has_reference_work": profile["has_reference_work"],
            "dropped": dropped,
            "auto_filtered_out_of_band": [
                {"title": r["item"]["title"], "word_count": r["item"]["word_count"]}
                for r in auto_dropped
            ],
            "inaccessible": [_result_payload(r) for r in inaccessible],
            "merged_duplicates": [
                {"title": r["item"]["title"], "same_as": r["dup_of"]} for r in dup_alias
            ],
            "held_by_region": [_result_payload(r) for r in held],
            "warnings": warnings,
            "count": len(results),
            "results": [_result_payload(r) for r in results],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_table(
            results,
            profile,
            dropped,
            dup_alias,
            held,
            inaccessible,
            auto_dropped,
            warnings,
            target_count=args.target_count,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
