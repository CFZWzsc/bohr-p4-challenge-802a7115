# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-802a7115` (track: `literature-search`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable entry point and all supporting scripts. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `cross-lingual-literature-search`
- Summary: Use when a research search must cover several languages and only a supplied glossary is available, and needs per-language query construction with untranslated terms listed, script-aware language detection with ambiguity flags, quoted match evidence, declared translation-version grouping, and per-language coverage gaps in a contract-preserving result.json.

## Contents

| File |
|------|
| `SKILL.md` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/run_skill.py --case /input/case.json --output /app/output/result.json
```

The entry point is `SKILL.md`; input/output contracts, error handling and a minimal
usage example are documented there.

## Notes

- Pure Python standard library; no network access required.
- The result JSON keeps the input case id, the main results, per-item evidence,
  a run status and an uncertainty section.
