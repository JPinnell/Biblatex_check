#!/usr/bin/env python3
"""
BibTeX Formatting Cleaner
Local formatting validation and fixing for BibTeX files (no API calls).
"""

import re
import sys
import os
import argparse
from typing import Dict, List, Tuple, Optional, Set
from datetime import datetime
from difflib import SequenceMatcher
from pybtex.database import parse_file, BibliographyData, Entry
from pybtex.database.output.bibtex import Writer


def clean_filepath(filepath: str) -> str:
    """
    Clean file path by removing surrounding quotes and whitespace.
    Also handles paths with double backslashes if they are passed as literal strings.
    """
    if not filepath:
        return filepath

    # Strip whitespace
    cleaned = filepath.strip()

    # Strip surrounding quotes (single or double)
    if (cleaned.startswith('"') and cleaned.endswith('"')) or \
       (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1]

    # Strip whitespace again in case quotes were around whitespace
    cleaned = cleaned.strip()

    return cleaned


# Entry type specifications (accepts both BibTeX and BibLaTeX field names)
# Format: 'field_name' or ['field1', 'field2'] for alternatives (either is acceptable)
ENTRY_TYPES = {
    'article': {
        'required': [
            'author',
            'title',
            ['journal', 'journaltitle'],  # BibTeX uses 'journal', BibLaTeX uses 'journaltitle'
            ['year', 'date']              # BibTeX uses 'year', BibLaTeX uses 'date'
        ],
        'optional': ['volume', 'number', 'pages', 'doi', 'issn', 'url']
    },
    'book': {
        'required': [
            'author',
            'title',
            ['year', 'date']
        ],
        'optional': ['publisher', 'location', 'isbn', 'edition', 'pages']
    },
    'inproceedings': {
        'required': [
            'author',
            'title',
            'booktitle',
            ['year', 'date']
        ],
        'optional': ['editor', 'pages', 'publisher', 'location', 'doi']
    },
    'incollection': {
        'required': [
            'author',
            'title',
            'booktitle',
            ['year', 'date']
        ],
        'optional': ['editor', 'pages', 'publisher', 'chapter']
    },
    'phdthesis': {
        'required': [
            'author',
            'title',
            ['school', 'institution'],  # Both 'school' and 'institution' are acceptable
            ['year', 'date']
        ],
        'optional': ['address', 'month', 'url']
    },
    'mastersthesis': {
        'required': [
            'author',
            'title',
            'school',
            ['year', 'date']
        ],
        'optional': ['address', 'month', 'url']
    },
    'techreport': {
        'required': [
            'author',
            'title',
            'institution',
            ['year', 'date']
        ],
        'optional': ['number', 'address', 'month']
    },
    'misc': {
        'required': [],
        'optional': ['author', 'title', ['year', 'date'], 'howpublished', 'note']
    },
    'online': {
        'required': [
            'title',
            'url',
            ['year', 'date']
        ],
        'optional': ['author', 'urldate', 'organization']
    },
}

# Field name mappings: BibTeX -> BibLaTeX
BIBTEX_TO_BIBLATEX = {
    'journal': 'journaltitle',
    'year': 'date',
    'address': 'location',
    'number': 'issue',
}

# Field name mappings: BibLaTeX -> BibTeX
BIBLATEX_TO_BIBTEX = {v: k for k, v in BIBTEX_TO_BIBLATEX.items()}

# Known valid BibTeX/BibLaTeX field names (for detecting typos/forbidden fields)
KNOWN_FIELDS = {
    # Standard fields (both BibTeX and BibLaTeX)
    'author', 'title', 'year', 'month', 'day',
    'editor', 'publisher', 'organization', 'institution', 'school',
    'volume', 'number', 'pages', 'chapter', 'edition',
    'series', 'type', 'note', 'howpublished',
    'booktitle', 'address', 'url', 'urldate',

    # BibTeX-specific
    'journal',

    # BibLaTeX-specific
    'journaltitle', 'date', 'location', 'maintitle', 'mainsubtitle',
    'subtitle', 'titleaddon', 'language', 'origlanguage',
    'eventtitle', 'eventdate', 'venue', 'issue',

    # Identifiers
    'doi', 'eprint', 'eprinttype', 'eprintclass',
    'isbn', 'issn', 'isrn', 'isan', 'ismn', 'isrc', 'iswc',

    # Online/URLs
    'eid', 'url', 'urldate',

    # Cross-references
    'crossref', 'xref', 'xdata', 'related', 'relatedtype', 'relatedstring',

    # Pagination
    'pagination', 'bookpagination',

    # Misc
    'abstract', 'annotation', 'keywords', 'file', 'library',
    'addendum', 'pubstate', 'version',

    # Metadata (reference managers like Zotero, Mendeley, etc.)
    'owner', 'timestamp', 'date-added', 'date-modified', 'copyright',

    # Special
    'entryset', 'execute', 'gender', 'hyphenation', 'indextitle',
    'indexsorttitle', 'label', 'nameaddon', 'options', 'presort',
    'shortauthor', 'shorteditor', 'shorthand', 'shorthandintro',
    'shortjournal', 'shortseries', 'shorttitle', 'sortkey', 'sortname',
    'sortshorthand', 'sorttitle', 'sortyear', 'usera', 'userb', 'userc',
    'userd', 'usere', 'userf', 'verba', 'verbb', 'verbc',
}

# Recommended fields for completeness (can use same alternative format as required fields)
RECOMMENDED_FIELDS = {
    'article': ['volume', 'pages', 'doi'],
    'book': [['publisher'], ['location', 'address'], 'isbn'],    # BibTeX uses 'address', BibLaTeX uses 'location'
    'inproceedings': ['pages', ['publisher'], 'doi'],
}


class BibTeXCleaner:
    """Local formatting validator for BibTeX files."""

    def __init__(self, verbose: bool = False):
        """Initialize the cleaner."""
        self.verbose = verbose
        self.issues = []
        self.warnings = []
        self.removed_duplicates = []  # Track removed duplicate fields

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

            # Remove LaTeX accent commands to avoid false positives
            # This prevents flagging things like {\"a} or {\'e} as smart quotes
            cleaned_value = value_str
            # Remove common LaTeX accent patterns: {\cmd{char}}, {\cmd char}, \cmd{char}, \cmd char
            cleaned_value = re.sub(r'\{\\[`\'^"~=.uvHckr]\{?[a-zA-Z]\}?\}', '', cleaned_value)
            cleaned_value = re.sub(r'\\[`\'^"~=.uvHckr]\{?[a-zA-Z]\}?', '', cleaned_value)

            for char, desc in problematic_chars.items():
                if char in cleaned_value:
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

                # Check for "and others" with too few authors (likely hallucination)
                # Count real authors (excluding "others")
                real_author_count = sum(1 for p in persons if str(p).lower() != 'others')
                has_others = any(str(p).lower() == 'others' for p in persons)

                if has_others and real_author_count < 5:
                    self.warnings.append(
                        f"Entry {key}: Found 'and others' with only {real_author_count} real {role}(s) - possible hallucination"
                    )

                for idx, person in enumerate(persons, 1):
                    person_str = str(person)

                    # Single-word names (potential parsing issue)
                    # Exception: "others" is valid in BibTeX/BibLaTeX for "et al."
                    if ' ' not in person_str.strip() and ',' not in person_str.strip():
                        if person_str.lower() != 'others':
                            self.warnings.append(
                                f"Entry {key}, {role} #{idx} '{person_str}': Single-word name (check parsing)"
                            )

                    # Numbers in names
                    if re.search(r'\d', person_str):
                        self.issues.append(
                            f"Entry {key}, {role} #{idx} '{person_str}': Contains numbers"
                        )

                    # Unusual characters (but allow LaTeX commands)
                    # Remove LaTeX commands first: {\' ...}, {\^ ...}, {\` ...}, etc.
                    cleaned_name = re.sub(r'\{\\[`\'^"~=.]\{?[a-zA-Z]\}?\}', '', person_str)
                    # Also remove other common LaTeX patterns
                    cleaned_name = re.sub(r'\{\\[a-zA-Z]+\{[a-zA-Z]\}\}', '', cleaned_name)

                    # Now check for unusual characters (allow LaTeX special chars: {}\)
                    if re.search(r'[^\w\s,.\-\'`{}\\]', cleaned_name):
                        self.warnings.append(
                            f"Entry {key}, {role} #{idx} '{person_str}': Contains unusual characters"
                        )

    # ===== Entry Type and Field Validation =====

    def check_entry_type_fields(self, key: str, entry: Entry):
        """Check required fields for entry type (accepts both BibTeX and BibLaTeX field names)."""
        entry_type = entry.type.lower()

        if entry_type not in ENTRY_TYPES:
            self.warnings.append(
                f"Entry {key}: Unknown entry type '@{entry_type}'"
            )
            return

        spec = ENTRY_TYPES[entry_type]
        required = spec.get('required', [])

        # Check for missing required fields
        # Fields can be strings (exact match) or lists (any alternative is acceptable)
        missing = []
        for field_spec in required:
            if isinstance(field_spec, list):
                # Alternative fields - at least one must be present
                alternatives = field_spec
                if not any(alt in entry.fields or alt in entry.persons for alt in alternatives):
                    missing.append(' OR '.join(alternatives))
            else:
                # Single required field
                if field_spec not in entry.fields and field_spec not in entry.persons:
                    missing.append(field_spec)

        if missing:
            self.issues.append(
                f"Entry {key} (@{entry_type}): Missing required fields: {', '.join(missing)}"
            )

    def check_unknown_fields(self, key: str, entry: Entry):
        """Check for unknown/forbidden field names (likely typos)."""
        for field_name in entry.fields.keys():
            if field_name.lower() not in KNOWN_FIELDS:
                # Check if it's a close typo of a known field
                suggestions = []
                field_lower = field_name.lower()

                # Check for common typos
                if 'journal' in field_lower:
                    suggestions.append('journal or journaltitle')
                elif 'title' in field_lower:
                    suggestions.append('title or journaltitle')
                elif 'addr' in field_lower or 'loc' in field_lower:
                    suggestions.append('address or location')

                suggestion_text = f" (did you mean: {', '.join(suggestions)}?)" if suggestions else ""
                self.issues.append(
                    f"Entry {key}: Unknown field '{field_name}'{suggestion_text}"
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

            # Check for valid date formats: YYYY, YYYY-MM, or YYYY-MM-DD
            if re.match(r'^\d{4}$', date_str):
                # Year only - valid, check range
                try:
                    year = int(date_str)
                    current_year = datetime.now().year
                    if year < 1000:
                        self.issues.append(f"Entry {key}: Year '{year}' in date field seems too old")
                    elif year > current_year + 5:
                        self.issues.append(f"Entry {key}: Future year '{year}' in date field (>5 years ahead)")
                except ValueError:
                    pass
            elif re.match(r'^\d{4}-\d{2}$', date_str):
                # Year-month - valid, check month validity
                month_match = re.match(r'^\d{4}-(\d{2})$', date_str)
                if month_match:
                    month = int(month_match.group(1))
                    if month < 1 or month > 12:
                        self.issues.append(f"Entry {key}: Invalid month '{month}' in date")
            elif re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
                # Full ISO date - valid, check month validity
                month_match = re.match(r'^\d{4}-(\d{2})-\d{2}$', date_str)
                if month_match:
                    month = int(month_match.group(1))
                    if month < 1 or month > 12:
                        self.issues.append(f"Entry {key}: Invalid month '{month}' in date")
            else:
                # Invalid format
                self.warnings.append(f"Entry {key}: Date '{date_str}' not in valid format (use YYYY, YYYY-MM, or YYYY-MM-DD)")

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

    def check_page_format(self, key: str, entry: Entry):
        """
        Check page range format.
        Single page numbers (e.g., '077401') are fine.
        Page ranges should use double hyphen (e.g., '123--456' not '123-456').
        """
        if 'pages' not in entry.fields:
            return

        pages = entry.fields['pages']

        # If already has double hyphen, it's correct
        if '--' in pages:
            return

        # Check if it has a single hyphen (potential page range with wrong format)
        # But we need to distinguish between:
        # - Single page numbers (no hyphen): '077401' - FINE
        # - Page ranges with single hyphen: '123-456' - NEEDS FIXING
        # - Page ranges with en-dash or em-dash: '123–456' or '123—456' - NEEDS FIXING

        if '-' in pages or '–' in pages or '—' in pages:
            # This looks like a page range with single hyphen
            # Check if it's actually a range (has digits on both sides of the hyphen)
            if re.search(r'\d+[-–—]\d+', pages):
                # This is a page range with single hyphen/dash
                self.warnings.append(
                    f"Entry {key}: Page range uses single hyphen/dash. Use double hyphen '--' instead: '{pages}'"
                )
            # Otherwise, it might be something like a hyphenated article number, which is fine

    def check_field_consistency(self, key: str, entry: Entry):
        """Check field naming consistency (BibTeX vs BibLaTeX)."""
        # Check if entry mixes BibTeX and BibLaTeX field names
        has_bibtex_fields = False
        has_biblatex_fields = False
        mixed_fields = []

        # Check for BibTeX-style fields
        if 'journal' in entry.fields:
            has_bibtex_fields = True
        if 'year' in entry.fields and 'date' not in entry.fields:
            has_bibtex_fields = True
        if 'address' in entry.fields:
            has_bibtex_fields = True

        # Check for BibLaTeX-style fields
        if 'journaltitle' in entry.fields:
            has_biblatex_fields = True
        if 'date' in entry.fields:
            has_biblatex_fields = True
        if 'location' in entry.fields:
            has_biblatex_fields = True

        # Warn if both present (especially problematic pairs)
        if 'journal' in entry.fields and 'journaltitle' in entry.fields:
            self.warnings.append(
                f"Entry {key}: Has both 'journal' (BibTeX) and 'journaltitle' (BibLaTeX) - use only one"
            )

        if 'year' in entry.fields and 'date' in entry.fields:
            self.warnings.append(
                f"Entry {key}: Has both 'year' (BibTeX) and 'date' (BibLaTeX) - use only one"
            )

        if 'address' in entry.fields and 'location' in entry.fields:
            self.warnings.append(
                f"Entry {key}: Has both 'address' (BibTeX) and 'location' (BibLaTeX) - use only one"
            )

    def check_completeness(self, key: str, entry: Entry):
        """Check for recommended fields (accepts both BibTeX and BibLaTeX alternatives)."""
        entry_type = entry.type.lower()

        if entry_type in RECOMMENDED_FIELDS:
            recommended = RECOMMENDED_FIELDS[entry_type]
            missing = []

            for field_spec in recommended:
                if isinstance(field_spec, list):
                    # Alternative fields - at least one must be present
                    alternatives = field_spec
                    if not any(alt in entry.fields for alt in alternatives):
                        # Don't show "OR" for single-item lists
                        if len(alternatives) == 1:
                            missing.append(alternatives[0])
                        else:
                            missing.append(' OR '.join(alternatives))
                else:
                    # Single recommended field
                    if field_spec not in entry.fields:
                        missing.append(field_spec)

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

    def remove_duplicate_fields(self, bib_data: BibliographyData) -> List[str]:
        """
        Remove duplicate alternative fields (journal/journaltitle, year/date).
        Keeps the BibLaTeX-preferred version (journaltitle, date).

        Returns:
            List of messages about removed duplicates
        """
        removed_duplicates = []

        for key, entry in bib_data.entries.items():
            # Check for journal AND journaltitle - keep journaltitle
            if 'journal' in entry.fields and 'journaltitle' in entry.fields:
                journal_value = entry.fields['journal']
                journaltitle_value = entry.fields['journaltitle']
                del entry.fields['journal']
                removed_duplicates.append(
                    f"Entry {key}: Removed duplicate 'journal' field (kept 'journaltitle')"
                )

            # Check for year AND date - keep date
            if 'year' in entry.fields and 'date' in entry.fields:
                year_value = entry.fields['year']
                date_value = entry.fields['date']
                del entry.fields['year']
                removed_duplicates.append(
                    f"Entry {key}: Removed duplicate 'year' field (kept 'date')"
                )

        return removed_duplicates

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
                     check_unknown_fields: bool = True,
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

        # Remove duplicate fields (journal/journaltitle, year/date) automatically
        self.removed_duplicates = self.remove_duplicate_fields(bib_data)
        if self.removed_duplicates:
            print(f"\nAutomatically removed {len(self.removed_duplicates)} duplicate field(s)")
            for msg in self.removed_duplicates:
                print(f"  ✓ {msg}")

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
            if check_unknown_fields:
                self.check_unknown_fields(key, entry)
            if check_dates:
                self.check_date_validity(key, entry)
            if check_identifiers:
                self.check_identifier_formats(key, entry)
                self.check_page_format(key, entry)
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

        if self.removed_duplicates:
            report.append(f"\nDuplicate Fields Removed: {len(self.removed_duplicates)}")
            for msg in self.removed_duplicates:
                report.append(f"  ✓ {msg}")

        if self.issues:
            report.append(f"\nIssues Found: {len(self.issues)}")
            for issue in self.issues:
                report.append(f"  ✗ {issue}")

        if self.warnings:
            report.append(f"\nWarnings: {len(self.warnings)}")
            for warning in self.warnings:
                report.append(f"  ⚠ {warning}")

        if not self.issues and not self.warnings and not self.removed_duplicates:
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
    parser.add_argument('--fix', action='store_true',
                       help='Automatically fix issues and save to *_formatting_corrected.bib')

    # Diagnostic options
    parser.add_argument('--no-unicode', action='store_true', help='Skip unicode checking')
    parser.add_argument('--no-ampersand', action='store_true', help='Skip ampersand checking')
    parser.add_argument('--no-special', action='store_true', help='Skip special character checking')
    parser.add_argument('--no-accents', action='store_true', help='Skip accent checking')
    parser.add_argument('--no-names', action='store_true', help='Skip name formatting checking')
    parser.add_argument('--no-entry-types', action='store_true', help='Skip entry type validation')
    parser.add_argument('--no-unknown-fields', action='store_true', help='Skip unknown field detection')
    parser.add_argument('--no-dates', action='store_true', help='Skip date validation')
    parser.add_argument('--no-identifiers', action='store_true', help='Skip identifier validation')
    parser.add_argument('--no-consistency', action='store_true', help='Skip field consistency')
    parser.add_argument('--no-completeness', action='store_true', help='Skip completeness checking')
    parser.add_argument('--no-crossrefs', action='store_true', help='Skip crossref validation')
    parser.add_argument('--no-duplicates', action='store_true', help='Skip duplicate detection')

    args = parser.parse_args()

    # Clean file paths
    args.input_file = clean_filepath(args.input_file)
    if args.report_file:
        args.report_file = clean_filepath(args.report_file)

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
            check_unknown_fields=not args.no_unknown_fields,
            check_dates=not args.no_dates,
            check_identifiers=not args.no_identifiers,
            check_consistency=not args.no_consistency,
            check_completeness=not args.no_completeness,
            check_crossrefs_flag=not args.no_crossrefs,
            check_duplicates=not args.no_duplicates
        )

        # Save corrected file if --fix option is used
        if args.fix and cleaner.removed_duplicates:
            # Generate output filename
            import os
            base_name = os.path.splitext(args.input_file)[0]
            output_file = f"{base_name}_formatting_corrected.bib"
            cleaner.save_bibtex(bib_data, output_file)
            print(f"\n✓ Corrected file saved to: {output_file}")

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
