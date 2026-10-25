# novel-recommender

[![CI](https://github.com/xoox911/novel-recommender/actions/workflows/tests.yml/badge.svg)](https://github.com/xoox911/novel-recommender/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

为 AI Agent 提供中文网络小说推荐能力：分轮采集阅读偏好，在四个主流平台定向检索，由脚本按固定权重排序，并对每条信息标注可信度。

适用于 WorkBuddy、Claude Code、Codex。由提示词文档与一个纯标准库脚本组成，不需要安装任何第三方包。

---

## 项目定位

通用助手回答「推荐几本小说」时，通常给出的是热榜复述：书名高度重复、阅读渠道不明、好评与营销通稿混在一起、用户明确说过的雷点照样出现。这个技能包针对的正是这四个具体失效点。

它的做法是把「找书」拆成可检查的步骤：先确认口味，再按平台定向检索，然后用规则淘汰，最后用脚本算分。整个过程留下两个 JSON 文件，随时可复核、可增量修正。

**适用**：书荒求新书；按某部作品找同类；查询某本书在哪些平台能看、是否免费、口碑如何。

**不适用**：外文作品与翻译小说；影视、动漫、漫画；需要人工精读的长篇书评；任何非正版获取渠道。

## 工作流程

六个阶段顺序执行，任一步跳过都会影响结论可靠性。

| 阶段 | 做什么 | 落地产物 |
|---|---|---|
| 1 偏好采集 | 分轮询问题材、结构偏好、篇幅、雷点、已读、平台与付费意愿 | 经用户确认的偏好描述 |
| 2 偏好画像 | 把偏好整理为结构化字段 | `novel-profile.json` |
| 3 定向检索 | 四个平台组合检索，收一条判一条（雷点 / 篇幅 / 可及性当场粗筛），只对通过的补元信息与查口碑 | `novel-candidates.json` |
| 4 硬过滤 | 依次淘汰已读、命中雷点、篇幅越界、无法阅读的作品 | 淘汰清单（分类计数） |
| 5 打分排序 | 六维加权，再做同名合并与主题分散 | 排序表 |
| 6 输出 | 按数量分两层：5 部内全展开，6 部以上给速览表 + 前 3 详情；逐部标注可信度 | 推荐清单 |

两处设计值得单独说明：

**结构偏好与题材同等重要。** 用户说「要玄幻」，真正在意的往往是「不要系统流」「不要后宫」。只记录题材大类必然踩雷，所以第一轮固定包含结构标签与雷点清单。

**检索必须带平台前缀。** 中文网文搜索结果被单一平台高度垄断，只搜题材词等于只搜了一个站。四个必检平台覆盖男频/女频 × 付费/免费四种组合，缺任一个就会有一整类作品检索不到。

## 核心特性

| 特性 | 具体表现 |
|---|---|
| 偏好采集 | 三轮递进：首轮 7 项必备（含平台与付费、已读），次轮条件触发，末轮深挖冷门标签；用户回答「随便」时有明确默认值 |
| 多源检索 | 起点、番茄、晋江、七猫四个平台组合检索，另补豆瓣、知乎等社区口碑；按预算分标准/精简/最小三档，每档标明目标产出、候选池下限与检索调用上限 |
| 硬过滤 | 已读去重、雷点排除、篇幅越界、渠道不可达四道；其中篇幅与可及性由脚本自动执行，人工只需标 `status` |
| 可复现排序 | 六维加权由脚本计算，同一输入必然同一输出；同分按题材分、篇幅分、书名依次决出 |
| 去重与分散 | 别名归一化合并同一本书的不同译名；同一地理或时代背景默认最多保留 3 部，被挤出的单独列出可替换 |
| 可信度标注 | 四档：已核实、待核实、信息不全、来源不明；标注是决策依据，不是免责声明 |
| 最小增量修正 | 用户不满意时按五类信号走五条路径，只改需要改的部分；修正上限 3 轮，第 4 轮转为诊断偏好本身 |

## 安装

### 目录放置

把 `novel-recommender` 整个目录放进宿主工具的 skills 路径：

| 工具 | macOS / Linux | Windows |
|---|---|---|
| WorkBuddy | `~/.workbuddy/skills/novel-recommender/` | `%USERPROFILE%\.workbuddy\skills\novel-recommender\` |
| Claude Code | `~/.claude/skills/novel-recommender/` | `%USERPROFILE%\.claude\skills\novel-recommender\` |
| Codex | `$CODEX_HOME/skills/novel-recommender/` | `%USERPROFILE%\.codex\skills\novel-recommender\` |

`CODEX_HOME` 未设置时默认 `~/.codex`。Windows 上 `~` 仅在 PowerShell 与 Git Bash 中有效，命令提示符与地址栏请用 `%USERPROFILE%`。

### 三种获取方式

```bash
# 1. 克隆
git clone https://github.com/xoox911/novel-recommender.git ~/.workbuddy/skills/novel-recommender
```

```text
# 2. 从 Releases 下载 novel-recommender.zip，解压得到 novel-recommender 目录
#    https://github.com/xoox911/novel-recommender/releases
```

第三种是交给 AI 自行安装：在支持技能的对话框里直接给出仓库地址，由它完成下载、放置与加载确认。前提是宿主具备文件读写与命令执行权限、当前会话可联网、且宿主支持 `SKILL.md` 规范。

### 验证

```bash
cd ~/.workbuddy/skills/novel-recommender && python -m unittest discover -s tests
```

末行显示 `OK` 即安装完整。随后核对 `SKILL.md` 的 `version` 字段与 Releases 最新版本号一致——这是判断「装的版本」是否最新的唯一依据。

报「找不到文件」说明目录层级放错，`SKILL.md` 应在目录第一层；报 `No module named unittest` 属于 Python 环境问题，与本项目无关。

### 更新与卸载

更新：用新版本目录覆盖旧目录即可，没有需要迁移的配置。卸载：删除该目录。项目不写入 skills 目录之外的任何位置。

## 快速上手

一次完整会话的样子：

```text
你：书荒了，帮我找本小说

AI：先确认几件事——最近想看什么类型？有什么特别想要或特别不要的设定结构？
    篇幅偏好？有什么绝对不能出现的？最近看过哪些（看过的不会再推）？

你：星际战争，不要感情线，不要系统流，100 万字以上，番茄能看的

AI：（复述并确认偏好）→ 检索四平台 → 按雷点淘汰 → 脚本打分
    （给出排序表与逐部说明，未核实的标「待核实」）
```

常见触发说法均有效：「推荐几本小说」「有没有类似《XXX》的」「这本书在哪个平台能看」「为什么有人说它烂尾」。

拿到结果后可以直接提修正要求，不必重述需求：

| 你的说法 | 技能的处理方式 |
|---|---|
| 只要免费的 / 要连载的 / 字数再长点 | 改画像对应字段，重跑过滤与打分 |
| 不想看贸易流了 | 改题材字段，回补检索并全量重排 |
| 第 3 本我看过 / 第 2 本不喜欢 | 标记该条状态，由候补补位；否决理由回灌画像 |
| 这几本都不对味 | 先诊断偏的是题材、平台还是风格，再决定回到哪一阶段 |
| 第 2 本结局是 HE 吗 | 直接回答，不动流程 |

## 配置参考

**项目没有全局配置文件。** 安装后无需任何设置。运行期的可调项全部位于两个 JSON 文件中，默认写在当前工作目录，名称如上。

### 偏好画像 `novel-profile.json`

| 字段 | 类型 | 说明 |
|---|---|---|
| `target_word_min` / `target_word_max` | number \| null | 目标篇幅区间，单位为**万字**。`null` 表示不限。200 万字填 `200` |
| `has_reference_work` | bool | 是否给了参考作品。为 `false` 时相似度维度不计入分母，总分按 80 分制归一化到 100 |
| `tag_denominator` | int | 画像中细分标签总数。用于把命中数折算成比例；缺省时按「每命中 1 个计 4 分」 |
| `region_cap` | int | 同一背景最多保留几部，默认 3。设 `0` 关闭主题分散，填 `null` 回到默认值 |
| `note` | string | 偏好摘要，仅用于输出抬头，上限 1000 字符 |

### 候选书单 `novel-candidates.json`

每部候选一条，外层为 `{"candidates": [...]}`，也可直接传数组。外层还可维护 `searches` 数组记录已跑过的检索（`query` / `platform` / `leads` / `round`），脚本只读 `candidates`，不读 `searches`；它的用途是让第二轮知道哪些词、哪些平台已经搜过，改题材时只补没覆盖的组合。

| 字段 | 类型 | 取值与要求 |
|---|---|---|
| `title` | string | 必填，上限 200 字符。控制字符与 ANSI 转义会被剥除 |
| `author` | string | 可选 |
| `main_genre_match` | bool | 必填。为 `false` 时题材分封顶 20 |
| `sub_tag_hits` | int | 必填。作品标签与画像标签的交集个数；大于分母时按上限截断并提示复核 |
| `tag_denominator` | int | 可选。单条覆盖画像中的同名值 |
| `similarity` | number | 0–20。`has_reference_work` 为 `false` 时忽略；为 `true` 时缺失会触发提示 |
| `word_count` | number \| null | 单位为**万字**。未知填 `null`；超过 5000 视为单位填错并拒绝 |
| `platform_match` | string | `primary` / `secondary` / `none`。`none` 会移出主榜，单列为延伸参考 |
| `update_match` | string | `exact` / `acceptable` / `mismatch` |
| `reputation` | string | 六档口碑取值，见下节 |
| `credibility` | string | `verified` / `pending` / `incomplete` / `unknown` |
| `status` | string | `active` / `read` / `rejected` / `excluded`。仅 `active` 参与排序 |
| `region` | string | 地理或时代背景，用于主题分散。留空则不受该规则约束 |
| `aliases` | string[] | 别名或异译名，参与同名合并，支持链式 |
| `sources` | string[] | 来源页面链接。缺填会触发提示，输出时按「来源不明」处理 |
| `note` | string | 可选，上限 1000 字符 |

`already_read` 为已废弃字段，仅在未写 `status` 时生效；两者同时出现且冲突时脚本报错而不猜测。

### 调整权重

权重常量位于 `scripts/rank_novels.py` 顶部：`W_GENRE`、`W_SIMILARITY`、`W_LENGTH`、`W_PLATFORM`、`W_REPUTATION`、`W_UPDATE`。改完必须同步 `SKILL.md` 的权重表与 `README.md` 上表——`tests/test_docs_consistency.py` 会比对两处文档的分值与脚本常量，漏改直接测试失败，不会静默漂移。

标注判定不在此列。「什么算两极分化」「什么情况标待核实」属于语义判断，由执行阶段完成，脚本只接收判定结果。把判定规则写进代码会让每次规则调整都变成发版。

## 打分模型

满分 100；无参考作品时按 80 分制归一化，两种情况的最终得分均为百分制、可直接比较。

| 维度 | 权重 | 计分方式 |
|---|---|---|
| 题材与标签契合 | 30 | 主类型命中记 10 分，其余 20 分按标签命中比例折算；主类型未命中时整项封顶 20 |
| 与参考作品相似度 | 20 | 仅在提供参考作品时启用，取输入值 |
| 篇幅契合 | 15 | 目标区间内满分；区间外 30% 以内记 8 分；超出记 0；字数未知记 0 |
| 平台可及性 | 15 | 主用平台可直达 15，需切换平台 8，完全不可达不计入主榜 |
| 舆论质量 | 15 | 六档取值，见下表 |
| 更新状态匹配 | 5 | 完全匹配 5，可接受 3，不匹配 0 |

口碑六档的判定重点不在讨论量，而在讨论内容：`strong_positive` 15、`positive_quiet` 11、`polarized_style` 9、`polarized_flaw` 5、`single_source` 4、`mostly_negative` 2。六档的判定条件以 `SKILL.md` 阶段五「舆论质量六档细则」为唯一口径，本文件不复述，避免两处分值不一致。

`polarized_style` 与 `polarized_flaw` 差 4 分，是本模型唯一的定性区分点：前者说明作品风格取向明确，合口味即可；后者说明作品本身存在缺陷。同一篇通稿被多站转载只计一个来源，不计入口碑。

### 调用方式

```bash
# 先校验字段，不排序
python "<skill_dir>/scripts/rank_novels.py" ./novel-candidates.json --profile ./novel-profile.json --check

# 输出表格（按本轮档位传目标产出：标准 10 / 精简 8 / 最小 5）
python "<skill_dir>/scripts/rank_novels.py" ./novel-candidates.json --profile ./novel-profile.json --target-count 8

# 输出结构化 JSON，便于下游加工
python "<skill_dir>/scripts/rank_novels.py" ./novel-candidates.json --profile ./novel-profile.json --json
```

`--target-count` 决定"数量不足"的判定线，不传按 10 计。三档目标产出分别是标准 10、精简 8、最小 5，档位与数字必须和 `SKILL.md` 的检索预算表一致。

`<skill_dir>` 为技能实际安装路径。**必须使用绝对路径**：执行者的当前目录通常是用户工作目录，写相对路径会找不到脚本。

退出码：`0` 正常；`1` 文件缺失、读取失败、JSON 解析失败或无有效候选；`2` 字段校验失败，此时会一次性列出全部问题位置，不进入排序。

脚本自行完成后处理，顺序固定为：状态剔除 → 打分排序 → 篇幅过滤 → 同名合并 → 可及性拆分 → 主题分散。被剔除的条目均单列报回，不静默丢弃。

## 输出约定

推荐清单分两层，按数量决定展开到哪一层：**5 部及以下**全部展开成详情卡；**6 部及以上**先给全量速览表，只把前 3 名展开成详情卡，其余保留表内一行。因主题重复暂缓的作品与被合并的异译重复各占一行，不展开。

详情卡必须包含：书名（含常见别名）、作者、简介（自述设定与核心冲突，不复述官方宣传语）、主要标签、匹配度与适配理由（引用用户原话）、舆论情况（讨论热度、评价倾向、主要争议点、争议性质）、可读平台、是否免费、获取途径、作品页链接、信息可信度。

**是否免费**只允许四种表述：官方免费；限时免费或会员免费；部分免费；付费。不得使用「应该免费」这类含糊说法。

**可信度**四档的触发条件：

| 标记 | 触发条件 |
|---|---|
| 已核实 | 作品页实际访问成功，书名、作者、付费状态三项与页面一致 |
| 待核实 | 信息来自搜索摘要或社区讨论，未直接访问作品页 |
| 信息不全 | 缺少作者、字数、完结状态中任意一项 |
| 来源不明 | 仅出现于单一非官方来源，无法交叉验证 |

## 使用边界

- **需要联网**。检索不可用时全量标注「待核实」并说明清单可能严重不完整，不会凭记忆补全。
- **仅覆盖四个必检平台**。掌阅、书旗、咪咕等未纳入常规检索，仅在查询特定作品时兜底。
- **结果不作缓存**。同一偏好两次询问可能给出不同的书，取决于当次检索到的内容。
- **数量不强行凑齐**。口味过窄时可能不足本轮目标产出（标准 10 / 精简 8 / 最小 5），此时说明缺口与原因，不掺入不合口味的作品。
- **舆论分档含主观成分**。六档由执行者判定，同一作品不同人可能落到相邻两档。
- **中文描述触发更稳**。以英文提问时触发率可能下降。

**合规**：仅提供正版阅读渠道，不检索、不提供、不暗示任何盗版站点、破解资源、网盘分享或 TXT 下载渠道，不绕过付费墙、验证码或访问控制。推荐结果中的书籍信息版权归原作者与平台所有。

**安全**：本技能不收集数据、不读取凭据、不写系统目录。可报告的问题类型与渠道见 [SECURITY.md](SECURITY.md)。

## 环境与兼容性

- Python 3.10 或更高；仅使用标准库，无需安装依赖
- 脚本对 Windows 控制台中文输出做了编码兼容，非 UTF-8 保存的 JSON 会给出可读提示而非抛出堆栈

| 宿主 | 状态 |
|---|---|
| WorkBuddy | 已实测 |
| Claude Code | 符合 `SKILL.md` 规范，未逐一实测 |
| Codex | 符合 `SKILL.md` 规范，未逐一实测 |

`SKILL.md` 的 frontmatter 含 `name`、`description`、`version`、`agent_created` 四个字段。`agent_created` 由 WorkBuddy 写入，其他宿主忽略即可，不影响加载。主流程与 `references/` 不依赖任何宿主专有特性。

## 开发

```bash
python -m unittest discover -s tests   # 回归测试（含文档一致性校验）
ruff check scripts tests               # 静态检查
ruff format --check scripts tests      # 格式检查
```

测试覆盖打分模型、字段校验、别名合并、主题分散、硬过滤与各类异常输入。`tests/test_docs_consistency.py` 单独校验文档与代码的口径：权重表、口碑六档分值、可信度四档取值、`status` 取值必须与 `scripts/rank_novels.py` 常量一致，改代码漏改文档会直接测试失败。CI 在 3.10–3.13 四个版本上运行上述三项检查。

改动落点、字段同步要求与发版流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。字段完整定义见 [references/output-template.md](references/output-template.md)，样例输入见 [examples/](examples/)。

## 许可证

[MIT](LICENSE) © 2026 xoox911
