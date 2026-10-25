# 参与开发

面向要改这个项目的人。只想用的话看 [README](README.md) 就够了。

## 环境

Python 3.10+，零第三方依赖——不用 `pip install` 任何东西，标准库够用。

## 跑测试

```bash
python -m unittest discover -s tests -v
```

42 个用例覆盖打分模型、字段校验、别名合并、主题分散、硬过滤、漏填字段提示和各类异常输入。改脚本前后都跑一遍。

Lint 用 ruff（可选，CI 会跑）：

```bash
ruff check scripts tests
ruff format --check scripts tests
```

## 改动该落在哪

这个项目有三层，改错地方容易白改：

| 要改什么 | 改哪里 |
|---|---|
| 打分算法、判重、排序、字段校验 | `scripts/rank_novels.py` |
| 判定规则（什么算口碑好、怎么识别营销号、平台怎么排） | `references/*.md` |
| 整体流程、阶段顺序、多轮修正协议 | `SKILL.md` |
| 脚本的输入输出格式 | `references/output-template.md` |

**规则别写进代码。** 什么算"两极分化"、什么情况标"待核实"，这些判断由 AI 在检索阶段做，脚本只接收判定好的结果。把规则硬编码进 Python，改一次要发一次版。

## 三处必须同步的地方

改打分权重的时候，这三处一起改，漏一处就自相矛盾：

1. `scripts/rank_novels.py` 顶部的 `W_GENRE` / `W_SIMILARITY` 等常量
2. `SKILL.md` 阶段五的权重表
3. `references/output-template.md` 的字段说明

同理，新增候选字段时：脚本的 `validate_candidate`、`output-template.md` 的字段表、`SKILL.md` 的相关段落，三处都要补，否则 AI 不知道该怎么填。

## 发版

**只 push commit 不会更新 Releases 面板**——那里只列打过 tag 的发行版。发版要做四步，缺一步都会出问题：

```bash
# 1. 改版本号（两处，见下）
# 2. 打 tag 并推送
git tag v1.0.2
git push origin v1.0.2
# 3. 打包 skill 目录成 zip
# 4. 建 release，并把 zip 作为附件传上去
gh release create v1.0.2 novel-recommender.zip --title "v1.0.2 <一句话说明>" --generate-notes
```

没有 gh CLI 就在网页点「Draft a new release」，选刚推的 tag，**在附件区手动拖入 zip**，再发布。

### 版本号要改两处

`pyproject.toml` 的 `version`，和 `SKILL.md` frontmatter 的 `version`。加上 git tag，一共三处必须一致——漏掉 SKILL.md 会出现「装的版本」和「skill 里写的版本」对不上，用户没法自查。

### 必须传 zip 附件

`--generate-notes` 不会自动生成附件，不传 zip 的话 README 里「从 Releases 下载 zip」就落空，用户只能拿 Source code（多一层 `novel-recommender-1.0.2/` 目录，解压后不能直接用）。

zip 里的顶层目录必须叫 `novel-recommender`，解压即可用。

Windows（PowerShell，在仓库根目录执行）：

```powershell
Compress-Archive -Path novel-recommender -DestinationPath novel-recommender.zip -Force
```

macOS / Linux：

```bash
zip -r novel-recommender.zip novel-recommender -x "novel-recommender/.git/*"
```

仓库根目录本身就叫 `novel-recommender`，所以在**它的上一级**执行才打包出正确结构。打完先解压验一遍：打开 zip 应先看到一个 `novel-recommender` 文件夹，点进去直接是 `SKILL.md`。

### 发完核对三件事

1. Releases 页面最新那条带 `novel-recommender.zip` 附件
2. 下载解压后 `SKILL.md` 在第一层，`version` 与 tag 一致
3. CI 在 tag 上也是绿的

### 一个踩过的坑


**别删已发布的 tag 去重打。** 删除远端 tag 的瞬间，关联的 Release 会掉成 draft，URL 变成 `untagged-<hash>`，`/releases/latest` 退回上一个版本。

补救办法是调 `PATCH /repos/{owner}/{repo}/releases/{id}`，body 带上 `{"tag_name": "v1.0.2", "draft": false, "make_latest": "true"}`。但能不踩就别踩——发布超过几分钟的 tag 就别动了，别人可能已经拉取。
