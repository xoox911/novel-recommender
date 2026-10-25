# 样例数据

两个文件对应 `rank_novels.py` 的 `--profile` 和候选书单参数，只为演示字段格式，**书是编的**，不要当真实推荐看。

```bash
python "<skill_dir>/scripts/rank_novels.py" examples/novel-candidates.json --profile examples/novel-profile.json
```

五个候选故意覆盖了四种情况，跑完能一次看到脚本的几个行为：

| 候选 | 会触发什么 |
|---|---|
| 帝国雄心 | 正常进主榜，字段填满 |
| 法兰西 1794 | 口碑两极为「硬伤」档、可信度「待核实」，输出时必须保留标注 |
| 日本战国走一遭 | 主用平台读不到，需要换平台，平台分减半 |
| 超长篇幅示例 | 480 万字，超出目标区间上限 30%，被硬过滤自动剔除 |
| 下架示例 | `platform_match: "none"`，移出主榜进延伸参考 |

末尾会出现「仅 3 部，低于 10 部下限」的警告——这是正常的，样例就五本书。真实使用时检索阶段至少要凑到 10 部。

每条候选都带 `sources`（这里填的是 example.com 占位链接，真实使用时换成实际来源页面）。**不填 `sources` 的候选，`--check` 会报警，输出时按规则标「来源不明」**，这是防止"书是编的"最重要的一道闸。

字段完整说明见 [../references/output-template.md](../references/output-template.md)。
