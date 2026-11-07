#!/usr/bin/env python3
"""Tests for md_to_html.py conversion."""

import importlib.util
import os
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'md_to_html.py')

_spec = importlib.util.spec_from_file_location('md_to_html', SCRIPT)
md_to_html = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(md_to_html)


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


if __name__ == '__main__':
    unittest.main()
