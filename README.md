# BibTeX Diagnostic Tool

A comprehensive Python tool for validating and correcting BibTeX/BibLaTeX files using Google Scholar as the ground truth. Perfect for cleaning up bibliographies with hallucinated or incorrect references from LLMs.

## Features

### Main Feature: Google Scholar Validation
- **Cross-reference with Google Scholar**: Automatically checks each entry's title against Google Scholar
- **Ground Truth Replacement**: If a matching title is found on Google Scholar, pulls the authoritative BibTeX entry
- **Smart Title Matching**: Uses fuzzy matching to handle variations in punctuation and formatting
- **Rate-Limited Queries**: Respects Google Scholar's rate limits with configurable delays

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
conda install pybtex scholarly requests
```

Or with pip:
```bash
pip install pybtex scholarly requests
```

### Required Packages
- **pybtex** (>=0.24.0): BibTeX file parsing and writing
- **scholarly** (>=1.7.0): Google Scholar integration
- **requests** (>=2.28.0): HTTP requests for DOI validation

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

### Update with Google Scholar Data

Automatically update entries with Google Scholar data and save to a new file:

```bash
python biblatex_diagnostics.py references.bib --update-scholar -o corrected.bib
```

### Run Specific Diagnostics

```bash
# Only check DOIs and unicode issues (skip Google Scholar)
python biblatex_diagnostics.py references.bib --no-scholar

# Only check Google Scholar matches
python biblatex_diagnostics.py references.bib --no-doi --no-unicode --no-ampersand --no-special
```

### Advanced Options

```bash
# Verbose output with custom delay between Google Scholar queries
python biblatex_diagnostics.py references.bib -v --delay 3.0

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
- `--delay`: Delay between Google Scholar queries in seconds (default: 5.0)

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
- `--no-scholar`: Skip Google Scholar checking
- `--no-doi`: Skip DOI validation
- `--no-unicode`: Skip unicode character checking
- `--no-ampersand`: Skip ampersand checking
- `--no-special`: Skip special character checking
- `--no-accents`: Skip accent formatting checking
- `--no-names`: Skip name formatting checking

### Update Options
- `--update-scholar`: Update entries with Google Scholar data (requires `-o`)

## Examples

### Example 1: Full Diagnostic Run
```bash
python biblatex_diagnostics.py my_references.bib -v
```

This will check all entries for:
- **Core validation**: Entry types, required fields, date/year validity, ISBN/ISSN/arXiv formats
- **Completeness**: Missing recommended fields, suspiciously bare entries
- **Consistency**: Field naming (journal vs journaltitle), crossref validity
- **Duplicates**: Fuzzy matching to find potential duplicates
- **Google Scholar**: Cross-reference with authoritative sources
- **Character issues**: Unicode, accents, unescaped special characters
- **Name formatting**: Author/editor parsing issues, inconsistent separators

### Example 2: Clean and Correct References
```bash
python biblatex_diagnostics.py messy_refs.bib --update-scholar -o clean_refs.bib --delay 7.0
```

This will:
- Search Google Scholar for each entry
- Replace matching entries with Google Scholar's authoritative data
- Use a 7-second delay between queries to avoid rate limiting
- Save the corrected bibliography to `clean_refs.bib`

### Example 3: Quick Unicode Check
```bash
python biblatex_diagnostics.py refs.bib --no-scholar --no-doi --no-ampersand --no-special
```

Quickly check just for unicode issues without hitting Google Scholar.

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
- **Potential Corrections**: Shows entries that match Google Scholar records
- **Summary Statistics**: Total entries checked, issues found, corrections available

Example output:
```
Running diagnostics on 15 entries...
============================================================

[1/15] Checking: einstein1905
  ✓ Match found on Google Scholar
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
  ℹ einstein1905: Found matching entry on Google Scholar

============================================================
```

## How It Works

1. **BibTeX Parsing**: Uses `bibtexparser` to load and parse your bibliography
2. **Google Scholar Integration**: Uses the `scholarly` package to query Google Scholar by title
3. **Title Matching**: Implements fuzzy matching (Jaccard similarity) to handle title variations
4. **Data Validation**: Checks DOIs via HTTP requests, detects unicode patterns, validates LaTeX escaping
5. **Ground Truth Replacement**: When matches are found, replaces entire entries with Google Scholar data

## Tips for Best Results

- **Rate Limiting**: Google Scholar may block rapid queries. Increase `--delay` if you encounter issues (try 10+ seconds)
- **Network Issues**: The tool requires internet access for Google Scholar and DOI validation
- **Large Files**: For 700+ entries, expect the full run to take significant time due to rate limiting
- **Backup First**: Always keep a backup of your original .bib file before using `--update-scholar`

## Troubleshooting

**Google Scholar blocking requests?**
- Increase the delay: `--delay 10.0` or higher
- Run diagnostics in smaller batches
- Consider using a proxy (modify the scholarly configuration in the code)

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
