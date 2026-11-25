# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-802a7115` (track: `literature-search`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable pipeline and all supporting documents. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `cross-lingual-literature-search`
- Summary: Use when a research search must cover several languages and only a supplied glossary is available, and needs per-language query construction with untranslated terms listed, script-aware language detection with ambiguity flags, quoted match evidence, declared translation-version grouping, and per-language coverage gaps in a contract-preserving result.json.

## Contents

| File |
|------|
| `SKILL.md` |
| `examples/demo-case/case.json` |
| `scripts/deliver.py` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

A single deterministic pass reads `/input`, computes the deliverable and writes a
contract-complete `/app/output/result.json` plus the human-readable review files
described in `SKILL.md`. The same input always produces byte-identical output; no
network access is used, and fields the materials cannot support are reported
explicitly instead of being left empty.

## Notes

- Pure Python standard library; no network access required.
- Every claim is anchored to paragraph-level evidence; unknown items are reported
  in `uncertainty` instead of being fabricated.
