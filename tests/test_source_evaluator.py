#!/usr/bin/env python3
"""Tests for source_evaluator.py domain scoring, including Brazilian sources."""

import importlib.util
import os
import unittest

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


if __name__ == '__main__':
    unittest.main()
