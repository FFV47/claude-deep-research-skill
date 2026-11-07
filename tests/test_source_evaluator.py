#!/usr/bin/env python3
"""Tests for source_evaluator.py domain scoring, including Brazilian sources."""

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'source_evaluator.py')

_spec = importlib.util.spec_from_file_location('source_evaluator', SCRIPT)
source_evaluator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(source_evaluator)


def authority(url: str) -> float:
    ev = source_evaluator.SourceEvaluator()
    return ev.evaluate_source(url=url, title='Artigo').domain_authority


def overall(url: str) -> float:
    ev = source_evaluator.SourceEvaluator()
    return ev.evaluate_source(url=url, title='Artigo').overall_score


class TestBrazilianDomains(unittest.TestCase):
    def test_academic_domains_are_high_authority(self):
        for url in ['https://www.scielo.br/j/x', 'https://bdtd.ibict.br/x',
                    'https://jornal.usp.br/x', 'https://www.ifsp.edu.br/x']:
            with self.subTest(url=url):
                self.assertEqual(authority(url), 90.0)

    def test_public_sector_domains_are_high_authority(self):
        for url in ['https://www.gov.br/x', 'https://www.ibge.gov.br/x',
                    'https://www.camara.leg.br/x', 'https://portal.stf.jus.br/x',
                    'https://www.mpf.mp.br/x']:
            with self.subTest(url=url):
                self.assertEqual(authority(url), 90.0)

    def test_news_domains_are_moderate_authority(self):
        for url in ['https://www1.folha.uol.com.br/x', 'https://g1.globo.com/x',
                    'https://www.estadao.com.br/x', 'https://agenciabrasil.ebc.com.br/x']:
            with self.subTest(url=url):
                self.assertEqual(authority(url), 70.0)

    def test_academic_source_outscores_unknown_domain(self):
        self.assertGreater(overall('https://www.scielo.br/j/x'),
                           overall('https://www.tripadvisor.com/x'))

    def test_government_root_domain_gets_expertise_bonus(self):
        ev = source_evaluator.SourceEvaluator()
        score = ev.evaluate_source(url='https://www.gov.br/x', title='Artigo')
        self.assertGreaterEqual(score.expertise, 75.0)


class TestPortugueseContent(unittest.TestCase):
    def test_balanced_portuguese_content_gets_bias_bonus(self):
        ev = source_evaluator.SourceEvaluator()
        plain = ev.evaluate_source(url='https://x.com.br', title='Artigo', content='Texto.')
        balanced = ev.evaluate_source(url='https://x.com.br', title='Artigo',
                                      content='O dado subiu. No entanto, a amostra é pequena.')
        self.assertEqual(balanced.bias_score - plain.bias_score, 10.0)

    def test_sensational_portuguese_title_loses_bias_points(self):
        ev = source_evaluator.SourceEvaluator()
        plain = ev.evaluate_source(url='https://x.com.br', title='Artigo')
        sensational = ev.evaluate_source(url='https://x.com.br',
                                         title='Você não vai acreditar no que aconteceu')
        self.assertEqual(plain.bias_score - sensational.bias_score, 20.0)


class TestDomainMatching(unittest.TestCase):
    def test_subdomains_match_listed_parent(self):
        self.assertEqual(authority('https://pt.wikipedia.org/wiki/x'), 70.0)
        self.assertEqual(authority('https://www.ncbi.nlm.nih.gov/x'), 90.0)

    def test_lookalike_domains_do_not_match(self):
        self.assertEqual(authority('https://notgov.br/x'), 55.0)
        self.assertEqual(authority('https://fakeusp.br/x'), 55.0)

    def test_unknown_domain_keeps_default(self):
        self.assertEqual(authority('https://www.tripadvisor.com/x'), 55.0)

    def test_domain_lists_contain_only_hostnames(self):
        ev = source_evaluator.SourceEvaluator
        for d in ev.HIGH_AUTHORITY_DOMAINS | ev.MODERATE_AUTHORITY_DOMAINS:
            with self.subTest(domain=d):
                self.assertNotIn('/', d)


# The three classes below come from upstream PR #10, with dates made relative
# to today so the tests do not expire.

class TestRecency(unittest.TestCase):
    """Recency must score tz-aware ISO dates, not fall through to the default."""

    def setUp(self):
        self.evaluator = source_evaluator.SourceEvaluator()

    def _recency(self, date: str) -> float:
        return self.evaluator.evaluate_source(
            url='https://www.nature.com/x', title='T', publication_date=date
        ).recency

    def test_zulu_date_scores_recent(self):
        recent = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.assertGreaterEqual(self._recency(recent), 85.0)

    def test_naive_date_still_scores_recent(self):
        recent = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        self.assertGreaterEqual(self._recency(recent), 85.0)

    def test_missing_date_returns_default(self):
        score = self.evaluator.evaluate_source(url='https://x.com', title='T').recency
        self.assertEqual(score, 50.0)


class TestDomainExtraction(unittest.TestCase):
    """www prefix must be stripped, but only as a prefix."""

    def setUp(self):
        self.evaluator = source_evaluator.SourceEvaluator()

    def test_strips_www_prefix(self):
        self.assertEqual(self.evaluator._extract_domain('https://www.nature.com/x'), 'nature.com')

    def test_keeps_www_inside_domain(self):
        self.assertEqual(self.evaluator._extract_domain('https://api.www.gov'), 'api.www.gov')

    def test_does_not_corrupt_quadruple_w(self):
        self.assertEqual(self.evaluator._extract_domain('https://wwww.test.com'), 'wwww.test.com')


class TestExpertiseAuthor(unittest.TestCase):
    """Author credentials raise expertise."""

    def setUp(self):
        self.evaluator = source_evaluator.SourceEvaluator()

    def test_credential_boosts_expertise(self):
        base = self.evaluator.evaluate_source(url='https://x.com', title='Study').expertise
        with_cred = self.evaluator.evaluate_source(
            url='https://x.com', title='Study', author='Dr. Smith'
        ).expertise
        self.assertGreater(with_cred, base)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


class TestCli(unittest.TestCase):
    def test_single_source_returns_object(self):
        result = run_cli('--json', json.dumps({'url': 'https://www.scielo.br/x', 'title': 'Artigo'}))
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out['url'], 'https://www.scielo.br/x')
        self.assertEqual(out['domain_authority'], 90.0)
        self.assertIn(out['recommendation'], ('high_trust', 'moderate_trust', 'low_trust', 'verify'))

    def test_array_returns_one_result_per_source(self):
        sources = [
            {'url': 'https://g1.globo.com/x', 'title': 'Notícia', 'publication_date': '2026-10-01'},
            {'url': 'https://x.blogspot.com/y', 'title': 'Post', 'author': 'Dr. Silva'},
        ]
        result = run_cli('--json', json.dumps(sources))
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual([r['url'] for r in out], [s['url'] for s in sources])

    def test_missing_title_fails_with_message(self):
        result = run_cli('--json', json.dumps({'url': 'https://x.com'}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('title', result.stderr)

    def test_invalid_json_fails(self):
        result = run_cli('--json', '{not json')
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
