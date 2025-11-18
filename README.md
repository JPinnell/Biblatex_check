# BibTeX Diagnostic and Cleaning Tools

Two focused Python tools for working with BibTeX/BibLaTeX files:

1. **biblatex_diagnostics.py** - Validates entries against online APIs (Crossref + Semantic Scholar)
2. **biblatex_cleaner.py** - Local formatting validator (no API calls, works offline)

Perfect for cleaning up bibliographies with hallucinated or incorrect references from LLMs.

## biblatex_diagnostics.py - API Validation

Automatically compares your BibTeX entries against ground truth from Crossref and Semantic Scholar.

### Features

- **Crossref Primary**: Fast bibliographic database (20 requests/sec, no API key needed)
- **Semantic Scholar Fallback**: Academic search when Crossref doesn't find a match
- **Automatic Replacement**: Replaces entries with authoritative data from APIs
- **Smart Title Matching**: Fuzzy matching (70% Jaccard similarity) handles title variations
- **Dual-API Coverage**: Comprehensive coverage with two complementary databases

### How It Works

For each entry in your `.bib` file:
1. Extracts the title
2. Searches Crossref API (primary, very fast at 20 req/sec)
3. If not found, searches Semantic Scholar API (fallback)
4. Uses fuzzy matching to compare titles
5. Reports matches, mismatches, and entries not found
6. Optionally replaces entries with complete, accurate data from APIs

## Installation

### Requirements

```bash
# Using conda (recommended)
conda install pybtex requests

# Or using pip
pip install pybtex requests
```

### API Configuration (Optional)

**Crossref Polite Pool (Recommended):**

Get better service by identifying yourself:

```bash
export CROSSREF_MAILTO="your-email@example.com"
```

**Semantic Scholar API Key (Optional):**

For better fallback performance:

```bash
export SEMANTIC_SCHOLAR_API_KEY="your-api-key-here"
```

Get a free key from [Semantic Scholar](https://www.semanticscholar.org/product/api).

## Usage - biblatex_diagnostics.py

### Validate All Entries

Compare all entries against APIs and get a report:

```bash
python biblatex_diagnostics.py my_references.bib
```

**Output:**
```
Validating 100 entries against APIs...
============================================================

[1/100] Checking: einstein1905
[INFO] Searching Crossref for: On the Electrodynamics of Moving Bodies
[INFO] ✓ Match found on Crossref

[2/100] Checking: fake_paper2023
[INFO] Searching Crossref for: Machine Learning with Quantum Entanglement
[INFO] Not found on Crossref
[INFO] Searching Semantic Scholar for: Machine Learning with Quantum Entanglement
[INFO] Not found on Semantic Scholar

...

==========================================================
BIBTEX API VALIDATION REPORT
============================================================

Matches: 85
  ✓ einstein1905: Found on crossref
  ✓ smith2020: Found on semantic_scholar
  ...

Not Found: 15
  ✗ fake_paper2023: Not found in any API
  ...

============================================================
```

### Update Entries with API Data

Automatically replace entries with authoritative bibliographic data:

```bash
python biblatex_diagnostics.py my_references.bib --update -o corrected.bib
```

**This will:**
1. Search Crossref for each entry (~700 entries in ~35 seconds)
2. Fall back to Semantic Scholar for entries Crossref doesn't have
3. Replace matching entries with complete, accurate metadata
4. Save corrected bibliography to `corrected.bib`
5. Report statistics (Crossref matches, Semantic Scholar matches, not found)

### Save Report to File

```bash
python biblatex_diagnostics.py my_references.bib -r validation_report.txt
```

### Verbose Mode

See each API query in real-time:

```bash
python biblatex_diagnostics.py my_references.bib -v
```

### Custom Rate Limiting

Adjust delay between Crossref queries (default: 0.05s for 20 req/sec):

```bash
python biblatex_diagnostics.py my_references.bib --delay 0.1
```

## Command-Line Options

```
usage: biblatex_diagnostics.py [-h] [-o OUTPUT] [-r REPORT_FILE] [-v]
                                [--delay DELAY] [--update]
                                input_file

Arguments:
  input_file            Input BibTeX file

Options:
  -o, --output         Output file for corrected BibTeX
  -r, --report-file    Save validation report to file
  -v, --verbose        Verbose output (show API queries)
  --delay DELAY        Delay between Crossref queries (default: 0.05s)
  --update             Update entries with API data (requires -o)
```

## Examples

### Example 1: Quick Validation

Check which entries match online databases:

```bash
python biblatex_diagnostics.py references.bib
```

### Example 2: Fix Hallucinated References

You have a bibliography with ~700 entries, many potentially hallucinated by an LLM:

```bash
python biblatex_diagnostics.py llm_generated.bib --update -o fixed.bib -v
```

This will:
- Validate all 700 entries against Crossref + Semantic Scholar
- Replace matches with authoritative data
- Take ~35-40 seconds (thanks to Crossref's 20 req/sec rate limit)
- Show progress in real-time with `-v`

### Example 3: Generate Validation Report

Create a detailed report for manual review:

```bash
python biblatex_diagnostics.py suspicious_refs.bib -r validation_report.txt -v
```

Review `validation_report.txt` to see:
- Which entries matched (and from which API)
- Which entries had title mismatches
- Which entries weren't found in any database

## Performance

**Speed with Crossref:**
- 20 requests/sec (default 0.05s delay)
- 700 entries: ~35 seconds
- No API key required (polite pool with email recommended)

**Semantic Scholar Fallback:**
- With API key: 1 request/sec
- Without API key: ~0.2 requests/sec
- Only used for entries Crossref doesn't have

## Tips for Best Results

- **Set CROSSREF_MAILTO**: Better service from Crossref polite pool
- **Backup First**: Always keep original `.bib` file before using `--update`
- **Review Not Found**: Entries not found in either API may be:
  - Typos or hallucinations
  - Very recent papers (not yet indexed)
  - Non-English publications
  - Books or reports not in academic databases
- **Title Variations**: Tool uses fuzzy matching (70% similarity) to handle punctuation differences, but manual review is recommended for mismatches

## Troubleshooting

**Rate Limiting:**
- Crossref: Default 0.05s delay (20 req/sec) is within limits
- Semantic Scholar: Automatic retry with exponential backoff
- Adjust with `--delay` if needed

**403 Errors:**
- Set `CROSSREF_MAILTO` environment variable
- Check internet connection

**Title Mismatches:**
- Review manually - fuzzy matching isn't perfect
- Some entries may have significantly different titles online vs in your file

## biblatex_cleaner.py - Local Formatting Validator

Checks local formatting issues without making any API calls. Fast and works offline.

### Features

**Character & Formatting:**
- Unicode character detection (em-dashes, smart quotes, ellipsis)
- Unescaped ampersands (`&` → `\&`)
- Special character issues (`%`, `_`)
- Accent formatting (é → `\'e`, ñ → `\~n`)
- Name formatting problems

**Entry Validation:**
- Entry type validation (required fields for @article, @book, etc.)
- Date/year validity
- ISBN/ISSN/arXiv/DOI format validation
- Field consistency (journal vs journaltitle)
- Completeness checking (recommended fields)
- Crossref validation (verify references exist)
- Duplicate detection (fuzzy matching)

### Usage

Run all formatting checks:

```bash
python biblatex_cleaner.py my_references.bib
```

Save report to file:

```bash
python biblatex_cleaner.py my_references.bib -r formatting_report.txt
```

Skip specific checks:

```bash
# Skip completeness and duplicate checks (faster)
python biblatex_cleaner.py refs.bib --no-completeness --no-duplicates

# Only check critical issues (no warnings)
python biblatex_cleaner.py refs.bib --no-completeness --no-consistency
```

### Command-Line Options

```
Options:
  -r, --report-file    Save report to file
  -v, --verbose        Verbose output

Skip checks:
  --no-unicode         Skip unicode character checking
  --no-ampersand       Skip ampersand checking
  --no-special         Skip special character checking
  --no-accents         Skip accent formatting checking
  --no-names           Skip name formatting checking
  --no-entry-types     Skip entry type validation
  --no-dates           Skip date validation
  --no-identifiers     Skip identifier format validation
  --no-consistency     Skip field consistency checking
  --no-completeness    Skip completeness checking
  --no-crossrefs       Skip crossref validation
  --no-duplicates      Skip duplicate detection
```

### Example Output

```
Validating 100 entries (local checks only, no API calls)...
============================================================

[1/100] Checking: einstein1905
[2/100] Checking: smith2023
...

============================================================
BIBTEX FORMATTING REPORT
============================================================

Issues Found: 15
  ✗ Entry smith2023, field 'title': Contains em-dash ('—')
  ✗ Entry jones2020, field 'author': Contains unescaped ampersand (use \&)
  ✗ Entry doe2021 (@article): Missing required fields: journaltitle
  ✗ Entry fake2022: Invalid year '2050' (>5 years ahead)
  ...

Warnings: 25
  ⚠ Entry old_style2019: Use 'journaltitle' instead of 'journal' in biblatex
  ⚠ Entry incomplete2020 (@article): Missing recommended fields: volume, number
  ⚠ Possible duplicate: 'paper_v1' and 'paper_v2' (95% similar)
  ...

============================================================
```

### Performance

- **Very fast**: No network calls, purely local validation
- Works offline
- 700 entries: < 2 seconds

## License

MIT License

## Contributing

Issues and pull requests welcome at https://github.com/JPinnell/Biblatex_check
