#!/usr/bin/env python3
"""Tests for md_to_html.py conversion and CLI."""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'md_to_html.py')
FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'valid_report.md')

_spec = importlib.util.spec_from_file_location('md_to_html', SCRIPT)
md_to_html = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(md_to_html)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


SAMPLE = """## Findings

Text before divider.

---

**Date:** 2026-11-07
**Mode:** quick

## Bibliography

[1] Author (2026). "First Title". Publisher. https://example.com/one
[2] Other Author (2025). "Second Title". Journal. https://example.com/two

## Appendix: Methodology

Searched 10 queries.
"""


class TestConversion(unittest.TestCase):
    """Regressions for upstream PR #4."""

    def setUp(self):
        self.content, self.bib = md_to_html.convert_markdown_to_html(SAMPLE)

    def test_appendix_is_not_rendered_as_bibliography(self):
        self.assertNotIn('Searched 10 queries', self.bib)
        self.assertIn('Searched 10 queries', self.content)

    def test_one_paragraph_per_bibliography_entry(self):
        self.assertEqual(self.bib.count('<p class="bib-entry"'), 2)
        self.assertIn('href="https://example.com/two"', self.bib)

    def test_horizontal_rule_becomes_hr(self):
        self.assertIn('<hr class="section-divider">', self.content)
        self.assertNotIn('<p>---', self.content)

    def test_consecutive_metadata_lines_are_split(self):
        self.assertIn('<br><strong>Mode:</strong>', self.content)


class TestCli(unittest.TestCase):
    def test_help_works(self):
        result = run_cli('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('--out', result.stdout)

    def test_stdout_mode_prints_full_content(self):
        result = run_cli(FIXTURE)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(FIXTURE) as f:
            content, bib = md_to_html.convert_markdown_to_html(f.read())
        self.assertGreater(len(content), 1000)  # the old CLI cut output at 1000 chars
        self.assertIn(content, result.stdout)
        self.assertIn(bib, result.stdout)

    def test_out_writes_filled_template(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'report.html')
            result = run_cli(FIXTURE, '--out', out, '--title', 'Relatório',
                             '--source-count', '7', '--metrics', '{"Fontes": "7"}')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), out)
            with open(out) as f:
                html = f.read()
        self.assertNotIn('{{', html)
        self.assertIn('Relatório', html)
        self.assertIn('metric-label">Fontes<', html)

    def test_out_requires_title_and_source_count(self):
        with tempfile.TemporaryDirectory() as d:
            result = run_cli(FIXTURE, '--out', os.path.join(d, 'r.html'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--title', result.stderr)

    def test_missing_file_fails(self):
        result = run_cli('/nonexistent/report.md')
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
