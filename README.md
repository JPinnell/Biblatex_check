# BibTeX Diagnostic Tool

A comprehensive Python tool for validating and correcting BibTeX/BibLaTeX files using Crossref and Semantic Scholar as the ground truth. Perfect for cleaning up bibliographies with hallucinated or incorrect references from LLMs.

## Features

### Main Feature: Crossref + Semantic Scholar Validation
- **Primary: Crossref API**: Fast, high-rate-limit bibliographic database (20 requests/sec)
- **Fallback: Semantic Scholar**: Academic paper database when Crossref doesn't find a match
- **Ground Truth Replacement**: If a matching title is found, pulls the authoritative BibTeX entry
- **Smart Title Matching**: Uses fuzzy matching to handle variations in punctuation and formatting
- **Rate-Limited Queries**: Handles API rate limits (429 errors) with automatic retry and exponential backoff

### Additional Diagnostics

**Core Validation:**
- **Entry Type Validation**: Ensures all required fields are present for each entry type (@article, @book, @inproceedings, etc.)
- **Date/Year Validation**: Checks for impossible dates, future years, invalid months, and malformed date fields
- **Identifier Validation**: Validates ISBN, ISSN, arXiv ID, and DOI formats; detects placeholder values (TBA, ???, etc.)
- **Field Consistency**: Warns about old BibTeX conventions (use `journaltitle` instead of `journal` in biblatex)
- **Completeness Checking**: Suggests recommended fields for scholarly completeness (volume, number, pages, publisher, etc.)
- **Crossref Validation**: Verifies that crossref, xdata, and related fields point to existing entries
- **Duplicate Detection**: Finds potential duplicate entries using fuzzy matching on author+title+year

**Character & Formatting:**
- **DOI Validation**: Checks DOI format and verifies that DOIs resolve correctly
- **Unicode Character Detection**: Identifies problematic unicode characters like em-dashes (—), en-dashes (–), smart quotes, and ellipses
- **Ampersand Checking**: Finds unescaped ampersands that should be `\&` in LaTeX
- **Special Character Validation**: Detects improperly formatted special characters (%, _, etc.)
- **Accent Formatting**: Detects unescaped accented characters (é, ñ, ü, etc.) that should be LaTeX-formatted (\'e, \~n, \"u)
- **Name Formatting**: Checks author/editor names for parsing issues, numbers, unusual characters, and inconsistent separators

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd Biblatex_check
```

2. Install required packages using conda (or pip):
```bash
conda install pybtex requests
```

Or with pip:
```bash
pip install pybtex requests
```

### Required Packages
- **pybtex** (>=0.24.0): BibTeX file parsing and writing
- **requests** (>=2.28.0): HTTP requests for Semantic Scholar API and DOI validation

### API Configuration (Optional)

**Crossref Polite Pool (Recommended):**

Crossref offers a "polite pool" with higher rate limits when you identify yourself. Set your email:

```bash
export CROSSREF_MAILTO="your-email@example.com"
```

This gives you access to the polite pool with better performance. The tool already uses 20 requests/sec by default.

**Semantic Scholar API Key (Optional):**

The Semantic Scholar API is used as a fallback. An API key provides better access:

```bash
# Set for current session
export SEMANTIC_SCHOLAR_API_KEY="your-api-key-here"

# Or add to your ~/.bashrc or ~/.zshrc for permanent setup
echo 'export SEMANTIC_SCHOLAR_API_KEY="your-api-key-here"' >> ~/.bashrc
source ~/.bashrc
```

Get a free API key from [Semantic Scholar](https://www.semanticscholar.org/product/api).

## Usage

### Basic Diagnostics (Read-Only)

Run all diagnostics on your BibTeX file without making changes:

```bash
python biblatex_diagnostics.py references.bib
```

### Save Report to File

Save the diagnostic report to a text file instead of printing to terminal:

```bash
python biblatex_diagnostics.py references.bib -r report.txt
```

### Update with API Data

Automatically update entries with Crossref/Semantic Scholar data and save to a new file:

```bash
python biblatex_diagnostics.py references.bib --update-scholar -o corrected.bib
```

This will:
1. Try Crossref first (fast, comprehensive bibliographic data)
2. Fall back to Semantic Scholar if Crossref doesn't find a match
3. Update entries with authoritative data

### Run Specific Diagnostics

```bash
# Only check DOIs and unicode issues (skip API lookups)
python biblatex_diagnostics.py references.bib --no-scholar

# Only check API matches
python biblatex_diagnostics.py references.bib --no-doi --no-unicode --no-ampersand --no-special
```

### Advanced Options

```bash
# Verbose output with custom delay between API queries
python biblatex_diagnostics.py references.bib -v --delay 0.05

# Full help
python biblatex_diagnostics.py --help
```

## Command-Line Arguments

### Required Arguments
- `input_file`: Path to your BibTeX file

### Optional Arguments
- `-o, --output`: Output file for corrected BibTeX
- `-r, --report-file`: Save diagnostic report to file (default: print to terminal)
- `-v, --verbose`: Enable verbose output
- `--delay`: Delay between Crossref API queries in seconds (default: 0.05s for 20 req/sec)

### Diagnostic Control

**Core Validation Checks:**
- `--no-entry-types`: Skip entry type and required fields checking
- `--no-dates`: Skip date/year validity checking
- `--no-identifiers`: Skip ISBN/ISSN/arXiv format checking
- `--no-consistency`: Skip field naming consistency checking
- `--no-completeness`: Skip recommended fields checking
- `--no-crossrefs`: Skip crossref/xdata/related validation
- `--no-duplicates`: Skip duplicate entry detection

**Character & Formatting Checks:**
- `--no-scholar`: Skip API checking (Crossref and Semantic Scholar)
- `--no-doi`: Skip DOI validation
- `--no-unicode`: Skip unicode character checking
- `--no-ampersand`: Skip ampersand checking
- `--no-special`: Skip special character checking
- `--no-accents`: Skip accent formatting checking
- `--no-names`: Skip name formatting checking

### Update Options
- `--update-scholar`: Update entries with API data: Crossref (primary) → Semantic Scholar (fallback) (requires `-o`)

## Examples

### Example 1: Full Diagnostic Run
```bash
python biblatex_diagnostics.py my_references.bib -v
```

This will check all ~700 entries for:
- **Core validation**: Entry types, required fields, date/year validity, ISBN/ISSN/arXiv formats
- **Completeness**: Missing recommended fields, suspiciously bare entries
- **Consistency**: Field naming (journal vs journaltitle), crossref validity
- **Duplicates**: Fuzzy matching to find potential duplicates
- **API Validation**: Cross-reference with Crossref and Semantic Scholar
- **Character issues**: Unicode, accents, unescaped special characters
- **Name formatting**: Author/editor parsing issues, inconsistent separators

### Example 2: Clean and Correct References
```bash
python biblatex_diagnostics.py messy_refs.bib --update-scholar -o clean_refs.bib
```

This will:
- Search Crossref for each entry (fast, 20 req/sec)
- Fall back to Semantic Scholar if Crossref doesn't find a match
- Replace matching entries with authoritative data
- Save the corrected bibliography to `clean_refs.bib`

### Example 3: Quick Unicode Check
```bash
python biblatex_diagnostics.py refs.bib --no-scholar --no-doi --no-ampersand --no-special
```

Quickly check just for unicode issues without API lookups.

### Example 4: Save Report to File
```bash
python biblatex_diagnostics.py references.bib -r diagnostics_report.txt
```

Run all diagnostics and save the warnings and errors to a text file for later review.

### Example 5: Core Validation Only
```bash
python biblatex_diagnostics.py references.bib --no-scholar --no-doi --no-unicode --no-ampersand --no-special --no-accents --no-names
```

Focus on core biblatex validation: entry types, required fields, dates, identifiers, completeness, crossrefs, and duplicates.

### Example 6: Find Duplicates and Broken References
```bash
python biblatex_diagnostics.py references.bib --no-scholar --no-doi --no-unicode --no-ampersand --no-special --no-accents --no-names --no-entry-types --no-dates --no-identifiers --no-consistency --no-completeness
```

Quickly check only for duplicate entries and broken crossrefs without running other validations.

## Output

The tool provides detailed reports including:

- **Issues Found**: Lists all problems detected (invalid DOIs, unicode characters, etc.)
- **Potential Corrections**: Shows entries that match Crossref/Semantic Scholar records
- **Summary Statistics**: Total entries checked, issues found, corrections available

Example output:
```
Running diagnostics on 15 entries...
============================================================

[1/15] Checking: einstein1905
  ✓ Match found on Crossref
  ✓ Valid DOI: 10.1002/andp.19053221004

[2/15] Checking: smith2023ai
  ⚠ Entry smith2023ai: Title mismatch
  ⚠ Field 'title': Contains em-dash ('—')

============================================================
BIBTEX DIAGNOSTICS REPORT
============================================================

Found 2 issues:
  ⚠ Entry smith2023ai: Title mismatch
  ⚠ Entry smith2023ai, field 'title': Contains em-dash ('—')

Found 1 potential corrections:
  ℹ einstein1905: Found matching entry on Crossref

============================================================
```

## How It Works

1. **BibTeX Parsing**: Uses `pybtex` to load and parse your bibliography
2. **Crossref Integration (Primary)**: Uses the Crossref API to query bibliographic data by title (20 req/sec)
3. **Semantic Scholar Integration (Fallback)**: Falls back to Semantic Scholar API when Crossref doesn't find a match
4. **Title Matching**: Implements fuzzy matching (Jaccard similarity) to handle title variations
5. **Data Validation**: Checks DOIs via HTTP requests, detects unicode patterns, validates LaTeX escaping
6. **Ground Truth Replacement**: When matches are found, replaces entire entries with API data
7. **Rate Limiting**: Automatically handles API rate limits (429 errors) with exponential backoff

## Tips for Best Results

- **Crossref Polite Pool**: Set `CROSSREF_MAILTO` environment variable with your email for better service
- **Fast Processing**: Crossref allows 20 requests/sec, so large files process quickly (default 0.05s delay)
- **Network Issues**: The tool requires internet access for API calls and DOI validation
- **Large Files**: With Crossref, 700+ entries can be processed in ~35 seconds (vs minutes with other APIs)
- **Backup First**: Always keep a backup of your original .bib file before using `--update-scholar`

## Troubleshooting

**API rate limiting issues?**
- Crossref: The tool uses 0.05s delay (20 req/sec) by default, which is within limits
- Semantic Scholar (fallback): Automatically retries with exponential backoff (2s, 4s, 8s)
- Adjust delay if needed: `--delay 0.1` for slower Crossref queries

**"Title mismatch" warnings?**
- The tool uses fuzzy matching, but may still miss some matches
- Manually review these entries
- Adjust the similarity threshold in `_titles_match()` if needed

**Dependencies not installing?**
- Ensure you're using Python 3.7+
- Try: `pip install --upgrade pip` then reinstall requirements

## Contributing

Feel free to submit issues or pull requests for additional features or improvements.

## License

This project is provided as-is for cleaning up and correcting BibTeX files.
