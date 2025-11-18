#!/usr/bin/env python3
"""
BibTeX Formatting Cleaner
Local formatting validation and fixing for BibTeX files (no API calls).
"""

import re
import sys
import argparse
from typing import Dict, List, Tuple, Optional, Set
from datetime import datetime
from difflib import SequenceMatcher
from pybtex.database import parse_file, BibliographyData, Entry
from pybtex.database.output.bibtex import Writer


# Biblatex entry type specifications
BIBLATEX_ENTRY_TYPES = {
    'article': {
        'required': ['author', 'title', 'journaltitle', 'year'],
        'optional': ['volume', 'number', 'pages', 'doi', 'issn', 'url']
    },
    'book': {
        'required': ['author', 'title', 'year'],
        'optional': ['publisher', 'location', 'isbn', 'edition', 'pages']
    },
    'inproceedings': {
        'required': ['author', 'title', 'booktitle', 'year'],
        'optional': ['editor', 'pages', 'publisher', 'location', 'doi']
    },
    'incollection': {
        'required': ['author', 'title', 'booktitle', 'year'],
        'optional': ['editor', 'pages', 'publisher', 'chapter']
    },
    'phdthesis': {
        'required': ['author', 'title', 'school', 'year'],
        'optional': ['address', 'month', 'url']
    },
    'mastersthesis': {
        'required': ['author', 'title', 'school', 'year'],
        'optional': ['address', 'month', 'url']
    },
    'techreport': {
        'required': ['author', 'title', 'institution', 'year'],
        'optional': ['number', 'address', 'month']
    },
    'misc': {
        'required': [],
        'optional': ['author', 'title', 'year', 'howpublished', 'note']
    },
    'online': {
        'required': ['title', 'url', 'year'],
        'optional': ['author', 'urldate', 'organization']
    },
}

# Recommended fields for completeness
RECOMMENDED_FIELDS = {
    'article': ['volume', 'number', 'pages', 'doi'],
    'book': ['publisher', 'location', 'isbn'],
    'inproceedings': ['pages', 'publisher', 'doi'],
}


class BibTeXCleaner:
    """Local formatting validator for BibTeX files."""

    def __init__(self, verbose: bool = False):
        """Initialize the cleaner."""
        self.verbose = verbose
        self.issues = []
        self.warnings = []

    def log(self, message: str):
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(f"[INFO] {message}")

    def load_bibtex(self, filepath: str) -> BibliographyData:
        """Load a BibTeX file."""
        self.log(f"Loading BibTeX file: {filepath}")

        try:
            bib_data = parse_file(filepath)
            self.log(f"Loaded {len(bib_data.entries)} entries")
            return bib_data
        except Exception as e:
            error_msg = str(e)
            print(f"\n{'='*60}")
            print("ERROR: Failed to parse BibTeX file")
            print(f"{'='*60}")
            print(f"\n{error_msg}\n")

            # Check for common issues
            if "repeated bibliography entry" in error_msg.lower():
                print("This means you have duplicate citation keys in your .bib file.")
                print("Each entry must have a unique key.\n")
            elif "expected ," in error_msg.lower() or "unexpected" in error_msg.lower():
                print("This indicates a syntax error in your .bib file.")
                print("Common issues: missing commas, missing braces, or invalid characters.\n")

            print("SUGGESTION: Fix syntax errors FIRST using the syntax checker:")
            print(f"  python3 biblatex_syntax_checker.py {filepath}\n")

            print("The syntax checker will identify ALL syntax issues that prevent")
            print("parsing. After fixing those, run this tool again for detailed")
            print("formatting and semantic validation.\n")
            print(f"{'='*60}")
            raise

    def save_bibtex(self, bib_data: BibliographyData, filepath: str):
        """Save BibTeX database to file."""
        writer = Writer()
        writer.write_file(bib_data, filepath)
        self.log(f"Saved to: {filepath}")

    # ===== Character and Formatting Checks =====

    def check_unicode_issues(self, key: str, entry: Entry):
        """Check for problematic unicode characters."""
        problematic_chars = {
            '—': 'em-dash (use ---)',
            '–': 'en-dash (use --)',
            ''': 'smart quote (use \')',
            ''': 'smart quote (use \')',
            '"': 'smart quote (use ``)',
            '"': 'smart quote (use \'\')',
            '…': 'ellipsis (use ...)',
        }

        for field, value in entry.fields.items():
            value_str = str(value)
            for char, desc in problematic_chars.items():
                if char in value_str:
                    self.issues.append(
                        f"Entry {key}, field '{field}': Contains {desc} ('{char}')"
                    )

    def check_unescaped_ampersand(self, key: str, entry: Entry):
        """Check for unescaped ampersands."""
        for field, value in entry.fields.items():
            value_str = str(value)
            if re.search(r'(?<!\\)&', value_str):
                self.issues.append(
                    f"Entry {key}, field '{field}': Contains unescaped ampersand (use \\&)"
                )

    def check_special_characters(self, key: str, entry: Entry):
        """Check for improperly formatted special characters."""
        for field, value in entry.fields.items():
            value_str = str(value)

            # Check for unescaped underscores (except in URLs)
            if '_' in value_str and field not in ['url', 'doi', 'eprint', 'file']:
                if re.search(r'(?<!\\)_', value_str):
                    self.issues.append(
                        f"Entry {key}, field '{field}': May contain unescaped underscore (use \\_)"
                    )

            # Check for unescaped percent signs
            if re.search(r'(?<!\\)%', value_str):
                self.issues.append(
                    f"Entry {key}, field '{field}': Contains unescaped percent sign (use \\%)"
                )

    def check_accent_formatting(self, key: str, entry: Entry):
        """Check for unescaped accented characters."""
        accent_chars = {
            'á': r"\'a", 'à': r"\`a", 'ä': r'\"a', 'â': r"\^a", 'ã': r"\~a",
            'Á': r"\'A", 'À': r"\`A", 'Ä': r'\"A', 'Â': r"\^A", 'Ã': r"\~A",
            'é': r"\'e", 'è': r"\`e", 'ë': r'\"e', 'ê': r"\^e",
            'É': r"\'E", 'È': r"\`E", 'Ë': r'\"E', 'Ê': r"\^E",
            'í': r"\'i", 'ì': r"\`i", 'ï': r'\"i', 'î': r"\^i",
            'Í': r"\'I", 'Ì': r"\`I", 'Ï': r'\"I', 'Î': r"\^I",
            'ó': r"\'o", 'ò': r"\`o", 'ö': r'\"o', 'ô': r"\^o", 'õ': r"\~o",
            'Ó': r"\'O", 'Ò': r"\`O", 'Ö': r'\"O', 'Ô': r"\^O", 'Õ': r"\~O",
            'ú': r"\'u", 'ù': r"\`u", 'ü': r'\"u', 'û': r"\^u",
            'Ú': r"\'U", 'Ù': r"\`U", 'Ü': r'\"U', 'Û': r"\^U",
            'ñ': r"\~n", 'Ñ': r"\~N",
            'ç': r"\c{c}", 'Ç': r"\c{C}",
            'ß': r"\ss",
        }

        for field, value in entry.fields.items():
            value_str = str(value)
            found_chars = []

            for char, latex_form in accent_chars.items():
                if char in value_str:
                    found_chars.append(f"{char} (should be {latex_form})")

            if found_chars:
                chars_str = ", ".join(found_chars)
                self.issues.append(
                    f"Entry {key}, field '{field}': Unescaped accents: {chars_str}"
                )

    def check_name_formatting(self, key: str, entry: Entry):
        """Check for name formatting issues."""
        for role in ['author', 'editor']:
            if role in entry.persons:
                persons = entry.persons[role]

                for idx, person in enumerate(persons, 1):
                    person_str = str(person)

                    # Single-word names (potential parsing issue)
                    if ' ' not in person_str.strip() and ',' not in person_str.strip():
                        self.warnings.append(
                            f"Entry {key}, {role} #{idx} '{person_str}': Single-word name (check parsing)"
                        )

                    # Numbers in names
                    if re.search(r'\d', person_str):
                        self.issues.append(
                            f"Entry {key}, {role} #{idx} '{person_str}': Contains numbers"
                        )

                    # Unusual characters
                    if re.search(r'[^\w\s,.\-\'`]', person_str):
                        self.warnings.append(
                            f"Entry {key}, {role} #{idx} '{person_str}': Contains unusual characters"
                        )

    # ===== Entry Type and Field Validation =====

    def check_entry_type_fields(self, key: str, entry: Entry):
        """Check required fields for entry type."""
        entry_type = entry.type.lower()

        if entry_type not in BIBLATEX_ENTRY_TYPES:
            self.warnings.append(
                f"Entry {key}: Unknown entry type '@{entry_type}'"
            )
            return

        spec = BIBLATEX_ENTRY_TYPES[entry_type]
        required = spec.get('required', [])

        # Check for missing required fields
        missing = []
        for field in required:
            if field not in entry.fields and field not in entry.persons:
                missing.append(field)

        if missing:
            self.issues.append(
                f"Entry {key} (@{entry_type}): Missing required fields: {', '.join(missing)}"
            )

    def check_date_validity(self, key: str, entry: Entry):
        """Check date and year validity."""
        # Check year
        if 'year' in entry.fields:
            year_str = entry.fields['year']
            try:
                year = int(year_str)
                current_year = datetime.now().year

                if year < 1000:
                    self.issues.append(f"Entry {key}: Year '{year}' seems too old")
                elif year > current_year + 5:
                    self.issues.append(f"Entry {key}: Future year '{year}' (>5 years ahead)")
            except ValueError:
                self.issues.append(f"Entry {key}: Invalid year format '{year_str}'")

        # Check date field
        if 'date' in entry.fields:
            date_str = entry.fields['date']

            # Check for valid ISO date format
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
                self.warnings.append(f"Entry {key}: Date '{date_str}' not in ISO format (YYYY-MM-DD)")

            # Check month validity
            if re.match(r'^\d{4}-(\d{2})', date_str):
                month_match = re.match(r'^\d{4}-(\d{2})', date_str)
                month = int(month_match.group(1))
                if month < 1 or month > 12:
                    self.issues.append(f"Entry {key}: Invalid month '{month}' in date")

        # Check month field
        if 'month' in entry.fields:
            month_str = entry.fields['month']
            try:
                month = int(month_str)
                if month < 1 or month > 12:
                    self.issues.append(f"Entry {key}: Invalid month number '{month}'")
            except ValueError:
                pass  # Month names are OK

    def check_identifier_formats(self, key: str, entry: Entry):
        """Check ISBN, ISSN, arXiv, DOI formats."""
        # Check DOI
        if 'doi' in entry.fields:
            doi = entry.fields['doi']
            # Check for placeholder values
            if doi.lower() in ['tba', 'todo', '???', 'unknown', 'pending']:
                self.issues.append(f"Entry {key}: Placeholder value in doi: '{doi}'")
            # Check DOI format
            elif not re.match(r'^10\.\d{4,}/\S+$', doi):
                self.issues.append(f"Entry {key}: Invalid DOI format '{doi}'")

        # Check ISBN
        if 'isbn' in entry.fields:
            isbn = entry.fields['isbn'].replace('-', '').replace(' ', '')
            if len(isbn) not in [10, 13]:
                self.issues.append(f"Entry {key}: Invalid ISBN length '{entry.fields['isbn']}'")

        # Check ISSN
        if 'issn' in entry.fields:
            issn = entry.fields['issn']
            if not re.match(r'^\d{4}-\d{3}[\dX]$', issn):
                self.issues.append(f"Entry {key}: Invalid ISSN format '{issn}' (should be XXXX-XXXX)")

        # Check arXiv
        if 'eprint' in entry.fields and entry.fields.get('eprinttype') == 'arxiv':
            arxiv = entry.fields['eprint']
            # New format: YYMM.NNNNN or old format: arch-ive/YYMMNNN
            if not re.match(r'^\d{4}\.\d{4,5}$', arxiv) and not re.match(r'^[a-z-]+/\d{7}$', arxiv):
                self.issues.append(f"Entry {key}: Invalid arXiv ID format '{arxiv}'")

        # Check for placeholder values in URL
        if 'url' in entry.fields:
            url = entry.fields['url']
            if url.lower() in ['tba', 'todo', '???', 'unknown', 'pending']:
                self.issues.append(f"Entry {key}: Placeholder value in url: '{url}'")

    def check_field_consistency(self, key: str, entry: Entry):
        """Check field naming consistency."""
        # BibLaTeX uses 'journaltitle', not 'journal'
        if 'journal' in entry.fields:
            self.warnings.append(
                f"Entry {key}: Use 'journaltitle' instead of 'journal' in biblatex"
            )

    def check_completeness(self, key: str, entry: Entry):
        """Check for recommended fields."""
        entry_type = entry.type.lower()

        if entry_type in RECOMMENDED_FIELDS:
            recommended = RECOMMENDED_FIELDS[entry_type]
            missing = [f for f in recommended if f not in entry.fields]

            if missing:
                self.warnings.append(
                    f"Entry {key} (@{entry_type}): Missing recommended fields: {', '.join(missing)}"
                )

        # Check for suspiciously bare entries
        total_fields = len(entry.fields) + sum(len(p) for p in entry.persons.values())
        if total_fields < 4:
            self.warnings.append(
                f"Entry {key}: Suspiciously bare entry (only {total_fields} fields)"
            )

    def check_crossrefs(self, bib_data: BibliographyData):
        """Check crossref/xdata/related validity."""
        all_keys = set(bib_data.entries.keys())

        for key, entry in bib_data.entries.items():
            # Check crossref
            if 'crossref' in entry.fields:
                ref_key = entry.fields['crossref']
                if ref_key not in all_keys:
                    self.issues.append(
                        f"Entry {key}: Broken crossref to '{ref_key}' (entry does not exist)"
                    )

            # Check xdata
            if 'xdata' in entry.fields:
                xdata_keys = entry.fields['xdata'].split(',')
                for xdata_key in xdata_keys:
                    xdata_key = xdata_key.strip()
                    if xdata_key not in all_keys:
                        self.issues.append(
                            f"Entry {key}: Broken xdata to '{xdata_key}' (entry does not exist)"
                        )

            # Check related
            if 'related' in entry.fields:
                related_keys = entry.fields['related'].split(',')
                for rel_key in related_keys:
                    rel_key = rel_key.strip()
                    if rel_key not in all_keys:
                        self.warnings.append(
                            f"Entry {key}: Broken related to '{rel_key}' (entry does not exist)"
                        )

    def find_duplicates(self, bib_data: BibliographyData, threshold: float = 0.8) -> List[Tuple[str, str, float]]:
        """Find potential duplicate entries."""
        duplicates = []
        entries_list = list(bib_data.entries.items())

        for i, (key1, entry1) in enumerate(entries_list):
            for key2, entry2 in entries_list[i + 1:]:
                # Compare titles
                title1 = entry1.fields.get('title', '').lower()
                title2 = entry2.fields.get('title', '').lower()

                if not title1 or not title2:
                    continue

                # Calculate similarity
                similarity = SequenceMatcher(None, title1, title2).ratio()

                if similarity >= threshold:
                    # Check authors too
                    authors1 = set(str(p) for p in entry1.persons.get('author', []))
                    authors2 = set(str(p) for p in entry2.persons.get('author', []))

                    # If titles are very similar, it's likely a duplicate
                    if similarity >= 0.9 or (authors1 and authors2 and authors1 == authors2):
                        duplicates.append((key1, key2, similarity))

        for key1, key2, sim in duplicates:
            self.warnings.append(
                f"Possible duplicate: '{key1}' and '{key2}' ({int(sim*100)}% similar)"
            )

        return duplicates

    # ===== Main Validation =====

    def validate_all(self, bib_data: BibliographyData,
                     check_unicode: bool = True,
                     check_ampersand: bool = True,
                     check_special: bool = True,
                     check_accents: bool = True,
                     check_names: bool = True,
                     check_entry_types: bool = True,
                     check_dates: bool = True,
                     check_identifiers: bool = True,
                     check_consistency: bool = True,
                     check_completeness: bool = True,
                     check_crossrefs_flag: bool = True,
                     check_duplicates: bool = True):
        """Run all validation checks."""
        total = len(bib_data.entries)
        print(f"\nValidating {total} entries (local checks only, no API calls)...")
        print("=" * 60)

        # Per-entry checks
        for idx, (key, entry) in enumerate(bib_data.entries.items(), 1):
            print(f"\n[{idx}/{total}] Checking: {key}")

            if check_unicode:
                self.check_unicode_issues(key, entry)
            if check_ampersand:
                self.check_unescaped_ampersand(key, entry)
            if check_special:
                self.check_special_characters(key, entry)
            if check_accents:
                self.check_accent_formatting(key, entry)
            if check_names:
                self.check_name_formatting(key, entry)
            if check_entry_types:
                self.check_entry_type_fields(key, entry)
            if check_dates:
                self.check_date_validity(key, entry)
            if check_identifiers:
                self.check_identifier_formats(key, entry)
            if check_consistency:
                self.check_field_consistency(key, entry)
            if check_completeness:
                self.check_completeness(key, entry)

        # Database-wide checks
        if check_crossrefs_flag:
            self.check_crossrefs(bib_data)
        if check_duplicates:
            self.find_duplicates(bib_data)

    def generate_report(self) -> str:
        """Generate validation report."""
        report = []
        report.append("\n" + "=" * 60)
        report.append("BIBTEX FORMATTING REPORT")
        report.append("=" * 60)

        if self.issues:
            report.append(f"\nIssues Found: {len(self.issues)}")
            for issue in self.issues:
                report.append(f"  ✗ {issue}")

        if self.warnings:
            report.append(f"\nWarnings: {len(self.warnings)}")
            for warning in self.warnings:
                report.append(f"  ⚠ {warning}")

        if not self.issues and not self.warnings:
            report.append("\n✓ No issues found!")

        report.append("\n" + "=" * 60)
        return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(
        description='BibTeX Formatting Cleaner - Local validation without API calls',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate all formatting
  python biblatex_cleaner.py input.bib

  # Save report to file
  python biblatex_cleaner.py input.bib -r report.txt

  # Skip specific checks
  python biblatex_cleaner.py input.bib --no-duplicates --no-completeness
        """
    )

    parser.add_argument('input_file', help='Input BibTeX file')
    parser.add_argument('-r', '--report-file', help='Save report to file')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    # Diagnostic options
    parser.add_argument('--no-unicode', action='store_true', help='Skip unicode checking')
    parser.add_argument('--no-ampersand', action='store_true', help='Skip ampersand checking')
    parser.add_argument('--no-special', action='store_true', help='Skip special character checking')
    parser.add_argument('--no-accents', action='store_true', help='Skip accent checking')
    parser.add_argument('--no-names', action='store_true', help='Skip name formatting checking')
    parser.add_argument('--no-entry-types', action='store_true', help='Skip entry type validation')
    parser.add_argument('--no-dates', action='store_true', help='Skip date validation')
    parser.add_argument('--no-identifiers', action='store_true', help='Skip identifier validation')
    parser.add_argument('--no-consistency', action='store_true', help='Skip field consistency')
    parser.add_argument('--no-completeness', action='store_true', help='Skip completeness checking')
    parser.add_argument('--no-crossrefs', action='store_true', help='Skip crossref validation')
    parser.add_argument('--no-duplicates', action='store_true', help='Skip duplicate detection')

    args = parser.parse_args()

    # Initialize cleaner
    cleaner = BibTeXCleaner(verbose=args.verbose)

    try:
        # Load BibTeX file
        bib_data = cleaner.load_bibtex(args.input_file)

        # Run validation
        cleaner.validate_all(
            bib_data,
            check_unicode=not args.no_unicode,
            check_ampersand=not args.no_ampersand,
            check_special=not args.no_special,
            check_accents=not args.no_accents,
            check_names=not args.no_names,
            check_entry_types=not args.no_entry_types,
            check_dates=not args.no_dates,
            check_identifiers=not args.no_identifiers,
            check_consistency=not args.no_consistency,
            check_completeness=not args.no_completeness,
            check_crossrefs_flag=not args.no_crossrefs,
            check_duplicates=not args.no_duplicates
        )

        # Generate report
        report = cleaner.generate_report()
        if args.report_file:
            with open(args.report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\n✓ Report saved to: {args.report_file}")
        else:
            print(report)

    except FileNotFoundError:
        print(f"Error: File '{args.input_file}' not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
