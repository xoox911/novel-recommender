# 输出模板与脚本输入格式

## 一、推荐清单输出模板

开头三行总体说明，然后逐部列出。

```
按「<核心偏好摘要>」筛出 <N> 部，已排除 <雷点摘要>。按匹配度降序，分数由题材契合、篇幅、平台可及性、口碑加权得出。

### 1. 《书名》 · 匹配度 87
**作者**：XXX｜**篇幅**：约 210 万字（已完结）｜**标签**：无限流、群像、无CP、快节奏

**简介**：两句话讲清设定与核心冲突。

**为什么推荐给你**：你要的是"无限流但不谈恋爱"，这本全程无感情线，副本设计密度高，主角团五人各有独立线。

**阅读渠道**
- 平台：起点中文网
- 免费情况：部分免费（前 30 章免费，后续按章付费）
- 获取途径：需按章购买
- 链接：https://...

**信息可信度**：✅ 已核实（作品页已访问，书名、作者、付费状态一致）
```

## 二、字段填写要求

| 字段 | 禁止的写法 | 要求的写法 |
|---|---|---|
| 篇幅 | "很长" | "约 210 万字（已完结）" |
| 标签 | "好看、精彩" | "无限流、群像、无CP、快节奏" |
| 简介 | 复制官方宣传语 | 自述设定 + 核心冲突，2–3 句 |
| 为什么推荐 | "很符合你的口味" | 引用用户偏好原话并逐条对应 |
| 免费情况 | "应该免费" | 四种标准表述之一，不确定则标"待核实" |
| 链接 | 首页链接 | 具体作品页链接 |

## 三、多部作品的紧凑列表形式

作品超过 5 部时，先给一张速览表，再展开前 3 部的详情：

```
| # | 书名 | 作者 | 标签 | 平台 | 免费情况 | 匹配度 | 可信度 |
|---|------|------|------|------|----------|--------|--------|
| 1 | ... | ... | ... | 起点 | 部分免费 | 87 | 已核实 |
```

## 四、rank_novels.py 输入格式

### profile.json

```json
{
  "target_word_min": 150,
  "target_word_max": 300,
  "has_reference_work": true,
  "note": "西幻群像、无CP、拒绝系统流"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| target_word_min | number | 目标字数下限，单位万字。null 表示不限 |
| target_word_max | number | 目标字数上限，单位万字。null 表示不限 |
| has_reference_work | bool | 用户是否给了参考作品。false 时相似度不进分母，总分按 80 分制归一化到 100 |
| tag_denominator | int | 可选。画像里的细分标签总数，用于把命中数按比例折算成题材分。缺省时按"每命中 1 个加 4 分"计 |
| region_cap | int | 可选。同一地理/时代背景最多保留几本，默认 3。设 0 关闭主题分散；填 null 或不填则用默认值 3 |
| note | string | 偏好摘要，仅用于输出抬头，不参与计算。上限 1000 字符 |

**单位是「万字」，不是「字」。** 210 万字请填 `210` 而不是 `2100000`。填成后者脚本会直接报错——超过 5000 万的数值一律判定为单位填错并拒绝，不会静默扣满分篇幅分。

### candidates.json

```json
{
  "candidates": [
    {
      "title": "书名",
      "author": "作者",
      "main_genre_match": true,
      "sub_tag_hits": 3,
      "tag_denominator": 4,
      "similarity": 16,
      "word_count": 210,
      "platform_match": "primary",
      "update_match": "exact",
      "reputation": "strong_positive",
      "credibility": "verified",
      "status": "active",
      "region": "日本战国",
      "aliases": ["别译名"],
      "sources": ["https://www.qidian.com/book/xxxx/", "https://book.douban.com/subject/xxxx/"],
      "note": "补充说明"
    }
  ]
}
```

| 字段 | 类型 | 取值 | 说明 |
|---|---|---|---|
| title | string | — | 书名，必填。不可见控制字符（含 ANSI 转义）会被自动剥除，上限 200 字符 |
| main_genre_match | bool | true/false | 主类型是否命中，必填。**为 false 时题材分封顶 20**，哪怕子标签全中 |
| sub_tag_hits | int | ≥0 | 作品标签与画像细分标签的交集个数。给了 tag_denominator 时按 hits ÷ denominator 折算题材分 |
| tag_denominator | int | ≥1 | 可选。覆盖 profile 里的同名值，用于本条单独指定标签总数 |
| similarity | number | 0–20 | 与参考作品的相似度，has_reference_work 为 false 时忽略 |
| word_count | number \| null | 万字 | 总字数，**单位万字**。未知填 null，脚本会提示需标「信息不全」，且不参与篇幅硬过滤。超过 5000 视为单位填错，直接报错 |
| platform_match | string | primary / secondary / none | 渠道可及性，**大小写敏感**。填 none 的作品会被移出主榜、单列为延伸参考 |
| update_match | string | exact / acceptable / mismatch | 完结状态匹配度，**大小写敏感** |
| reputation | string | 见下表六档 | 舆论质量，**不是讨论热度** |
| credibility | string | verified / pending / incomplete / unknown | 对应四档标注，脚本仅原样带回 |
| status | string | active / read / rejected / excluded | 默认 active。脚本只对 active 排序，其余剔除并按类别报数量 |
| region | string | 如「日本战国」「二战德国」 | 地理或时代背景，用于主题分散。留空则不受分散约束 |
| aliases | string[] | 别名/异译名 | 用于同名合并，与 title 一并参与归一化判重。**支持链式**：A、B(别名A)、C(别名B) 会合并成一条 |
| sources | string[] | 来源页面链接 | **每部候选都应填**。检索时实际打开或看到的页面，多个来源全部列出。缺填时 `--check` 报警，输出时该作品按规则标「来源不明」 |
| already_read | bool | true/false | **旧字段，已废弃**。仅在没写 status 时生效（为 true 等价于 `status: "read"`）。与 status 同时出现且冲突时脚本报错，不会静默覆盖 |
| author / note | string | — | 可选。类型不对会报错，不会把 JSON 对象直接塞进输出。note 上限 1000 字符 |

**数值不能是 NaN / Infinity。** 这是非标准 JSON 字面量，脚本会拒绝并提示，不会让 `nan` 混进最终分数。

字段类型或枚举值写错时，脚本报错退出（退出码 2），一次性列出所有问题候选及具体字段，**不会静默按 0 分处理**。

`reputation` 六档取值（满分 15）：

| 取值 | 含义 | 分 |
|---|---|---|
| strong_positive | 多来源正面 + 讨论量大 | 15 |
| positive_quiet | 多来源正面 + 讨论少 | 11 |
| polarized_style | 两极分化，争议在口味 | 9 |
| polarized_flaw | 两极分化，争议在硬伤 | 5 |
| single_source | 单一来源 / 只有官方推荐语 | 4 |
| mostly_negative | 负面为主 | 2 |

`main_genre_match` 是必填项；`similarity` 在无参考作品时可省略或填 0；批量补录时直接往 `candidates` 数组追加即可。

`main_genre_match`、`sub_tag_hits`、`similarity`、`reputation` 由检索阶段人工判定后填入，**脚本不做语义判断**。

### 调用

```bash
# 逐批补录时先校验，不排序
python "<skill_dir>/scripts/rank_novels.py" ./novel-candidates.json --profile ./novel-profile.json --check

# 出表格
python "<skill_dir>/scripts/rank_novels.py" ./novel-candidates.json --profile ./novel-profile.json

# 出结构化 JSON
python "<skill_dir>/scripts/rank_novels.py" ./novel-candidates.json --profile ./novel-profile.json --json
```

`<skill_dir>` 替换为 skill 实际所在目录。JSON 写到当前工作目录即可，不要依赖脚本的 cwd。

- `--check` — 只校验字段不排序。候选是分批补录的，填到第 20 部才发现第 7 部写错会整体重来，逐批验证更省事
- `--json` — 输出结构化结果，便于后续加工
- 不带参数 — 输出可读表格

### 脚本会自己做的三件事

不需要手工标记，也**不要**手动把这些候选删掉：

| 行为 | 触发条件 | 输出字段 |
|---|---|---|
| 篇幅硬过滤 | `word_count` 已知且超出目标区间上下 30% | `auto_filtered_out_of_band` |
| 可及性硬过滤 | `platform_match: "none"` | `inaccessible` |
| 同名合并 | title / aliases 归一化后重复 | `merged_duplicates` |

被剔除的作品都单列报回，不静默丢弃，需要时可以直接替换回主清单。

**处理顺序固定**：status 剔除 → 打分排序 → 篇幅过滤 → 同名合并 → 可及性拆分 → 主题分散。同名合并排在可及性拆分之前，所以同一本书不会在主榜和延伸参考里各出现一次。

`--json` 的完整字段：`profile_note`、`has_reference_work`、`dropped`、`auto_filtered_out_of_band`、`inaccessible`、`merged_duplicates`、`held_by_region`、`warnings`、`count`、`results`。其中 `results`、`inaccessible`、`held_by_region` 三处的每一条都带完整 `breakdown` 和 `sources`，字段结构一致，可以直接拼在一起做下游加工。

### 输出示例

```
排序结果（共 6 部，按匹配度降序）
说明：未提供参考作品，相似度维度不计分，总分按 80 分制归一化到 100

#  书名          匹配度  题材   相似  篇幅  平台  更新  口碑  可信度
1  ...            87.5     30     —     15    15    5     9     已核实
```
