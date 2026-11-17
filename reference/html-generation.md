# HTML Generation: McKinsey Style Report

## Design Principles

- Sharp corners (NO border-radius)
- Muted corporate colors (navy #003d5c, gray #f8f9fa)
- Ultra-compact layout
- Info-first structure
- 14px base font, compact spacing
- No decorative gradients or colors
- NO EMOJIS in final HTML

---

## Generation Steps

### Step 1: Template

The script loads `./templates/mckinsey_report_template.html` by default (`--template [path]` overrides it). No need to read it into context.

### Step 2: Extract Key Metrics

Extract 3-4 key quantitative findings for dashboard display at top.

### Step 3: Build the HTML Report (one call)

```bash
cd ~/.claude/skills/deep-research
python scripts/md_to_html.py [markdown_report_path] --out [html_path] \
  --title "[Report title]" --source-count [N] \
  --metrics '{"[Label 1]": "[Value 1]", "[Label 2]": "[Value 2]"}'
```

The script converts the markdown, fills every template placeholder, writes the file and prints its path. Do not paste the HTML into context or write it by hand.

| Placeholder           | Filled from                                          |
| --------------------- | ---------------------------------------------------- |
| {{TITLE}}             | `--title`                                            |
| {{DATE}}              | `--date` (default: today, YYYY-MM-DD)                |
| {{SOURCE_COUNT}}      | `--source-count`                                     |
| {{METRICS_DASHBOARD}} | `--metrics` (JSON object from step 2)                |
| {{CONTENT}}           | All sections except Bibliography (Appendix included) |
| {{BIBLIOGRAPHY}}      | Bibliography section, one entry per `[N]` line       |

Without `--out`, the script prints both HTML parts in full to stdout (for inspection only).

**Script handles all conversion:**

- Headers: `##` -> `<div class="section"><h2 class="section-title">`
- Headers: `###` -> `<h3 class="subsection-title">`
- Lists: Markdown bullets -> `<ul><li>` with nesting
- Tables: Markdown tables -> `<table>` with thead/tbody
- Paragraphs: Text wrapped in `<p>` tags
- Bold/italic: `**text**` -> `<strong>`, `*text*` -> `<em>`
- Citations: [N] preserved for tooltip conversion

### Step 4: Add Citation Tooltips (Optional)

Attribution Gradients - in the HTML file written by step 3, wrap each [N] citation:

```html
<span class="citation"
  >[N]
  <span class="citation-tooltip">
    <div class="tooltip-title">[Source Title]</div>
    <div class="tooltip-source">[Author/Publisher]</div>
    <div class="tooltip-claim">
      <div class="tooltip-claim-label">Supports Claim:</div>
      [Extract sentence with this citation]
    </div>
  </span>
</span>
```

NOTE: This step is optional for speed. Basic [N] citations are sufficient.

### Step 5: Verify HTML

```bash
python scripts/verify_html.py --html [html_path] --md [md_path]
```

- Pass: Done. Do not open the file; report its path to the user
- Fail: Fix errors and re-run

---

## PDF Generation

**Option A: WeasyPrint Direct (Preferred)**

1. Create print-optimized HTML following `./reference/weasyprint_guidelines.md`
2. Critical CSS:
   - `page-break-inside: avoid` on tables, boxes
   - `page-break-after: avoid` on headings
   - `orphans: 3; widows: 3` on paragraphs
   - Use `display: table` not Flexbox/Grid
   - Font sizes in pt (10pt body, 8pt citations)
3. Generate: `weasyprint [html_path] [pdf_path]`
4. Do not open the PDF; report its path to the user

**Option B: generating-pdf Skill**

Use Task tool with general-purpose agent, invoke generating-pdf skill.
