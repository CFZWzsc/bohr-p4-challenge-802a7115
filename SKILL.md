---
name: cross-lingual-literature-search
description: Use when a research search must cover several languages and only a supplied glossary is available, and needs per-language query construction with untranslated terms listed, script-aware language detection with ambiguity flags, quoted match evidence, declared translation-version grouping, and per-language coverage gaps in a contract-preserving result.json.
---

# 跨语言文献检索与术语扩展

## 用途与适用条件

当同一研究问题的相关文献分散在英文、中文、日文、德文、俄文等多种语言库中，需要构造各语言检索式、识别记录语种、归并译文版本并说明语种覆盖缺口时使用。

**适用前提**：输入真实提供查询主题、目标语种与**术语对照表**（glossary），以及多语种候选记录。没有对照表时仍可运行，但只会用原语言查询，并把"未翻译"显式列出——**不使用机器翻译，不臆造译名**。

**不适用**：在线翻译、代理访问受限数据库、跨脚本标题语义比对、替代人工双语审校。

## 输入

| 输入 | 说明 |
|---|---|
| `/input/case.json` | 必读。常见结构：`query`、`target_languages`（代码或语言名）、`glossary`（`[{"term","translations":{"zh":["..."],"ja":[...]}}]` 或 `{term: {lang: [...]}}`）、`records`/`results`（含 `title`、`abstract`、`language`、`doi`、可选 `translation_of`/`group_id`）。实际键名以文件为准。 |
| `task.md` | 可选，存在时读取用于核对目标语种与术语范围。 |
| `--work` | 工作目录，默认 `/app/work`。 |

## 处理流程（对应评分维度）

1. **术语与查询构造**（任务完成度）：抽取查询中的术语，只在 glossary 中查对应译文；逐目标语种生成查询式，记录哪些术语已翻译、哪些因缺译文保留原样；状态标为 `translated`/`partial`/`original_only`。
2. **语种识别**（结果正确性）：优先采用声明的 `language` 字段；缺失时按文字脚本判断（Hangul→ko、Kana→ja、Han→zh 但标歧义、Cyrillic/Arabic/Greek/Devanagari/Thai 各自标注共享脚本风险），拉丁字母则用停用词投票；无法判定标 `und`。
3. **匹配与排序**（正确性/可核验性）：在标题/摘要中做术语匹配（CJK 用子串、拉丁用词边界），标题命中权重高于摘要，语种一致仅在已有术语命中时加 1 分；每条命中保留术语、字段与**原句**。得分 0 的记录不进入结果。
4. **译文版本归并**（完整性）：仅依据共享 DOI 或声明的 `translation_of`/`group_id` 归组，不做跨脚本标题相似度比较；无法确认的版本保持独立。
5. **语种覆盖报告**（可核验性）：逐语种给出查询式、术语、记录数、命中数，并区分 `covered`、`no_matching_records`、`no_records_in_language`；后者说明是输入缺口而非文献不存在。
6. **不确定性登记**：未翻译术语、语言检测歧义、元数据口径不一致、无机器翻译，全部写入 `uncertainty`。

## 输出契约

写入 `--out`（默认 `/app/output/result.json`）。顶层字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 原样保留输入 `case_id` |
| `status` | string | `success` / `partial` / `insufficient_input` / `failed` |
| `result` | object | `query_original`、`queries`、`matches`（同时以 `results` 暴露）、`language_coverage`、`language_distribution`、`ambiguous_languages`、`version_groups`、`retrieval_strategy`、`limitations`、`change_log` |
| `matches` / `queries` | array | 顶层镜像：匹配记录（含证据）与逐语种查询式 |
| `evidence` | array | 术语表条目、匹配引文与来源定位 |
| `uncertainty` | array | 无对照表、未翻译、语种缺口、检测歧义、元数据差异 |
| `errors` | array | 运行错误；正常为空 |
| `stats` | object | 记录数、请求语种、有命中语种、匹配数、版本组 |
| `contract_notes` | object | 未产出契约字段说明 |
| `output_contract_fields` | object | `provided` 与 `present` |

输入 `output_contract` 的每个字段名都会出现在顶层；无法产出时写 `null` 并在 `contract_notes` 说明。

`status`：无记录且无查询 → `insufficient_input`；有记录但无对照表、或无记录 → `partial`；查询、对照表与记录齐备 → `success`；解析失败 → `failed`。

## 异常处理

| 情形 | 处理 | 输出标记 |
|---|---|---|
| 无 glossary | 只构造原语言查询，不翻译 | `status=partial`，`uncertainty.type=no_glossary` |
| 某术语缺目标语译文 | 保留原词并列出 | `queries[].untranslated_terms` |
| 目标语种无记录 | 报告输入缺口 | `language_coverage[].status=no_records_in_language` |
| Han 文种无法区分中/日 | 标 zh 但 `ambiguous=true` 并说明 | `ambiguous_languages` |
| Cyrillic 等多语共享脚本 | 标最可能语种并注明歧义 | `language_detection.note` |
| 记录缺 `language` 字段 | 脚本/停用词检测，失败标 `und` | `uncertainty.type=language_detection_ambiguity` |
| 译文版本无声明链接 | 不归并，保持独立 | `version_groups` 为空项 |
| 输出目录不可写 | stderr 简短错误，退出码 3 | 无静默成功 |

## 限制

- 不提供机器翻译；对照表未覆盖的术语无法跨语言检索，这是能力边界而非可忽略项。
- 脚本检测对共享文字（汉字、西里尔、阿拉伯字母）天然有歧义，只能标注，不能确证。
- 术语匹配不理解词形变化、同义词与否定，召回有限。
- 跨语言版本归并依赖声明链接或共享 DOI，缺少声明时无法识别译文对。
- 记录语言分布反映输入集合，不代表各语种真实文献量。

## Quickstart

在仓库根目录 `bohrium-competition` 执行（PowerShell，实测通过）：

```powershell
python -B "tracks\literature-search\challenges\challenge-802a7115\06_code\submission\scripts\run_skill.py" --case "tracks\literature-search\challenges\challenge-802a7115\06_code\submission\examples\demo-case\case.json" --out "$env:TEMP\demo_802a7115\result.json" --work "$env:TEMP\demo_802a7115\work"
```

- 示例输入：`examples/demo-case/case.json`，合成且自包含（`"demo": true`，1 条英文查询 + 中/英/德 3 条记录 + 小型术语表；DOI 均为虚构的 `10.0000/...`）。
- 实测输出：`status = "success"`、`matches = 9`，`result.json` 顶层含 `case_id`、`status`、`result`、`matches`、`queries`、`evidence`、`uncertainty`、`errors`、`stats`；同一输入两次运行结果逐字节一致。
- 该用例只验证脚本可执行与输出契约齐全，不代表真实跨语言检索效果。

## 最小调用示例（示例，非正式案例结果）

```bash
python /skills/weekly-skill/scripts/run_skill.py \
  --case /input/case.json --out /app/output/result.json --work /app/work
```

输入片段（示例）：

```json
{"case_id": "demo-007", "query": "NLRP3 inflammasome", "target_languages": ["en", "zh"],
 "glossary": [{"term": "NLRP3", "translations": {"en": ["NLRP3"], "zh": ["NLRP3"]}},
              {"term": "inflammasome", "translations": {"en": ["inflammasome"], "zh": ["炎症小体"]}}],
 "records": [{"title": "NLRP3炎症小体在脓毒症中的作用", "abstract": "NLRP3炎症小体激活。", "language": "zh", "doi": "10.1/z"}]}
```

示意输出（示例，已截断）：

```json
{"case_id": "demo-007", "status": "success",
 "queries": [{"language": "zh", "query": "NLRP3炎症小体", "status": "translated"}],
 "matches": [{"language": "zh", "score": 7, "matched_terms": ["NLRP3", "炎症小体"]}],
 "result": {"language_coverage": [{"language": "zh", "matches": 1, "status": "covered"}]}}
```

以上为接口示意，不代表任何官方固定案例结果。


## 交付保证与评分对齐

1. 在 Skill 安装目录执行：`cd /skills/weekly-skill && python scripts/run_skill.py --case /input/case.json --out /app/output/result.json --work /app/work`；路径不同时显式改 `--case` / `--out` / `--work`，不要假定相对路径可用。
2. 必须产出**完整成品** `result.json`：逐语种查询式、命中记录与原句证据、语种覆盖缺口全部落位；禁止 skeleton、`pending`、空占位或只写方法说明。
3. 脚本无法自动完成的实质判断（真实术语对照、语种归属争议）由调用 Agent 依据实际 glossary 与记录补全并写回 `result.json`，不得臆造译名。
4. 自检：`case_id` 与输入一致；`output_contract` 每个字段存在；`status` 取本契约值 `success` / `partial` / `insufficient_input` / `failed`（不得写 `completed`）；未翻译术语已列出。
5. 输入缺失、JSON 损坏或字段异常时仍写出结构化结果并说明缺口，不崩溃、不静默成功。

## 交付要求

1. **交付成品，不是流程说明**：脚本产出只是索引与核对骨架；调用 Agent 必须在同一 `result.json` 中补齐本题要求的检索结果、查询计划、纳排依据与证据；字段为空或含 `pending`、`TODO` 一律视为未完成。
2. **覆盖全部输入条目**：输入中的每条检索式、候选记录、问题与指标都要有对应条目；确实缺失的写入 `uncertainty` / `limitations` 并说明原因，不得静默跳过。
3. **自检后再交付**：`case_id` 与输入一致；`output_contract` 每个字段落位；状态取脚本实现的枚举（见上方契约表）；引文为原文短句并带来源定位；计数内部闭合、无自相矛盾。
4. **参数等价**：`--case <输入> --out <输出>` 与 `--output <输出>` 等价；默认 `/input/case.json` → `/app/output/result.json`。
5. **平台用 3 个固定案例分别运行**：逻辑由输入驱动，不针对示例硬编码；字段命名差异走别名匹配并在 `uncertainty` 记录假设。

## 运行时产物（单次运行自动写出）

入口脚本在写 `result.json` 的同一次运行里还会写出：`report.md`（人读报告，每条带源定位）、
`provenance.json`（条目 → 来源定位映射）、`records.csv`（平面结果表）、
`validation.json`（自检项）。`output_contract` 中的产物类字段直接指向这些文件，
无需第二次运行或人工补写。
