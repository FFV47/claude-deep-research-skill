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

# Common words that ENTITY_RE catches when they start a sentence (en, pt).
# ENTITY_RE only matches unaccented letters, so accented words are absent.
STOP_ENTITIES = frozenset([
    'The', 'This', 'That', 'These', 'Those', 'However', 'Furthermore',
    'Moreover', 'Additionally', 'Therefore', 'Nevertheless', 'According',
    'It', 'Its', 'He', 'She', 'We', 'They', 'You', 'There', 'Here',
    'My', 'Our', 'Your', 'His', 'Her', 'Their', 'What', 'Which', 'Who',
    'Some', 'None', 'No', 'Not', 'Nobody', 'Nothing', 'Neither', 'Never',
    'All', 'Any', 'Each', 'Every', 'Many', 'Most', 'Few', 'Several', 'Both',
    'Such', 'Only', 'Also', 'Even', 'Then', 'Now', 'An', 'In', 'On', 'At',
    'By', 'For', 'From', 'With', 'As', 'If', 'When', 'While', 'Since',
    'After', 'Before', 'During', 'And', 'But', 'Or', 'So',
    'Isso', 'Isto', 'Este', 'Esta', 'Estes', 'Estas', 'Esse', 'Essa',
    'Esses', 'Essas', 'Aquele', 'Aquela', 'Aquilo', 'Nenhum', 'Nenhuma',
    'Ele', 'Ela', 'Eles', 'Elas', 'Dele', 'Dela', 'Um', 'Uma', 'Uns',
    'Umas', 'Os', 'Meu', 'Minha', 'Meus', 'Minhas', 'Seu', 'Sua', 'Seus',
    'Suas', 'Nosso', 'Nossa', 'Nossos', 'Nossas', 'Qual', 'Quais', 'Quem',
    'Onde', 'Algum', 'Alguma', 'Alguns', 'Algumas', 'Todos', 'Todas',
    'Cada', 'Muitos', 'Muitas', 'Nunca', 'Apenas', 'Somente', 'Ainda',
    'Hoje', 'Depois', 'Antes', 'Durante', 'Segundo', 'Em', 'Na', 'Nos',
    'Nas', 'De', 'Do', 'Da', 'Dos', 'Das', 'Ao', 'Aos', 'Pelo', 'Pela',
    'Pelos', 'Pelas', 'Para', 'Por', 'Com', 'Sem', 'Se', 'Quando', 'Como',
    'Mas',
])


# Han ideographs: CJK Unified Ideographs and Extension A. Chinese has no
# spaces between words, so runs are split into character bigrams.
CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]+')


def normalize_text(text: str) -> str:
    """NFC-normalize and lowercase, so composed and decomposed accents match."""
    return unicodedata.normalize('NFC', text).lower()


# Negation markers and the phrases that contain one without negating live
# in a data file next to this script, so they change without code edits.
# A claim and a quote that disagree on negation are treated as a
# contradiction, not as support.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'negation_lexicon.json'), encoding='utf-8') as _f:
    _LEXICON = json.load(_f)


def _lexicon_words(key: str) -> list[str]:
    """Return a lexicon list, NFC-normalized and lowercased."""
    return [normalize_text(w) for w in _LEXICON[key]]


NEGATION_WORDS = frozenset(_lexicon_words('negation_words'))
CJK_NEGATIONS = frozenset(_lexicon_words('negation_chars'))

# Words that mark a text as Portuguese, and the negation words that, in
# such a text, are contractions ("no" = "em" + "o") and do not negate
PT_MARKERS = frozenset(_lexicon_words('pt_markers'))
PT_CONTRACTIONS = frozenset(_lexicon_words('pt_contractions'))

# Exceptions match as whole words, except Han compounds, which have no
# word boundaries. Longer phrases are tried first.
NEGATION_EXCEPTION_RE = re.compile('|'.join(
    re.escape(e) if CJK_RE.search(e) else rf'\b{re.escape(e)}\b'
    for e in sorted(_lexicon_words('exceptions'), key=len, reverse=True)
))

# Antonym pairs, each side a set of word forms: a negated word equals its
# antonym, so "not closed" agrees with "open".
ANTONYM_PAIRS = [
    tuple(frozenset(normalize_text(w) for w in side) for side in pair)
    for pair in _LEXICON['antonyms']
]

# Extract words in any alphabetic script
WORD_RE = re.compile(r'[^\W\d_]+')

# Extract whole words with their inner apostrophes, so "o" inside
# "O'Brien" is not read as the Portuguese article
PT_MARKER_WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")

# Text before a word that starts a sentence: nothing, or a sentence end,
# with optional quotes or brackets in between
SENTENCE_START_RE = re.compile(r'(?:^|[.!?])\W*$')

# Extract whole words with an optional "'t" suffix, so "no" inside "NO2"
# is not a negation
NEGATION_WORD_RE = re.compile(r"\b[^\W\d_]+(?:'t)?\b")

# Clause boundaries: commas, semicolons, colons, brackets, dashes between
# spaces, sentence ends (en, pt and zh punctuation), and the separator
# words in the lexicon ("but", "mas"). A period inside a number ("2.5")
# is not a boundary. The zh enumeration comma 、 is not a boundary, since
# it joins items of one clause.
CLAUSE_SPLIT_RE = re.compile(
    r'[,;:()\[\]，；：（）。！？]|[.!?](?=\s|$)|\s[-–—]\s|'
    + '|'.join(rf'\b{re.escape(w)}\b' for w in _lexicon_words('clause_separators')),
    re.IGNORECASE,
)

# Score thresholds: at or above SUPPORTED is supported, at or above
# PARTIAL is partial, below it needs review
SUPPORTED_THRESHOLD = 0.6
PARTIAL_THRESHOLD = 0.35


def is_portuguese(text: str) -> bool:
    """Return True if the text contains a Portuguese marker word.

    A marker counts in lowercase, or capitalized at the start of a
    sentence ("O museu"). Elsewhere a capitalized or all-caps word is a
    name or an acronym in any language ("São Paulo", "type O", "NAS")."""
    text = unicodedata.normalize('NFC', text).replace('’', "'")
    for match in PT_MARKER_WORD_RE.finditer(text):
        word = match.group()
        if word.lower() in PT_MARKERS and (
                word.islower()
                or (word.istitle() and SENTENCE_START_RE.search(text[:match.start()]))):
            return True
    return False


def has_negation(text: str, *, portuguese: bool) -> bool:
    """Return True if the text contains a negation marker.

    portuguese says whether the whole text the clause comes from reads as
    Portuguese; there, the contraction "no" does not negate."""
    # Fold the typographic apostrophe so "doesn’t" matches like "doesn't"
    text = normalize_text(text).replace('’', "'")
    text = NEGATION_EXCEPTION_RE.sub(' ', text)
    if any(ch in text for ch in CJK_NEGATIONS):
        return True
    negation_words = NEGATION_WORDS - PT_CONTRACTIONS if portuguese else NEGATION_WORDS
    words = NEGATION_WORD_RE.findall(text)
    return any(w in negation_words or w.endswith("n't") for w in words)


# Three-letter function words (en, pt). Other lowercase three-letter words
# carry the claim's predicate ("won", "big"), so they count as tokens.
# Negation words are left out, since the negation check handles them.
SHORT_FUNCTION_WORDS = frozenset([
    'the', 'and', 'for', 'are', 'was', 'but', 'nor', 'yet', 'you', 'all',
    'any', 'can', 'had', 'has', 'her', 'his', 'its', 'our', 'who', 'how',
    'why', 'may', 'did', 'per', 'via', 'she', 'him', 'own', 'too',
    'que', 'uma', 'uns', 'com', 'por', 'dos', 'das', 'nos', 'nas', 'aos',
    'mas', 'ele', 'ela', 'seu', 'sua', 'foi', 'são', 'sao', 'tem', 'era',
    'ser', 'sem', 'até', 'ate', 'lhe', 'num',
]) | NEGATION_WORDS


def extract_tokens(text: str) -> set[str]:
    """Extract significant tokens: in alphabetic scripts, words of 4+
    letters and lowercase three-letter words other than function words; in
    Han text, character bigrams. A capitalized three-letter word ("Tim",
    "GDP") names the subject, which entities cover, so it is no token."""
    tokens = {
        w.lower() for w in WORD_RE.findall(CJK_RE.sub(' ', unicodedata.normalize('NFC', text)))
        if len(w) >= 4 or (len(w) == 3 and w.islower() and w not in SHORT_FUNCTION_WORDS)
    }
    text = normalize_text(text)
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
    """Extract capitalized entity mentions, without leading stop words,
    so "Some Tesla" yields "Tesla" and "It" yields nothing."""
    ents = set()
    for match in ENTITY_RE.findall(text):
        words = match.split()
        while words and words[0] in STOP_ENTITIES:
            words.pop(0)
        if words:
            ents.add(' '.join(words))
    return ents


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


def claim_components(claim_text: str) -> list[tuple]:
    """Return the scored components the claim actually has, with its items."""
    return [
        (name, extract, claim_items, weight, threshold, note)
        for name, extract, weight, threshold, note in SCORE_COMPONENTS
        if (claim_items := extract(claim_text))
    ]


def score_quote(components: list[tuple], quote: str) -> tuple[float, list[tuple]]:
    """Score one quote against the claim components.

    Returns (score, matches), where matches holds
    (name, match, weight, threshold, note) per component.

    A word the claim and the quote share as an entity scores once, in the
    entities component, and is left out of the tokens. Otherwise a shared
    subject would also match as a token, and the quote "Tesla lost" would
    support the claim "Tesla won"."""
    claim_entities = next(
        (items for name, _, items, *_ in components if name == 'entities'), set())
    shared_entity_words = {
        w for e in claim_entities & extract_entities(quote) for w in normalize_text(e).split()
    }
    matches = []
    for name, extract, claim_items, weight, threshold, note in components:
        if name == 'tokens':
            claim_items = claim_items - shared_entity_words
            if not claim_items:
                continue
        matches.append(
            (name, len(claim_items & extract(quote)) / len(claim_items), weight, threshold, note))
    total_weight = sum(weight for _, _, weight, _, _ in matches)
    score = (
        sum(match * weight for _, match, weight, _, _ in matches) / total_weight
        if total_weight else 0.0
    )
    return score, matches


def content_items(text: str) -> set[str]:
    """Return the items scoring compares: tokens, numbers and entities."""
    return extract_tokens(text) | extract_numbers(text) | extract_entities(text)


def split_clauses(text: str) -> list[str]:
    """Split text at clause punctuation (en, pt and zh) and separator words.

    NFC-normalized, so a decomposed "porém" still matches, but not
    lowercased, since entity extraction needs the original case."""
    return [c for c in CLAUSE_SPLIT_RE.split(unicodedata.normalize('NFC', text)) if c.strip()]


def relevant_clauses(text: str, other: str, *, text_is_claim: bool) -> list[str]:
    """Return the clauses of text that carry content shared with other.

    A clause is relevant if, on its own, it partially matches the other
    text (scored claim against evidence), or if it holds shared content
    that the rest of text lacks. A negation in any other clause does not
    touch what the claim and the evidence have in common."""
    clauses = split_clauses(text)
    other_items = content_items(other)
    relevant = []
    for i, clause in enumerate(clauses):
        claim, quote = (clause, other) if text_is_claim else (other, clause)
        rest = ' '.join(clauses[:i] + clauses[i + 1:])
        shared_here = content_items(clause) & other_items
        if (score_quote(claim_components(claim), quote)[0] >= PARTIAL_THRESHOLD
                or shared_here - content_items(rest)):
            relevant.append(clause)
    return relevant


def uses_opposite_antonyms(text_a: str, text_b: str) -> bool:
    """Return True if the texts take opposite sides of an antonym pair:
    one uses only one side, the other only the opposite side. A text that
    uses both sides ("not open ... closed on holidays") takes neither."""
    words_a = set(WORD_RE.findall(normalize_text(text_a)))
    words_b = set(WORD_RE.findall(normalize_text(text_b)))
    for forms_x, forms_y in ANTONYM_PAIRS:
        a_x, a_y = bool(words_a & forms_x), bool(words_a & forms_y)
        b_x, b_y = bool(words_b & forms_x), bool(words_b & forms_y)
        if (a_x and not a_y and b_y and not b_x) or (a_y and not a_x and b_x and not b_y):
            return True
    return False


def negation_mismatch(claim_text: str, quote: str) -> bool:
    """Return True if claim and quote disagree on negating shared content.

    Each negation and each switch to an antonym flips the meaning once, so
    "not closed" agrees with "open" and "not open" disagrees with "not
    closed". Without a negation, antonyms alone do not count here."""
    claim_clauses = relevant_clauses(claim_text, quote, text_is_claim=True)
    quote_clauses = relevant_clauses(quote, claim_text, text_is_claim=False)
    claim_pt, quote_pt = is_portuguese(claim_text), is_portuguese(quote)
    claim_negated = any(has_negation(c, portuguese=claim_pt) for c in claim_clauses)
    quote_negated = any(has_negation(c, portuguese=quote_pt) for c in quote_clauses)
    if not (claim_negated or quote_negated):
        return False
    flipped = uses_opposite_antonyms(' '.join(claim_clauses), ' '.join(quote_clauses))
    return claim_negated ^ quote_negated ^ flipped


def compute_support_score(claim_text: str, evidence_quotes: list[str]) -> tuple[str, float, str]:
    """
    Compute support status for a claim given its linked evidence quotes.

    Returns (status, score, notes).
    Score range: 0.0 (no overlap) to 1.0 (strong support).
    """
    if not evidence_quotes:
        return ('unsupported', 0.0, 'no evidence linked')

    components = claim_components(claim_text)

    best_score = -1.0  # below any real score, so the first quote sets notes
    best_notes = []
    contradicted = False

    for quote in evidence_quotes:
        score, matches = score_quote(components, quote)

        if score >= PARTIAL_THRESHOLD and negation_mismatch(claim_text, quote):
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
