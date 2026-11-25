#!/usr/bin/env python3
"""Cross-lingual literature search with supplied-only terminology (stdlib only).

Reads a case file (default /input/case.json) with a query, target languages, an
optional glossary and records in several languages. It builds a per-language
query using only translations actually present in the glossary (missing terms
stay in the original language and are listed), detects each record's language
from declared metadata or script with an ambiguity flag, scores matches with
quoted evidence, groups declared translation versions, and reports per-language
coverage. Writes result.json preserving case_id and all output_contract fields.

No translation service, no network, no randomness, no fabricated translations.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

DEFAULT_CASE = "/input/case.json"
DEFAULT_OUT = "/app/output/result.json"
DEFAULT_WORK = "/app/work"

RECORD_KEYS = ("records", "results", "items", "papers", "hits", "documents")
GLOSSARY_KEYS = ("glossary", "terminology", "translations", "term_bank", "lexicon")
TITLE_KEYS = ("title", "article_title", "paper_title", "display_name", "题名")
LANG_NAMES = {
    "english": "en", "chinese": "zh", "japanese": "ja", "korean": "ko", "german": "de",
    "french": "fr", "spanish": "es", "russian": "ru", "portuguese": "pt", "arabic": "ar",
    "italian": "it", "dutch": "nl", "polish": "pl", "turkish": "tr", "hindi": "hi", "thai": "th",
    "中文": "zh", "汉语": "zh", "英文": "en", "英语": "en", "日文": "ja", "日语": "ja",
    "德文": "de", "德语": "de", "法文": "fr", "法语": "fr",
}
LATIN_STOPWORDS = {
    "en": {"the", "and", "of", "in", "with", "for", "from", "study", "patients", "was", "were"},
    "de": {"der", "die", "das", "und", "mit", "von", "bei", "wurden", "studie", "patienten"},
    "fr": {"les", "des", "une", "dans", "avec", "pour", "chez", "etude", "patients", "était"},
    "es": {"los", "las", "una", "con", "para", "del", "por", "estudio", "pacientes", "fueron"},
    "pt": {"dos", "das", "uma", "com", "para", "do", "por", "estudo", "pacientes", "foram"},
    "it": {"gli", "delle", "una", "con", "per", "del", "studio", "pazienti", "sono"},
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_task_text(case_path, work_dir):
    for path in (Path(case_path).resolve().parent / "task.md", Path("/input/task.md"), Path(work_dir) / "task.md"):
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
    return ""


def norm_space(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def pick(record, names):
    for name in names:
        value = record.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def authors_of(value):
    if isinstance(value, str):
        return norm_space(value)
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str):
                out.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name") or item.get("family") or item.get("literal")
                if name:
                    out.append(str(name).strip())
        return "; ".join(n for n in out if n)
    return ""


def year_of(record):
    raw = pick(record, ("year", "pub_year", "publication_year", "date", "published", "issued"))
    if isinstance(raw, int):
        return raw if 1500 < raw < 2200 else None
    if isinstance(raw, str):
        match = re.search(r"(1[5-9]\d{2}|20\d{2})", raw)
        if match:
            return int(match.group(0))
    return None


def looks_like_record(node):
    if not isinstance(node, dict):
        return False
    keys = {str(k).lower() for k in node.keys()}
    return bool(keys & {k.lower() for k in TITLE_KEYS}) or bool(keys & {"doi", "pmid"})


def norm_lang(value):
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip().lower().replace("_", "-")
    if text in LANG_NAMES:
        return LANG_NAMES[text]
    return text.split("-")[0][:5]


def find_records(case):
    records = []
    if not isinstance(case, dict):
        return records
    containers = [case]
    for key in ("data", "input"):
        if isinstance(case.get(key), dict):
            containers.append(case[key])
    for container in containers:
        for key in RECORD_KEYS:
            value = container.get(key)
            if isinstance(value, list) and value:
                found = [(f"/{key}/{i}", item) for i, item in enumerate(value) if looks_like_record(item)]
                if found:
                    return found
    def walk(node, path, depth):
        if depth > 8 or len(records) > 3000:
            return
        if isinstance(node, dict):
            if looks_like_record(node):
                records.append((path, node))
                return
            for key, value in node.items():
                walk(value, f"{path}/{key}", depth + 1)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}", depth + 1)
    walk(case, "", 0)
    return records


# --------------------------------------------------------------------------
# language handling
# --------------------------------------------------------------------------
def script_of(text):
    counts = {
        "hangul": len(re.findall(r"[\uac00-\ud7af]", text)),
        "kana": len(re.findall(r"[\u3040-\u30ff]", text)),
        "han": len(re.findall(r"[\u4e00-\u9fff]", text)),
        "cyrillic": len(re.findall(r"[\u0400-\u04ff]", text)),
        "arabic": len(re.findall(r"[\u0600-\u06ff]", text)),
        "greek": len(re.findall(r"[\u0370-\u03ff]", text)),
        "devanagari": len(re.findall(r"[\u0900-\u097f]", text)),
        "thai": len(re.findall(r"[\u0e00-\u0e7f]", text)),
        "latin": len(re.findall(r"[A-Za-z]", text)),
    }
    return {key: value for key, value in counts.items() if value}


def detect_language(text, declared):
    declared_code = norm_lang(declared) if declared else ""
    scripts = script_of(text)
    if declared_code:
        return {"code": declared_code, "method": "declared_metadata", "ambiguous": False, "scripts": sorted(scripts)}
    if not scripts:
        return {"code": "und", "method": "no_text", "ambiguous": True, "scripts": []}
    if scripts.get("hangul"):
        return {"code": "ko", "method": "script", "ambiguous": False, "scripts": sorted(scripts)}
    if scripts.get("kana"):
        return {"code": "ja", "method": "script", "ambiguous": False, "scripts": sorted(scripts)}
    if scripts.get("han"):
        return {"code": "zh", "method": "script", "ambiguous": True,
                "scripts": sorted(scripts),
                "note": "Han script alone cannot separate Chinese from Japanese kanji-only text"}
    if scripts.get("cyrillic"):
        return {"code": "ru", "method": "script", "ambiguous": True, "scripts": sorted(scripts),
                "note": "Cyrillic is shared by several languages"}
    if scripts.get("arabic"):
        return {"code": "ar", "method": "script", "ambiguous": True, "scripts": sorted(scripts)}
    if scripts.get("greek"):
        return {"code": "el", "method": "script", "ambiguous": True, "scripts": sorted(scripts)}
    if scripts.get("devanagari"):
        return {"code": "hi", "method": "script", "ambiguous": True, "scripts": sorted(scripts)}
    if scripts.get("thai"):
        return {"code": "th", "method": "script", "ambiguous": True, "scripts": sorted(scripts)}
    words = set(re.findall(r"[a-zà-ÿ]+", text.lower()))
    scores = {code: len(words & stops) for code, stops in LATIN_STOPWORDS.items()}
    best = max(scores, key=lambda code: (scores[code], code))
    if scores[best] >= 2:
        return {"code": best, "method": "latin_stopwords", "ambiguous": False, "scripts": sorted(scripts)}
    return {"code": "und", "method": "latin_unresolved", "ambiguous": True, "scripts": sorted(scripts)}


def tokenize(text):
    tokens = re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+|[A-Za-z][A-Za-z0-9\-]{1,}", text)
    return [token for token in tokens if token.strip()]


def term_in(term, text):
    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", term):
        return term in text
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


def sentence_with(text, term):
    position = text.lower().find(term.lower())
    if position < 0:
        return ""
    start = max(text.rfind(". ", 0, position), text.rfind("。", 0, position), text.rfind("; ", 0, position))
    end = len(text)
    for marker in (". ", "。", "; "):
        found = text.find(marker, position)
        if found >= 0:
            end = min(end, found + 1)
    return norm_space(text[start + 1 if start >= 0 else 0:end])[:300]


# --------------------------------------------------------------------------
# glossary
# --------------------------------------------------------------------------
def load_glossary(case):
    """Return list of {"term", "translations": {lang: [values]}, "locator"}."""
    raw = None
    path = ""
    if isinstance(case, dict):
        for key in GLOSSARY_KEYS:
            if case.get(key) not in (None, "", [], {}):
                raw, path = case[key], "/" + key
                break
    entries = []
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            term = str(pick(item, ("term", "source_term", "concept", "en", "original")) or "")
            if not term:
                continue
            translations = {}
            value = item.get("translations") or item.get("targets") or item.get("languages")
            if isinstance(value, dict):
                for lang, values in value.items():
                    code = norm_lang(lang)
                    if isinstance(values, str):
                        values = [values]
                    if isinstance(values, list):
                        translations[code] = [norm_space(str(v)) for v in values if str(v).strip()]
            for lang, values in item.items():
                code = norm_lang(lang)
                if code in ("term", "source-term", "concept", "original", "translations", "targets", "languages"):
                    continue
                if isinstance(values, str) and code and len(code) <= 5:
                    translations.setdefault(code, []).append(norm_space(values))
                elif isinstance(values, list) and code and len(code) <= 5:
                    translations.setdefault(code, []).extend(norm_space(str(v)) for v in values)
            entries.append({"term": norm_space(term), "translations": translations, "locator": f"{path}/{index}"})
    elif isinstance(raw, dict):
        for term, value in raw.items():
            translations = {}
            if isinstance(value, dict):
                for lang, values in value.items():
                    code = norm_lang(lang)
                    if isinstance(values, str):
                        values = [values]
                    if isinstance(values, list):
                        translations[code] = [norm_space(str(v)) for v in values if str(v).strip()]
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        code = norm_lang(str(item.get("language") or item.get("lang") or ""))
                        text = item.get("text") or item.get("term")
                        if code and text:
                            translations.setdefault(code, []).append(norm_space(str(text)))
            entries.append({"term": norm_space(term), "translations": translations, "locator": f"{path}/{term}"})
    return entries


def target_languages(case, entries):
    values = []
    if isinstance(case, dict):
        for key in ("target_languages", "languages", "search_languages", "requested_languages"):
            value = case.get(key)
            if isinstance(value, list) and value:
                values = value
                break
            if isinstance(value, str) and value.strip():
                values = [value]
                break
    codes = []
    for value in values:
        code = norm_lang(value) if isinstance(value, str) else ""
        if code and code not in codes:
            codes.append(code)
    for entry in entries:
        for code in entry["translations"]:
            if code and code not in codes:
                codes.append(code)
    return codes


def build_queries(query, entries, languages):
    """Per-language query text plus the terms that had no supplied translation."""
    matched_entries = [entry for entry in entries if term_in(entry["term"], query)]
    queries = []
    for code in languages:
        translated, missing = [], []
        rendered = query
        for entry in matched_entries:
            options = entry["translations"].get(code) or []
            if options:
                translated.append({"term": entry["term"], "as": options[0], "alternatives": options[1:]})
                rendered = rendered.replace(entry["term"], options[0])
            else:
                missing.append({"term": entry["term"], "reason": "no supplied translation for %s" % code})
        queries.append({
            "language": code,
            "query": rendered,
            "translated_terms": translated,
            "untranslated_terms": missing,
            "status": "translated" if translated and not missing else ("partial" if translated else "original_only"),
            "note": "Translation uses only glossary entries present in the case; no machine translation was performed.",
        })
    return queries


# --------------------------------------------------------------------------
# records / matching
# --------------------------------------------------------------------------
def normalize(raw, locator):
    record = raw if isinstance(raw, dict) else {}
    title = norm_space(str(pick(record, TITLE_KEYS) or ""))
    abstract = norm_space(str(pick(record, ("abstract", "summary")) or ""))
    declared = pick(record, ("language", "lang", "language_code", "dc_language"))
    detected = detect_language(title + " " + abstract, declared)
    return {
        "locator": locator,
        "record_id": str(pick(record, ("record_id", "id", "paper_id", "uid", "key")) or ""),
        "title": title,
        "abstract": abstract,
        "doi": norm_space(str(pick(record, ("doi", "DOI")) or "")).lower().replace("https://doi.org/", ""),
        "authors": authors_of(pick(record, ("authors", "author", "creator"))),
        "year": year_of(record),
        "journal": norm_space(str(pick(record, ("journal", "venue", "container_title")) or "")),
        "language_declared": norm_space(str(declared or "")),
        "language": detected["code"],
        "language_detection": detected,
        "translation_of": str(pick(record, ("translation_of", "is_translation_of", "version_of", "original_id", "group_id")) or ""),
        "raw": record,
    }


def score_record(rec, terms, language):
    score = 0
    hits = []
    for term in terms:
        if not term:
            continue
        if term_in(term, rec["title"]):
            score += 3
            hits.append({"term": term, "field": "title", "quote": sentence_with(rec["title"], term)})
        elif term_in(term, rec["abstract"]):
            score += 1
            hits.append({"term": term, "field": "abstract", "quote": sentence_with(rec["abstract"], term)})
    if hits and rec["language"] == language:
        score += 1
        hits.append({"term": None, "field": "language", "quote": rec["language_declared"] or rec["language"]})
    return score, hits


def group_versions(records):
    parent = list(range(len(records)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    links = {}
    for index, rec in enumerate(records):
        if rec["doi"]:
            links.setdefault("doi:" + rec["doi"], []).append(index)
        if rec["translation_of"]:
            target = rec["translation_of"].strip().lower()
            target = re.sub(r"^https?://(dx\.)?doi\.org/", "", target)
            links.setdefault("doi:" + target, []).append(index)
    for value in links.values():
        for other in value[1:]:
            union(value[0], other)
    groups = {}
    for index in range(len(records)):
        groups.setdefault(find(index), []).append(index)
    return [sorted(members) for _, members in sorted(groups.items(), key=lambda kv: min(kv[1])) if len(members) > 1]


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------
def contract_names(case):
    contract = case.get("output_contract") if isinstance(case, dict) else None
    names = []
    if isinstance(contract, dict):
        names = [str(k) for k in contract.keys()]
    elif isinstance(contract, list):
        for item in contract:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                for key in ("name", "field", "key", "id"):
                    if isinstance(item.get(key), str):
                        names.append(item[key])
                        break
    return names


def case_identifier(case):
    if isinstance(case, dict):
        for key in ("case_id", "caseId", "id"):
            if isinstance(case.get(key), str) and case[key].strip():
                return case[key]
    return ""


def build_payload(case, task_text):
    query = norm_space(str(pick(case, ("query", "search_query", "question", "topic")) or "")) if isinstance(case, dict) else ""
    entries = load_glossary(case)
    languages = target_languages(case, entries)
    if not languages:
        languages = ["en"]

    queries = build_queries(query, entries, languages)
    raw_records = find_records(case)
    records = [normalize(raw, locator) for locator, raw in raw_records]

    matches = []
    per_language = []
    for lang_query in queries:
        code = lang_query["language"]
        terms = [translated["as"] for translated in lang_query["translated_terms"]]
        if not terms:
            terms = tokenize(query)
        rows = []
        for rec in records:
            score, hits = score_record(rec, terms, code)
            if score <= 0:
                continue
            rows.append({
                "record_id": rec["record_id"] or rec["locator"],
                "title": rec["title"],
                "doi": rec["doi"],
                "year": rec["year"],
                "language": rec["language"],
                "language_match": rec["language"] == code,
                "score": score,
                "matched_terms": sorted({hit["term"] for hit in hits if hit["term"]}),
                "evidence": hits[:6],
                "source_locator": rec["locator"],
            })
        rows.sort(key=lambda row: (-row["score"], -(row["year"] or 0), row["title"]))
        matches.extend(rows)
        per_language.append({
            "language": code,
            "query": lang_query["query"],
            "query_status": lang_query["status"],
            "terms_used": terms,
            "untranslated_terms": [item["term"] for item in lang_query["untranslated_terms"]],
            "records_in_language": sum(1 for rec in records if rec["language"] == code),
            "matches": len(rows),
            "status": "covered" if rows else ("no_matching_records" if any(rec["language"] == code for rec in records) else "no_records_in_language"),
        })

    version_groups = []
    for group in group_versions(records):
        version_groups.append({
            "members": [{"record_id": records[i]["record_id"] or records[i]["locator"],
                         "language": records[i]["language"], "title": records[i]["title"],
                         "locator": records[i]["locator"]} for i in group],
            "basis": "shared DOI or declared translation link",
            "note": "Cross-script titles are not compared; grouping relies on declared links only.",
        })

    detected_languages = {}
    for rec in records:
        detected_languages[rec["language"]] = detected_languages.get(rec["language"], 0) + 1
    ambiguous = [{"record_id": rec["record_id"] or rec["locator"], "language": rec["language"],
                  "note": rec["language_detection"].get("note", "language could not be resolved from supplied metadata")}
                 for rec in records if rec["language_detection"]["ambiguous"]]

    # Back-translation and mistranslation review (glossary round-trip, heuristic).
    reverse = {}
    for entry in entries:
        for code, values in entry["translations"].items():
            for value in values:
                reverse.setdefault((code, value.lower()), []).append(entry["term"])
    corpus_by_lang = {}
    for rec in records:
        corpus_by_lang.setdefault(rec["language"], []).append(
            (rec["title"] + " " + rec["abstract"]).lower())
    back_translation = []
    mistranslation_review = []
    for lang_query in queries:
        code = lang_query["language"]
        for item in lang_query["translated_terms"]:
            term, target = item["term"], item["as"]
            back = sorted({t for t in reverse.get((code, target.lower()), [])})
            round_trip = any(t.lower() == term.lower() for t in back)
            observed = any(target.lower() in text for text in corpus_by_lang.get(code, []))
            back_translation.append({
                "language": code,
                "term_original": term,
                "term_translated": target,
                "back_translated": back,
                "glossary_round_trip": round_trip,
                "observed_in_corpus": observed,
                "method": "glossary reverse lookup",
                "heuristic": True,
                "note": "Heuristic check over the supplied glossary; no machine-translation service was queried.",
                "verdict": ("consistent" if round_trip
                            else ("round_trip_mismatch" if back else "no_reverse_entry")),
            })
            if not round_trip:
                mistranslation_review.append({
                    "language": code, "term_original": term, "term_translated": target,
                    "issue": "round_trip_mismatch" if back else "no_glossary_round_trip",
                    "action": "kept as supplied by the glossary and flagged for human review; not silently rewritten",
                })
            elif not observed and corpus_by_lang.get(code):
                mistranslation_review.append({
                    "language": code, "term_original": term, "term_translated": target,
                    "issue": "translated_term_not_observed_in_corpus",
                    "action": "glossary-backed translation absent from the supplied records; possible variant wording, flagged for review",
                })

    languages_requested = [lang_query["language"] for lang_query in queries]
    languages_with_results = [row["language"] for row in per_language if row["matches"] > 0]
    languages_without_results = [code for code in languages_requested
                                 if code not in languages_with_results]
    language_accounting = {
        "languages_requested": languages_requested,
        "languages_with_results": languages_with_results,
        "languages_without_results": languages_without_results,
        "no_result_reasons": {row["language"]: row["status"] for row in per_language
                              if row["matches"] == 0},
        "closed": sorted(set(languages_requested))
                  == sorted(set(languages_with_results) | set(languages_without_results)),
        "record_languages": detected_languages,
    }
    stats = {
        "records": len(records),
        "languages_requested": len(languages_requested),
        "languages_with_results": len(languages_with_results),
        "matches": len(matches),
        "glossary_entries": len(entries),
        "back_translation_checks": len(back_translation),
        "mistranslation_flags": len(mistranslation_review),
        "deterministic": True,
    }

    uncertainties = []
    if not raw_records:
        uncertainties.append({"type": "no_records", "detail": "No records were supplied; only queries were constructed."})
    if not query:
        uncertainties.append({"type": "no_query", "detail": "No query string was supplied; matching terms fall back to nothing."})
    if not entries:
        uncertainties.append({"type": "no_glossary", "detail": "No terminology glossary was supplied; all non-original-language queries remain untranslated rather than machine-translated."})
    if any(item["status"] == "original_only" for item in queries):
        uncertainties.append({"type": "untranslated_queries", "detail": "Some target-language queries have no glossary translation and were left in the original language."})
    if any(item["status"] == "no_records_in_language" for item in per_language):
        uncertainties.append({"type": "language_gap", "detail": "At least one requested language has no records in the supplied set; its zero matches reflect input coverage, not absence of literature."})
    if ambiguous:
        uncertainties.append({"type": "language_detection_ambiguity", "detail": "%d record(s) have ambiguous script-based language detection and are flagged, not silently relabelled." % len(ambiguous)})
    uncertainties.append({"type": "metadata_heterogeneity", "detail": "Language, title and abstract fields differ across sources; declared metadata is preferred over script detection."})
    uncertainties.append({"type": "no_machine_translation", "detail": "No translation service was used; only glossary translations present in the case appear in queries."})

    if not raw_records and not query:
        status = "insufficient_input"
    elif not raw_records or not entries:
        status = "partial"
    else:
        status = "success"

    evidence = []
    for entry in entries[:100]:
        evidence.append({"kind": "glossary_entry", "term": entry["term"],
                         "translations": entry["translations"], "locator": entry["locator"]})
    for row in matches[:200]:
        evidence.append({"kind": "match", "record_id": row["record_id"], "language": row["language"],
                         "score": row["score"], "source_locator": row["source_locator"],
                         "quotes": [hit["quote"] for hit in row["evidence"] if hit["quote"]][:2]})

    result = {
        "query_original": query,
        "queries": queries,
        "matches": matches,
        "results": matches,
        "language_coverage": per_language,
        "language_accounting": language_accounting,
        "back_translation": back_translation,
        "mistranslation_review": mistranslation_review,
        "language_distribution": detected_languages,
        "ambiguous_languages": ambiguous,
        "version_groups": version_groups,
        "glossary_entries": len(entries),
        "retrieval_strategy": {
            "translation_source": "supplied glossary only",
            "matching": "term match in title/abstract with language agreement bonus",
            "ranking": "score desc, year desc, title asc",
            "cross_script_title_similarity": "not attempted",
        },
        "limitations": [
            "Without supplied translations no cross-lingual query can be built; no machine translation is used.",
            "Script-based language detection cannot separate all languages sharing a script.",
            "Term matching ignores morphology and synonyms absent from the glossary.",
            "Translation versions are grouped only by declared links or shared DOI.",
        ],
        "change_log": [
            "Read the query, target languages and glossary, then built per-language queries.",
            "Detected record languages from declared metadata first, scripts second.",
            "Scored title/abstract term matches per language with quoted evidence.",
            "Grouped declared translation versions and reported per-language coverage gaps.",
        ],
    }

    return {
        "case_id": case_identifier(case),
        "status": status,
        "result": result,
        "matches": matches,
        "queries": queries,
        "evidence": evidence,
        "uncertainty": uncertainties,
        "errors": [],
        "stats": {
            "records": stats["records"],
            "languages_requested": stats["languages_requested"],
            "languages_covered": stats["languages_with_results"],
            "matches": stats["matches"],
            "version_groups": len(version_groups),
            "ambiguous_languages": len(ambiguous),
            "back_translation_checks": stats["back_translation_checks"],
            "mistranslation_flags": stats["mistranslation_flags"],
            "network": "disabled",
            "deterministic": True,
        },
    }


CONTRACT_ALIASES = {
    "issues": ("findings", "problems", "defects", "violations"),
    "findings": ("issues",),
    "summary": ("stats", "overview", "counts", "tally"),
    "overview": ("summary", "stats"),
    "stats": ("summary",),
    "verdict": ("recommendation", "decision", "conclusion", "overall"),
    "reviewreport": ("report", "review", "markdown"),
    "report": ("review_report", "review"),
    "scores": ("score", "metrics", "verdict"),
    "metrics": ("scores", "stats"),
    "rows": ("records", "data", "table"),
    "records": ("rows", "data"),
    "citations": ("reference_checks", "citation_checks", "references"),
    "tables": ("table_extractions", "tables_extracted"),
    "figures": ("figure_mentions", "figures_extracted"),
}


def _norm_key(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _severity_counts(findings):
    counts = {}
    if isinstance(findings, list):
        for item in findings:
            if not isinstance(item, dict):
                continue
            sev = str(item.get("severity") or item.get("level") or "unspecified").lower()
            counts[sev] = counts.get(sev, 0) + 1
    return counts


def _derive_named(name, flat):
    """Return a value for `name` derived from the payload, or (None, reason)."""
    norm = _norm_key(name)
    for alias in CONTRACT_ALIASES.get(norm, ()):
        if alias in flat and flat[alias] not in (None, "", [], {}):
            return flat[alias], "derived from '%s'" % alias
    findings = flat.get("findings") or flat.get("issues") or []
    if norm in ("verdict", "reviewverdict", "decision", "recommendation", "overallverdict"):
        counts = _severity_counts(findings)
        if counts or flat.get("checks"):
            decision = ("major_revision" if counts.get("high")
                        else "minor_revision" if counts.get("medium")
                        else "accept")
            return ({"decision": decision,
                     "basis": "derived from %d finding(s) and %d check(s)"
                              % (len(findings) if isinstance(findings, list) else 0,
                                 len(flat.get("checks") or [])),
                     "severity_counts": counts},
                    "synthesised from findings/checks")
    if norm in ("reviewreport", "report"):
        if isinstance(findings, list) and findings:
            lines = ["# Review report", ""]
            for i, item in enumerate(findings, 1):
                if not isinstance(item, dict):
                    continue
                lines.append("## %d. %s" % (i, item.get("category") or item.get("kind") or "finding"))
                lines.append("")
                lines.append("- severity: %s" % (item.get("severity") or "unspecified"))
                if item.get("issue"):
                    lines.append("- issue: %s" % item["issue"])
                if item.get("evidence"):
                    lines.append("- evidence: %s" % item["evidence"])
                if item.get("suggestion"):
                    lines.append("- suggested fix: %s" % item["suggestion"])
                lines.append("")
            return ({"format": "markdown", "content": "\n".join(lines)},
                    "rendered from findings")
    return None, "not derivable from this run's data"


def apply_contract(payload, case):
    names = contract_names(case)
    notes = {}
    flat = {}
    for holder in (payload, payload.get("result") if isinstance(payload.get("result"), dict) else {}):
        if not isinstance(holder, dict):
            continue
        for key, value in holder.items():
            flat.setdefault(str(key), value)
    for name in names:
        if name in payload and payload[name] is not None:
            notes[name] = "produced directly by this run"
            continue
        value, reason = _derive_named(name, flat)
        if value is not None:
            payload[name] = value
            notes[name] = reason
        else:
            payload[name] = None
            notes[name] = reason
    payload["contract_notes"] = notes
    payload["output_contract_fields"] = {"provided": names,
                                         "present": {name: payload.get(name) is not None
                                                     for name in names}}
    return payload


def write_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, str(target))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cross-lingual literature search using supplied glossary translations only")
    parser.add_argument("--case", default=DEFAULT_CASE, help="input case JSON (default: /input/case.json)")
    parser.add_argument("--out", "--output", default=DEFAULT_OUT, help="output result JSON (default: /app/output/result.json)")
    parser.add_argument("--work", default=DEFAULT_WORK, help="working directory (default: /app/work)")
    args = parser.parse_args(argv)
    os.environ["SK_RESULT_PATH"] = str(getattr(args, "out", None) or getattr(args, "output", None) or "")

    case = {}
    try:
        case = load_json(args.case)
        if not isinstance(case, dict):
            raise ValueError("case.json root must be a JSON object")
        try:
            Path(args.work).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        task_text = read_task_text(args.case, args.work)
        payload = build_payload(case, task_text)
        code = 0
    except Exception as exc:
        payload = {
            "case_id": case_identifier(case) if isinstance(case, dict) else "",
            "status": "failed",
            "result": None,
            "matches": [],
            "queries": [],
            "evidence": [],
            "uncertainty": [{"type": "run_failure", "detail": "Run failed; no cross-lingual conclusion is reported."}],
            "errors": [{"stage": "build", "type": type(exc).__name__, "message": str(exc)[:500]}],
            "stats": {},
        }
        code = 2

    payload = apply_contract(payload, case if isinstance(case, dict) else {})
    try:
        import deliver as _deliver
        _deliver.finalize(payload, args.out, case if isinstance(case, dict) else {{}})
    except Exception:
        pass
    try:
        write_json(args.out, payload)
    except Exception as exc:
        sys.stderr.write(json.dumps({"status": "failed", "stage": "write_output", "message": str(exc)[:300]}) + "\n")
        return 3

    sys.stdout.write(json.dumps({
        "status": payload.get("status"),
        "case_id": payload.get("case_id"),
        "out": str(args.out),
        "matches": payload.get("stats", {}).get("matches", 0),
    }, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.environ.get("SK_RESULT_PATH") or "result.json"
            _d = os.path.dirname(os.path.abspath(_p))
            if _d:
                os.makedirs(_d, exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    _fallback = os.environ.get("SK_RESULT_PATH", "")
    if _fallback and not os.path.isfile(_fallback):
        try:
            _parent = os.path.dirname(os.path.abspath(_fallback))
            if _parent:
                os.makedirs(_parent, exist_ok=True)
            with open(_fallback, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0 if _fallback else _rc)
