#!/usr/bin/env python3
"""
Claim-Support Verification — checks whether evidence supports claims.

CLI subcommands:
  verify       Check all claims against evidence, update support_status
  report       Generate a support verification summary

Version 1 is deterministic and cheap: entity, number, date,
lexical-overlap and negation checks over stored evidence. No LLM calls.
It is a heuristic, not semantic verification.

Only factual claims hard-fail (--strict) on unsupported or needs_review status.
Synthesis/recommendation need traceability but softer thresholds.
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def read_jsonl(path: str) -> list[dict]:
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, 'w') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


# ---------------------------------------------------------------------------
# Support verification logic
# ---------------------------------------------------------------------------

# Extract numbers (integers and decimals)
NUMBER_RE = re.compile(r'\b\d+(?:\.\d+)?(?:%|x|X)?\b')

# Extract year-like numbers
YEAR_RE = re.compile(r'\b(?:19|20)\d{2}\b')

# Extract capitalized entities (naive NER)
ENTITY_RE = re.compile(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b')

# Common stop entities to ignore
STOP_ENTITIES = frozenset([
    'The', 'This', 'That', 'These', 'However', 'Furthermore',
    'Moreover', 'Additionally', 'Therefore', 'Nevertheless',
])


# Negation markers. A claim and a quote that disagree on negation are
# treated as a contradiction, not as support.
NEGATION_WORDS = frozenset([
    'not', 'no', 'never', 'cannot',          # en
    'não', 'nunca', 'nem', 'jamais',         # pt
])
CJK_NEGATIONS = frozenset(['不', '没'])       # zh, matched as characters

# Han ideographs: CJK Unified Ideographs and Extension A. Chinese has no
# spaces between words, so runs are split into character bigrams.
CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]+')

# Extract words in any alphabetic script
WORD_RE = re.compile(r'[^\W\d_]+')

# Extract whole words with an optional "'t" suffix, so "no" inside "NO2"
# is not a negation
NEGATION_WORD_RE = re.compile(r"\b[^\W\d_]+(?:'t)?\b")

# Score thresholds: at or above SUPPORTED is supported, at or above
# PARTIAL is partial, below it needs review
SUPPORTED_THRESHOLD = 0.6
PARTIAL_THRESHOLD = 0.35


def normalize_text(text: str) -> str:
    """NFC-normalize and lowercase, so composed and decomposed accents match."""
    return unicodedata.normalize('NFC', text).lower()


def has_negation(text: str) -> bool:
    """Return True if the text contains a negation marker."""
    # Fold the typographic apostrophe so "doesn’t" matches like "doesn't"
    text = normalize_text(text).replace('’', "'")
    if any(ch in text for ch in CJK_NEGATIONS):
        return True
    words = NEGATION_WORD_RE.findall(text)
    return any(w in NEGATION_WORDS or w.endswith("n't") for w in words)


def extract_tokens(text: str) -> set[str]:
    """Extract significant tokens: words of 4+ letters in alphabetic
    scripts, and character bigrams in Han text."""
    text = normalize_text(text)
    tokens = {w for w in WORD_RE.findall(CJK_RE.sub(' ', text)) if len(w) >= 4}
    for run in CJK_RE.findall(text):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def extract_numbers(text: str) -> set[str]:
    """Extract numeric values."""
    return set(NUMBER_RE.findall(text))


def extract_years(text: str) -> set[str]:
    """Extract year mentions."""
    return set(YEAR_RE.findall(text))


def extract_entities(text: str) -> set[str]:
    """Extract capitalized entity mentions."""
    ents = set(ENTITY_RE.findall(text))
    return ents - STOP_ENTITIES


# Scored components: (name, extractor, weight, mismatch threshold, note).
# A component scores the share of the claim's items found in the quote.
# A component the claim lacks is left out of the score instead of counting
# as a full match.
SCORE_COMPONENTS = (
    ('tokens', extract_tokens, 0.4, 0.3, 'low lexical overlap'),
    ('numbers', extract_numbers, 0.25, 0.5, 'number mismatch'),
    ('years', extract_years, 0.15, 1.0, 'year mismatch'),
    ('entities', extract_entities, 0.2, 0.3, 'entity mismatch'),
)


def compute_support_score(claim_text: str, evidence_quotes: list[str]) -> tuple[str, float, str]:
    """
    Compute support status for a claim given its linked evidence quotes.

    Returns (status, score, notes).
    Score range: 0.0 (no overlap) to 1.0 (strong support).
    """
    if not evidence_quotes:
        return ('unsupported', 0.0, 'no evidence linked')

    # Keep only the components the claim actually has
    claim_components = [
        (name, extract, claim_items, weight, threshold, note)
        for name, extract, weight, threshold, note in SCORE_COMPONENTS
        if (claim_items := extract(claim_text))
    ]
    total_weight = sum(weight for _, _, _, weight, _, _ in claim_components)

    claim_negated = has_negation(claim_text)

    best_score = -1.0  # below any real score, so the first quote sets notes
    best_notes = []
    contradicted = False

    for quote in evidence_quotes:
        matches = [
            (name, len(claim_items & extract(quote)) / len(claim_items), weight, threshold, note)
            for name, extract, claim_items, weight, threshold, note in claim_components
        ]
        score = (
            sum(match * weight for _, match, weight, _, _ in matches) / total_weight
            if total_weight else 0.0
        )

        if score >= PARTIAL_THRESHOLD and has_negation(quote) != claim_negated:
            contradicted = True

        if score > best_score:
            best_score = score
            best_notes = ['no shared content with evidence'] if score == 0.0 else []
            best_notes += [
                note for name, match, _, threshold, note in matches
                # At score 0, "no shared content" replaces the lexical note
                if match < threshold and not (score == 0.0 and name == 'tokens')
            ]

    if contradicted:
        return ('needs_review', round(best_score, 3), 'negation mismatch with evidence')

    # Threshold decision
    if best_score >= SUPPORTED_THRESHOLD:
        status = 'supported'
    elif best_score >= PARTIAL_THRESHOLD:
        status = 'partial'
    else:
        status = 'needs_review'

    if best_notes:
        notes = '; '.join(best_notes)
    elif status == 'supported':
        notes = 'adequate overlap'
    else:
        notes = 'overlap below support threshold'
    return (status, round(best_score, 3), notes)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def factual_claims(claims: list[dict], *statuses: str) -> list[dict]:
    """Return the factual claims whose support_status is one of statuses."""
    return [
        c for c in claims
        if c.get('claim_type') == 'factual' and c.get('support_status') in statuses
    ]


def append_claim_section(lines: list[str], heading: str, claims: list[dict]) -> None:
    """Append a report section listing claims with their status and notes."""
    lines.append(f'## {heading}')
    lines.append('')
    for c in claims:
        lines.append(f'- [{c["support_status"]}] `{c["section_id"]}`: {c["text"][:100]}...')
        if c.get('_support_notes'):
            lines.append(f'  Notes: {c["_support_notes"]}')
    lines.append('')


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify all claims against evidence, update claims.jsonl."""
    claims_path = os.path.join(args.dir, 'claims.jsonl')
    evidence_path = os.path.join(args.dir, 'evidence.jsonl')
    sources_path = os.path.join(args.dir, 'sources.jsonl')

    claims = read_jsonl(claims_path)
    evidence = read_jsonl(evidence_path)
    sources = read_jsonl(sources_path)

    # Build evidence index by source_id
    ev_by_source: dict[str, list[str]] = {}
    ev_by_id: dict[str, dict] = {}
    for ev in evidence:
        sid = ev.get('source_id', '')
        eid = ev.get('evidence_id', '')
        ev_by_source.setdefault(sid, []).append(ev.get('quote', ''))
        ev_by_id[eid] = ev

    # Deduplicate claims
    seen = set()
    unique_claims = []
    for c in claims:
        cid = c.get('claim_id')
        if cid not in seen:
            seen.add(cid)
            unique_claims.append(c)

    verified = 0
    updated_claims = []

    for claim in unique_claims:
        claim_type = claim.get('claim_type', 'factual')

        # Gather evidence for this claim
        cited_ids = claim.get('cited_source_ids', [])
        evidence_ids = claim.get('evidence_ids', [])

        # Collect evidence quotes from linked evidence_ids
        quotes = []
        for eid in evidence_ids:
            if eid in ev_by_id:
                quotes.append(ev_by_id[eid].get('quote', ''))

        # Also gather from cited sources
        for sid in cited_ids:
            if sid in ev_by_source:
                quotes.extend(ev_by_source[sid])

        if not quotes and not cited_ids and not evidence_ids:
            # No links at all
            if claim_type == 'speculation':
                claim['support_status'] = 'supported'  # Speculation doesn't need evidence
            else:
                claim['support_status'] = 'unsupported'
        elif not quotes:
            # Has cited sources but no evidence captured yet
            claim['support_status'] = 'needs_review'
        else:
            status, score, notes = compute_support_score(claim['text'], quotes)
            claim['support_status'] = status
            claim['_support_score'] = score
            claim['_support_notes'] = notes

        verified += 1
        updated_claims.append(claim)

    # Rewrite claims.jsonl with updated statuses
    write_jsonl(claims_path, updated_claims)

    # Compute summary
    status_counts = Counter(c.get('support_status') for c in updated_claims)
    factual_unsupported = len(factual_claims(updated_claims, 'unsupported'))
    factual_needs_review = len(factual_claims(updated_claims, 'needs_review'))
    total_factual = sum(1 for c in updated_claims if c.get('claim_type') == 'factual')

    # Strict mode: fail if any factual claim is unsupported or needs review
    passed = True
    if args.strict and (factual_unsupported > 0 or factual_needs_review > 0):
        passed = False

    print(json.dumps({
        'status': 'pass' if passed else 'fail',
        'verified': verified,
        'support_status_counts': dict(status_counts),
        'factual_unsupported': factual_unsupported,
        'factual_needs_review': factual_needs_review,
        'total_factual': total_factual,
        'unsupported_rate': round(factual_unsupported / max(total_factual, 1), 3),
    }, indent=2))

    if not passed:
        sys.exit(1)


def cmd_report(args: argparse.Namespace) -> None:
    """Generate human-readable support verification report."""
    claims_path = os.path.join(args.dir, 'claims.jsonl')
    claims = read_jsonl(claims_path)

    # Deduplicate
    seen = set()
    unique = []
    for c in claims:
        cid = c.get('claim_id')
        if cid not in seen:
            seen.add(cid)
            unique.append(c)

    lines = ['# Claim Support Verification Report', '']

    # Summary
    status_counts = Counter(c.get('support_status') for c in unique)
    type_counts = Counter(c.get('claim_type') for c in unique)
    lines.append(f'**Total claims:** {len(unique)}')
    lines.append(f'**By type:** {dict(type_counts)}')
    lines.append(f'**By status:** {dict(status_counts)}')
    lines.append('')

    # Unsupported factual claims (the failures)
    unsupported_factual = factual_claims(unique, 'unsupported', 'needs_review')
    if unsupported_factual:
        append_claim_section(lines, 'Unsupported/Review-needed Factual Claims', unsupported_factual)

    # Partial factual claims: some overlap, below the support threshold
    partial_factual = factual_claims(unique, 'partial')
    if partial_factual:
        append_claim_section(lines, 'Partially Supported Factual Claims', partial_factual)

    if not unsupported_factual and not partial_factual:
        lines.append('## All factual claims passed the lexical support check.')
        lines.append('')

    lines.append(
        '_Support status comes from a lexical heuristic (shared words, '
        'numbers, years, entities and negation). It is not semantic '
        'verification: a claim marked supported can still misstate its source._'
    )

    print('\n'.join(lines))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog='verify_claim_support',
        description='Claim-support verification for deep-research v3.0',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # verify
    p_ver = sub.add_parser('verify', help='Verify claims against evidence')
    p_ver.add_argument('--dir', required=True, help='Run directory')
    p_ver.add_argument('--strict', action='store_true', help='Exit 1 if any factual claim is unsupported or needs review')

    # report
    p_rep = sub.add_parser('report', help='Generate verification report')
    p_rep.add_argument('--dir', required=True, help='Run directory')

    args = parser.parse_args()
    dispatch = {
        'verify': cmd_verify,
        'report': cmd_report,
    }
    dispatch[args.command](args)


if __name__ == '__main__':
    main()
