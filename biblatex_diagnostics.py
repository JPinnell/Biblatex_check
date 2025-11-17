#!/usr/bin/env python3
"""
BibTeX Diagnostic Tool
A comprehensive tool for validating and correcting BibTeX entries using Semantic Scholar as ground truth.
"""

import re
import sys
import os
import time
import argparse
import requests
from typing import Dict, List, Tuple, Optional, Set
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from difflib import SequenceMatcher
from pybtex.database import parse_file, BibliographyData, Entry
from pybtex.database.output.bibtex import Writer

# Semantic Scholar API endpoint
SEMANTIC_SCHOLAR_API_BASE = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_AVAILABLE = True  # API is always available, just needs rate limiting
SEMANTIC_SCHOLAR_API_KEY = os.environ.get('SEMANTIC_SCHOLAR_API_KEY', None)


# Biblatex entry type specifications
BIBLATEX_ENTRY_TYPES = {
    'article': {
        'required': ['author', 'title', 'journaltitle', 'year'],
        'optional': ['translator', 'annotator', 'commentator', 'subtitle', 'titleaddon',
                    'editor', 'editora', 'editorb', 'editorc', 'journalsubtitle', 'issuetitle',
                    'issuesubtitle', 'language', 'origlanguage', 'series', 'volume', 'number',
                    'eid', 'issue', 'month', 'pages', 'version', 'note', 'issn', 'addendum',
                    'pubstate', 'doi', 'eprint', 'eprintclass', 'eprinttype', 'url', 'urldate']
    },
    'book': {
        'required': ['author', 'title', 'year'],
        'optional': ['editor', 'publisher', 'location', 'isbn', 'series', 'volume', 'edition',
                    'chapter', 'pages', 'pagetotal', 'doi', 'url', 'urldate']
    },
    'inproceedings': {
        'required': ['author', 'title', 'booktitle', 'year'],
        'optional': ['editor', 'volume', 'number', 'series', 'pages', 'address', 'month',
                    'organization', 'publisher', 'doi', 'url', 'urldate']
    },
    'proceedings': {
        'required': ['title', 'year'],
        'optional': ['editor', 'volume', 'number', 'series', 'address', 'month', 'publisher',
                    'organization', 'doi', 'isbn', 'url', 'urldate']
    },
    'thesis': {
        'required': ['author', 'title', 'type', 'institution', 'year'],
        'optional': ['address', 'month', 'url', 'urldate', 'doi']
    },
    'phdthesis': {
        'required': ['author', 'title', 'school', 'year'],
        'optional': ['address', 'month', 'url', 'urldate', 'doi', 'type']
    },
    'mastersthesis': {
        'required': ['author', 'title', 'school', 'year'],
        'optional': ['address', 'month', 'url', 'urldate', 'doi', 'type']
    },
    'inbook': {
        'required': ['author', 'title', 'booktitle', 'year'],
        'optional': ['editor', 'volume', 'number', 'series', 'pages', 'address', 'publisher',
                    'chapter', 'doi', 'url', 'urldate']
    },
    'incollection': {
        'required': ['author', 'title', 'booktitle', 'year'],
        'optional': ['editor', 'volume', 'number', 'series', 'type', 'chapter', 'pages',
                    'address', 'edition', 'month', 'publisher', 'doi', 'url', 'urldate']
    },
    'online': {
        'required': ['author', 'title', 'url', 'year'],
        'optional': ['urldate', 'note', 'organization', 'date', 'month']
    },
    'misc': {
        'required': [],  # misc can have any fields
        'optional': ['author', 'title', 'howpublished', 'year', 'month', 'note', 'url', 'urldate']
    },
    'techreport': {
        'required': ['author', 'title', 'institution', 'year'],
        'optional': ['type', 'number', 'address', 'month', 'url', 'urldate', 'doi']
    },
    'unpublished': {
        'required': ['author', 'title', 'note'],
        'optional': ['year', 'month', 'url', 'urldate']
    },
    'manual': {
        'required': ['title'],
        'optional': ['author', 'organization', 'address', 'edition', 'month', 'year', 'url', 'urldate']
    },
}

# Recommended fields for scholarly completeness
RECOMMENDED_FIELDS = {
    'article': ['volume', 'number', 'pages', 'doi'],
    'book': ['publisher', 'location', 'isbn'],
    'inproceedings': ['pages', 'publisher', 'doi'],
    'online': ['urldate', 'organization'],
}


class BibTeXDiagnostics:
    """Main diagnostic class for BibTeX file validation and correction."""

    def __init__(self, verbose: bool = False, delay: float = 5.0):
        """
        Initialize the diagnostic tool.

        Args:
            verbose: Enable verbose output
            delay: Delay between Semantic Scholar API queries (seconds) to avoid rate limiting
        """
        self.verbose = verbose
        self.delay = delay
        self.issues = []
        self.corrections = []

    def log(self, message: str):
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(f"[INFO] {message}")

    def load_bibtex(self, filepath: str) -> BibliographyData:
        """Load a BibTeX file."""
        self.log(f"Loading BibTeX file: {filepath}")
        bib_data = parse_file(filepath)
        self.log(f"Loaded {len(bib_data.entries)} entries")
        return bib_data

    def save_bibtex(self, bib_data: BibliographyData, filepath: str):
        """Save BibTeX database to file."""
        writer = Writer()
        writer.write_file(bib_data, filepath)
        self.log(f"Saved corrected BibTeX to: {filepath}")

    def check_semantic_scholar(self, key: str, entry: Entry, update: bool = False) -> Optional[Entry]:
        """
        Check entry against Semantic Scholar and optionally update it.

        Args:
            key: BibTeX entry key
            entry: BibTeX entry
            update: If True, return the Semantic Scholar entry for updating

        Returns:
            Semantic Scholar entry if found and update=True, otherwise None
        """
        if not SEMANTIC_SCHOLAR_AVAILABLE:
            return None

        title = entry.fields.get('title', '').strip('{}').strip()
        if not title:
            self.issues.append(f"Entry {key} has no title")
            return None

        self.log(f"Searching Semantic Scholar for: {title}")

        max_retries = 3
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                # Search for the paper by title using Semantic Scholar API
                search_url = f"{SEMANTIC_SCHOLAR_API_BASE}/paper/search"
                params = {
                    'query': title,
                    'limit': 1,
                    'fields': 'title,authors,year,venue,doi,abstract,publicationTypes,externalIds'
                }

                # Add headers with User-Agent and optional API key
                headers = {
                    'User-Agent': 'biblatex-diagnostics/1.0 (https://github.com/user/biblatex-diagnostics)'
                }
                if SEMANTIC_SCHOLAR_API_KEY:
                    headers['x-api-key'] = SEMANTIC_SCHOLAR_API_KEY

                response = requests.get(search_url, params=params, headers=headers, timeout=10)

                # Handle rate limiting
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        self.log(f"Rate limited, waiting {retry_delay} seconds before retry...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        self.issues.append(f"Entry {key}: Semantic Scholar rate limit exceeded")
                        return None

                response.raise_for_status()
                data = response.json()

                if data.get('data') and len(data['data']) > 0:
                    result = data['data'][0]

                    # Check if titles match (allowing for some variation)
                    ss_title = result.get('title', '').lower()
                    entry_title = title.lower()

                    # Simple similarity check
                    if self._titles_match(entry_title, ss_title):
                        self.log(f"✓ Match found on Semantic Scholar: {result['title']}")

                        if update:
                            # Convert to BibTeX format
                            ss_entry = self._semantic_scholar_to_entry(result, key, entry.type)
                            return ss_entry
                        else:
                            # Just report the match
                            self.corrections.append({
                                'entry_id': key,
                                'type': 'semantic_scholar_match',
                                'message': f"Found matching entry on Semantic Scholar",
                                'ss_data': result
                            })
                    else:
                        self.issues.append(f"Entry {key}: Title mismatch - '{title}' vs '{result['title']}'")
                else:
                    self.issues.append(f"Entry {key}: Not found on Semantic Scholar")

                break  # Success, exit retry loop

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    self.log(f"Request error, retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    self.issues.append(f"Entry {key}: Semantic Scholar error - {str(e)}")

        return None

    def _titles_match(self, title1: str, title2: str) -> bool:
        """Check if two titles match (with some tolerance)."""
        # Remove common punctuation and extra spaces
        clean1 = re.sub(r'[^\w\s]', '', title1.lower()).strip()
        clean2 = re.sub(r'[^\w\s]', '', title2.lower()).strip()

        # Check if one title contains most of the other
        words1 = set(clean1.split())
        words2 = set(clean2.split())

        if not words1 or not words2:
            return False

        # Calculate Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        similarity = intersection / union if union > 0 else 0

        return similarity > 0.7  # 70% similarity threshold

    def _semantic_scholar_to_entry(self, ss_result: Dict, entry_key: str, entry_type: str) -> Entry:
        """Convert Semantic Scholar result to pybtex Entry format."""
        # Determine entry type from publication types
        pub_types = ss_result.get('publicationTypes', [])
        if 'JournalArticle' in pub_types:
            etype = 'article'
        elif 'Conference' in pub_types or 'ConferencePaper' in pub_types:
            etype = 'inproceedings'
        elif 'Book' in pub_types:
            etype = 'book'
        else:
            # Use venue to guess if not specified in types
            venue = ss_result.get('venue', '').lower()
            if venue and ('journal' in venue or 'trans' in venue):
                etype = 'article'
            elif venue and ('conference' in venue or 'proc' in venue):
                etype = 'inproceedings'
            else:
                etype = entry_type or 'article'

        # Create fields dict
        fields = {
            'title': '{' + ss_result.get('title', '') + '}',
        }

        # Add year
        if 'year' in ss_result and ss_result['year']:
            fields['year'] = str(ss_result['year'])

        # Add venue
        if 'venue' in ss_result and ss_result['venue']:
            if etype == 'article':
                fields['journaltitle'] = ss_result['venue']
            elif etype == 'inproceedings':
                fields['booktitle'] = ss_result['venue']

        # Add DOI
        if 'doi' in ss_result and ss_result['doi']:
            fields['doi'] = ss_result['doi']

        # Add arXiv ID if available
        external_ids = ss_result.get('externalIds', {})
        if external_ids.get('ArXiv'):
            fields['eprint'] = external_ids['ArXiv']
            fields['eprinttype'] = 'arxiv'

        # Add abstract if available
        if 'abstract' in ss_result and ss_result['abstract']:
            fields['abstract'] = '{' + ss_result['abstract'] + '}'

        # Handle authors
        from pybtex.database import Person
        persons = {}
        if 'authors' in ss_result and ss_result['authors']:
            author_list = []
            for author in ss_result['authors']:
                author_name = author.get('name', '')
                if author_name:
                    author_list.append(Person(author_name))
            if author_list:
                persons['author'] = author_list

        return Entry(etype, fields=fields, persons=persons)

    def validate_doi(self, key: str, entry: Entry) -> bool:
        """
        Validate DOI format and check if it resolves.

        Returns:
            True if DOI is valid, False otherwise
        """
        doi = entry.fields.get('doi', '').strip()
        if not doi:
            return True  # No DOI is not an error

        # Check DOI format
        doi_pattern = r'^10\.\d{4,}/[^\s]+$'
        if not re.match(doi_pattern, doi):
            self.issues.append(f"Entry {key}: Invalid DOI format - {doi}")
            return False

        # Check if DOI resolves (optional, can be slow)
        try:
            response = requests.head(f"https://doi.org/{doi}", timeout=5, allow_redirects=True)
            if response.status_code >= 400:
                self.issues.append(f"Entry {key}: DOI does not resolve - {doi}")
                return False
        except Exception as e:
            self.issues.append(f"Entry {key}: Could not verify DOI - {str(e)}")
            return False

        self.log(f"✓ Valid DOI: {doi}")
        return True

    def check_unicode_issues(self, key: str, entry: Entry) -> List[str]:
        """
        Check for problematic unicode characters.

        Returns:
            List of fields with unicode issues
        """
        issues = []
        problematic_chars = {
            '—': 'em-dash',
            '–': 'en-dash',
            ''': 'smart quote',
            ''': 'smart quote',
            '"': 'smart quote',
            '"': 'smart quote',
            '…': 'ellipsis',
        }

        for field, value in entry.fields.items():
            value_str = str(value)
            for char, name in problematic_chars.items():
                if char in value_str:
                    issues.append(field)
                    self.issues.append(
                        f"Entry {key}, field '{field}': Contains {name} ('{char}')"
                    )

        return issues

    def check_unescaped_ampersand(self, key: str, entry: Entry) -> List[str]:
        """
        Check for unescaped ampersands (should be \\&).

        Returns:
            List of fields with unescaped ampersands
        """
        issues = []

        for field, value in entry.fields.items():
            value_str = str(value)
            # Find ampersands that are not escaped (not preceded by backslash)
            if re.search(r'(?<!\\)&', value_str):
                issues.append(field)
                self.issues.append(
                    f"Entry {key}, field '{field}': Contains unescaped ampersand"
                )

        return issues

    def check_special_characters(self, key: str, entry: Entry) -> List[str]:
        """
        Check for improperly formatted special characters.

        Returns:
            List of fields with special character issues
        """
        issues = []

        for field, value in entry.fields.items():
            value_str = str(value)

            # Check for unescaped underscores (common in URLs or identifiers)
            if '_' in value_str and field not in ['url', 'doi', 'eprint', 'file']:
                if re.search(r'(?<!\\)_', value_str):
                    issues.append(field)
                    self.issues.append(
                        f"Entry {key}, field '{field}': May contain unescaped underscore"
                    )

            # Check for unescaped percent signs
            if re.search(r'(?<!\\)%', value_str):
                issues.append(field)
                self.issues.append(
                    f"Entry {key}, field '{field}': Contains unescaped percent sign"
                )

        return issues

    def check_accent_formatting(self, key: str, entry: Entry) -> List[str]:
        """
        Check for unescaped accented characters that should be LaTeX-formatted.

        Returns:
            List of fields with accent formatting issues
        """
        issues = []

        # Common accented characters that should be LaTeX-formatted
        accent_chars = {
            'á': r"\'a", 'à': r"\`a", 'ä': r'\"a', 'â': r"\^a", 'ã': r"\~a", 'å': r"\aa",
            'Á': r"\'A", 'À': r"\`A", 'Ä': r'\"A', 'Â': r"\^A", 'Ã': r"\~A", 'Å': r"\AA",
            'é': r"\'e", 'è': r"\`e", 'ë': r'\"e', 'ê': r"\^e",
            'É': r"\'E", 'È': r"\`E", 'Ë': r'\"E', 'Ê': r"\^E",
            'í': r"\'i", 'ì': r"\`i", 'ï': r'\"i', 'î': r"\^i",
            'Í': r"\'I", 'Ì': r"\`I", 'Ï': r'\"I', 'Î': r"\^I",
            'ó': r"\'o", 'ò': r"\`o", 'ö': r'\"o', 'ô': r"\^o", 'õ': r"\~o", 'ø': r"\o",
            'Ó': r"\'O", 'Ò': r"\`O", 'Ö': r'\"O', 'Ô': r"\^O", 'Õ': r"\~O", 'Ø': r"\O",
            'ú': r"\'u", 'ù': r"\`u", 'ü': r'\"u', 'û': r"\^u",
            'Ú': r"\'U", 'Ù': r"\`U", 'Ü': r'\"U', 'Û': r"\^U",
            'ñ': r"\~n", 'Ñ': r"\~N",
            'ç': r"\c{c}", 'Ç': r"\c{C}",
            'ß': r"\ss",
            'æ': r"\ae", 'Æ': r"\AE",
            'œ': r"\oe", 'Œ': r"\OE",
            'ł': r"\l", 'Ł': r"\L",
        }

        for field, value in entry.fields.items():
            value_str = str(value)
            found_chars = []

            for char, latex_form in accent_chars.items():
                if char in value_str:
                    found_chars.append(f"{char} (should be {latex_form})")

            if found_chars:
                issues.append(field)
                chars_str = ", ".join(found_chars)
                self.issues.append(
                    f"Entry {key}, field '{field}': Contains unescaped accented characters: {chars_str}"
                )

        return issues

    def check_name_formatting(self, key: str, entry: Entry) -> List[str]:
        """
        Check for name formatting issues in author/editor fields.

        Returns:
            List of fields with name formatting issues
        """
        issues = []

        # Check author and editor fields
        for role in ['author', 'editor']:
            if role in entry.persons:
                persons = entry.persons[role]

                for idx, person in enumerate(persons):
                    person_str = str(person)

                    # Check for potential issues
                    warnings = []

                    # Check for single-word names (might indicate parsing issues)
                    if ' ' not in person_str.strip() and ',' not in person_str.strip():
                        warnings.append("single-word name (may indicate parsing issue)")

                    # Check for numbers in names (likely an error)
                    if re.search(r'\d', person_str):
                        warnings.append("contains numbers")

                    # Check for multiple consecutive spaces
                    if '  ' in person_str:
                        warnings.append("multiple consecutive spaces")

                    # Check for unusual characters
                    if re.search(r'[{}[\]<>|]', person_str):
                        warnings.append("unusual characters")

                    if warnings:
                        issues.append(role)
                        warnings_str = ", ".join(warnings)
                        self.issues.append(
                            f"Entry {key}, {role} #{idx+1} '{person_str}': {warnings_str}"
                        )

        # Also check the raw author/editor fields for common issues
        for field in ['author', 'editor']:
            if field in entry.fields:
                value_str = str(entry.fields[field])

                # Check for inconsistent name separators
                if ' and ' in value_str and '&' in value_str:
                    issues.append(field)
                    self.issues.append(
                        f"Entry {key}, field '{field}': Inconsistent separators (mixes 'and' and '&')"
                    )

                # Check for missing 'and' between authors (common error)
                # This looks for patterns like "Smith, J. Doe, A." without 'and'
                if re.search(r',\s+[A-Z][a-z]+,\s+[A-Z]\.(?!\s+and\s+)', value_str):
                    issues.append(field)
                    self.issues.append(
                        f"Entry {key}, field '{field}': Possible missing 'and' between authors"
                    )

        return issues

    def check_entry_type_fields(self, key: str, entry: Entry) -> List[str]:
        """
        Check if entry has all required fields for its type and warn about inappropriate fields.

        Returns:
            List of fields with issues
        """
        issues = []
        entry_type = entry.type.lower()

        # Check if entry type is known
        if entry_type not in BIBLATEX_ENTRY_TYPES:
            self.issues.append(
                f"Entry {key}: Unknown entry type '@{entry_type}'"
            )
            return issues

        spec = BIBLATEX_ENTRY_TYPES[entry_type]
        entry_fields = set(entry.fields.keys())

        # Also include author/editor from persons
        if 'author' in entry.persons:
            entry_fields.add('author')
        if 'editor' in entry.persons:
            entry_fields.add('editor')

        # Check for missing required fields
        required = set(spec['required'])
        missing_fields = required - entry_fields

        if missing_fields:
            self.issues.append(
                f"Entry {key} (@{entry_type}): Missing required fields: {', '.join(sorted(missing_fields))}"
            )
            issues.extend(missing_fields)

        return issues

    def check_date_validity(self, key: str, entry: Entry) -> bool:
        """
        Check if year/date fields are valid and sensible.

        Returns:
            True if valid, False otherwise
        """
        valid = True
        current_year = datetime.now().year

        # Check year field
        if 'year' in entry.fields:
            year_str = entry.fields['year'].strip()
            try:
                year = int(year_str)

                # Check for impossible years
                if year < 1000:
                    self.issues.append(f"Entry {key}: Suspicious year '{year}' (before 1000)")
                    valid = False
                elif year > current_year + 5:
                    self.issues.append(f"Entry {key}: Future year '{year}' (more than 5 years ahead)")
                    valid = False
            except ValueError:
                self.issues.append(f"Entry {key}: Invalid year format '{year_str}'")
                valid = False

        # Check date field if present
        if 'date' in entry.fields:
            date_str = entry.fields['date'].strip()

            # Check ISO format YYYY-MM-DD
            date_pattern = r'^\d{4}-\d{2}-\d{2}$'
            if re.match(date_pattern, date_str):
                try:
                    year, month, day = map(int, date_str.split('-'))

                    if not (1 <= month <= 12):
                        self.issues.append(f"Entry {key}: Invalid month in date '{date_str}'")
                        valid = False
                    elif not (1 <= day <= 31):
                        self.issues.append(f"Entry {key}: Invalid day in date '{date_str}'")
                        valid = False
                    elif year > current_year + 5:
                        self.issues.append(f"Entry {key}: Future date '{date_str}'")
                        valid = False
                except ValueError:
                    self.issues.append(f"Entry {key}: Invalid date format '{date_str}'")
                    valid = False

        # Check month field
        if 'month' in entry.fields:
            month = entry.fields['month'].strip().lower()
            valid_months = ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
                          'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
                          'january', 'february', 'march', 'april', 'may', 'june',
                          'july', 'august', 'september', 'october', 'november', 'december']

            # Check if it's a number
            if month.isdigit():
                month_num = int(month)
                if not (1 <= month_num <= 12):
                    self.issues.append(f"Entry {key}: Invalid month number '{month}'")
                    valid = False
            elif month not in valid_months:
                self.issues.append(f"Entry {key}: Invalid month '{month}'")
                valid = False

        return valid

    def check_identifier_formats(self, key: str, entry: Entry) -> List[str]:
        """
        Validate ISBN, ISSN, arXiv, and other identifier formats.

        Returns:
            List of fields with invalid identifiers
        """
        issues = []

        # Check ISBN
        if 'isbn' in entry.fields:
            isbn = re.sub(r'[-\s]', '', entry.fields['isbn'])

            # ISBN-10 or ISBN-13
            if not (len(isbn) == 10 or len(isbn) == 13):
                self.issues.append(f"Entry {key}: Invalid ISBN length '{entry.fields['isbn']}'")
                issues.append('isbn')
            elif not isbn.replace('X', '').replace('x', '').isdigit():
                self.issues.append(f"Entry {key}: Invalid ISBN format '{entry.fields['isbn']}'")
                issues.append('isbn')

        # Check ISSN (format: XXXX-XXXX)
        if 'issn' in entry.fields:
            issn = entry.fields['issn'].strip()
            issn_pattern = r'^\d{4}-\d{3}[\dXx]$'

            if not re.match(issn_pattern, issn):
                self.issues.append(f"Entry {key}: Invalid ISSN format '{issn}' (should be XXXX-XXXX)")
                issues.append('issn')

        # Check arXiv ID
        if 'eprint' in entry.fields and entry.fields.get('eprinttype', '').lower() == 'arxiv':
            arxiv_id = entry.fields['eprint'].strip()

            # Old format: arch-ive/YYMMNNN or New format: YYMM.NNNNN
            old_pattern = r'^[a-z\-]+/\d{7}$'
            new_pattern = r'^\d{4}\.\d{4,5}$'

            if not (re.match(old_pattern, arxiv_id) or re.match(new_pattern, arxiv_id)):
                self.issues.append(f"Entry {key}: Invalid arXiv ID format '{arxiv_id}'")
                issues.append('eprint')

        # Check for placeholder values
        placeholder_patterns = ['tba', 'tbd', '??', 'xxx', 'pending']
        for field in ['doi', 'url', 'isbn', 'issn']:
            if field in entry.fields:
                value = entry.fields[field].lower().strip()
                if any(p in value for p in placeholder_patterns):
                    self.issues.append(f"Entry {key}: Placeholder value in {field}: '{entry.fields[field]}'")
                    issues.append(field)

        return issues

    def check_field_consistency(self, key: str, entry: Entry) -> List[str]:
        """
        Check for field naming consistency (biblatex vs bibtex conventions).

        Returns:
            List of fields with consistency issues
        """
        issues = []

        # Check for old BibTeX fields that should be updated in biblatex
        old_to_new = {
            'journal': 'journaltitle',
            'school': 'institution',
            'address': 'location',
        }

        for old_field, new_field in old_to_new.items():
            if old_field in entry.fields:
                entry_type = entry.type.lower()
                # Only warn for entry types where this matters
                if entry_type in ['article', 'phdthesis', 'mastersthesis']:
                    self.issues.append(
                        f"Entry {key}: Use '{new_field}' instead of '{old_field}' in biblatex"
                    )
                    issues.append(old_field)

        return issues

    def check_completeness(self, key: str, entry: Entry) -> List[str]:
        """
        Check if recommended fields are missing for scholarly completeness.

        Returns:
            List of missing recommended fields
        """
        issues = []
        entry_type = entry.type.lower()

        if entry_type not in RECOMMENDED_FIELDS:
            return issues

        recommended = RECOMMENDED_FIELDS[entry_type]
        entry_fields = set(entry.fields.keys())
        missing = [f for f in recommended if f not in entry_fields]

        if missing:
            self.issues.append(
                f"Entry {key} (@{entry_type}): Missing recommended fields for completeness: {', '.join(missing)}"
            )
            issues.extend(missing)

        # Check for suspiciously bare entries
        essential_count = len(entry_fields.intersection({'author', 'title', 'year', 'journal', 'journaltitle', 'booktitle'}))
        if essential_count < 3 and entry_type != 'misc':
            self.issues.append(
                f"Entry {key}: Suspiciously bare entry (only {len(entry_fields)} fields)"
            )

        return issues

    def check_crossrefs(self, bib_data: BibliographyData) -> Dict[str, List[str]]:
        """
        Validate crossref, xdata, and related fields point to existing entries.

        Returns:
            Dictionary mapping entry keys to lists of broken references
        """
        all_keys = set(bib_data.entries.keys())
        broken_refs = {}

        for key, entry in bib_data.entries.items():
            broken = []

            # Check crossref
            if 'crossref' in entry.fields:
                ref_key = entry.fields['crossref']
                if ref_key not in all_keys:
                    self.issues.append(
                        f"Entry {key}: Broken crossref to '{ref_key}' (entry does not exist)"
                    )
                    broken.append(ref_key)

            # Check xdata
            if 'xdata' in entry.fields:
                xdata_keys = entry.fields['xdata'].split(',')
                for xdata_key in xdata_keys:
                    xdata_key = xdata_key.strip()
                    if xdata_key not in all_keys:
                        self.issues.append(
                            f"Entry {key}: Broken xdata reference to '{xdata_key}' (entry does not exist)"
                        )
                        broken.append(xdata_key)

            # Check related
            if 'related' in entry.fields:
                related_keys = entry.fields['related'].split(',')
                for related_key in related_keys:
                    related_key = related_key.strip()
                    if related_key not in all_keys:
                        self.issues.append(
                            f"Entry {key}: Broken related reference to '{related_key}' (entry does not exist)"
                        )
                        broken.append(related_key)

            if broken:
                broken_refs[key] = broken

        return broken_refs

    def find_duplicates(self, bib_data: BibliographyData, threshold: float = 0.8) -> List[Tuple[str, str, float]]:
        """
        Find potential duplicate entries using fuzzy matching on author+title+year.

        Args:
            bib_data: Bibliography database
            threshold: Similarity threshold (0.0 to 1.0)

        Returns:
            List of tuples (key1, key2, similarity_score)
        """
        duplicates = []
        entries_list = list(bib_data.entries.items())

        for i, (key1, entry1) in enumerate(entries_list):
            for key2, entry2 in entries_list[i+1:]:
                # Create fingerprints
                def make_fingerprint(entry):
                    authors = ' '.join([str(p) for p in entry.persons.get('author', [])])
                    title = entry.fields.get('title', '').lower()
                    year = entry.fields.get('year', '')
                    return f"{authors} {title} {year}".lower()

                fp1 = make_fingerprint(entry1)
                fp2 = make_fingerprint(entry2)

                # Calculate similarity
                similarity = SequenceMatcher(None, fp1, fp2).ratio()

                if similarity >= threshold:
                    duplicates.append((key1, key2, similarity))
                    self.issues.append(
                        f"Possible duplicate: '{key1}' and '{key2}' ({similarity:.0%} similar)"
                    )

        return duplicates

    def run_diagnostics(self, bib_data: BibliographyData, check_scholar: bool = True,
                       check_doi: bool = True, check_unicode: bool = True,
                       check_ampersand: bool = True, check_special: bool = True,
                       check_accents: bool = True, check_names: bool = True,
                       check_entry_types: bool = True, check_dates: bool = True,
                       check_identifiers: bool = True, check_consistency: bool = True,
                       check_completeness_flag: bool = True, check_crossrefs_flag: bool = True,
                       check_duplicates: bool = True) -> None:
        """
        Run all selected diagnostics on the BibTeX database.

        Args:
            bib_data: The BibTeX database to check
            check_scholar: Check against Semantic Scholar
            check_doi: Validate DOIs
            check_unicode: Check for unicode issues
            check_ampersand: Check for unescaped ampersands
            check_special: Check for special character issues
            check_accents: Check for accent formatting issues
            check_names: Check for name formatting issues
            check_entry_types: Check entry types have required fields
            check_dates: Check date validity
            check_identifiers: Check ISBN/ISSN/arXiv formats
            check_consistency: Check field naming consistency
            check_completeness_flag: Check for recommended fields
            check_crossrefs_flag: Check crossref/xdata/related validity
            check_duplicates: Find potential duplicate entries
        """
        total_entries = len(bib_data.entries)
        print(f"\nRunning diagnostics on {total_entries} entries...")
        print("=" * 60)

        # Run cross-entry checks first
        if check_crossrefs_flag:
            self.check_crossrefs(bib_data)

        if check_duplicates:
            self.find_duplicates(bib_data)

        # Run per-entry checks
        for idx, (key, entry) in enumerate(bib_data.entries.items(), 1):
            print(f"\n[{idx}/{total_entries}] Checking: {key}")

            if check_entry_types:
                self.check_entry_type_fields(key, entry)

            if check_dates:
                self.check_date_validity(key, entry)

            if check_identifiers:
                self.check_identifier_formats(key, entry)

            if check_consistency:
                self.check_field_consistency(key, entry)

            if check_completeness_flag:
                self.check_completeness(key, entry)

            if check_scholar and SEMANTIC_SCHOLAR_AVAILABLE:
                self.check_semantic_scholar(key, entry, update=False)
                time.sleep(self.delay)  # Rate limiting

            if check_doi:
                self.validate_doi(key, entry)

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

    def fix_with_semantic_scholar(self, bib_data: BibliographyData) -> BibliographyData:
        """
        Update BibTeX entries with Semantic Scholar data where matches are found.

        Args:
            bib_data: The BibTeX database to update

        Returns:
            Updated BibTeX database
        """
        if not SEMANTIC_SCHOLAR_AVAILABLE:
            print("Error: Semantic Scholar API not available. Cannot update entries.")
            return bib_data

        total_entries = len(bib_data.entries)
        print(f"\nUpdating {total_entries} entries with Semantic Scholar data...")
        print("=" * 60)

        updated_count = 0

        for idx, (key, entry) in enumerate(list(bib_data.entries.items()), 1):
            print(f"\n[{idx}/{total_entries}] Processing: {key}")

            ss_entry = self.check_semantic_scholar(key, entry, update=True)

            if ss_entry:
                # Update entry with Semantic Scholar data
                bib_data.entries[key] = ss_entry
                updated_count += 1
                print(f"  ✓ Updated with Semantic Scholar data")
            else:
                print(f"  ✗ No update available")

            time.sleep(self.delay)  # Rate limiting

        print(f"\n{'=' * 60}")
        print(f"Updated {updated_count}/{total_entries} entries")

        return bib_data

    def generate_report(self) -> str:
        """Generate a diagnostic report."""
        report = []
        report.append("\n" + "=" * 60)
        report.append("BIBTEX DIAGNOSTICS REPORT")
        report.append("=" * 60)

        if self.issues:
            report.append(f"\nFound {len(self.issues)} issues:\n")
            for issue in self.issues:
                report.append(f"  ⚠ {issue}")
        else:
            report.append("\n✓ No issues found!")

        if self.corrections:
            report.append(f"\n\nFound {len(self.corrections)} potential corrections:\n")
            for correction in self.corrections:
                report.append(f"  ℹ {correction['entry_id']}: {correction['message']}")

        report.append("\n" + "=" * 60)

        return "\n".join(report)


def main():
    """Main entry point for the diagnostic tool."""
    parser = argparse.ArgumentParser(
        description='BibTeX Diagnostic Tool - Validate and correct BibTeX entries using Semantic Scholar',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all diagnostics (print to terminal)
  python biblatex_diagnostics.py input.bib

  # Save diagnostic report to file
  python biblatex_diagnostics.py input.bib -r report.txt

  # Update entries with Semantic Scholar data
  python biblatex_diagnostics.py input.bib --update-scholar -o corrected.bib

  # Run specific diagnostics only
  python biblatex_diagnostics.py input.bib --no-scholar

  # Verbose output with custom delay and save report
  python biblatex_diagnostics.py input.bib -v --delay 3.0 -r diagnostics.txt
        """
    )

    parser.add_argument('input_file', help='Input BibTeX file')
    parser.add_argument('-o', '--output', help='Output file for corrected BibTeX')
    parser.add_argument('-r', '--report-file', help='Save diagnostic report to file (default: print to terminal)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    # Default delay: 1.0 second with API key (1 req/sec limit), 5.0 seconds without
    default_delay = 1.0 if SEMANTIC_SCHOLAR_API_KEY else 5.0
    parser.add_argument('--delay', type=float, default=default_delay,
                       help=f'Delay between Semantic Scholar API queries (default: {default_delay} seconds)')

    # Diagnostic options
    parser.add_argument('--no-scholar', action='store_true',
                       help='Skip Semantic Scholar checking')
    parser.add_argument('--no-doi', action='store_true',
                       help='Skip DOI validation')
    parser.add_argument('--no-unicode', action='store_true',
                       help='Skip unicode character checking')
    parser.add_argument('--no-ampersand', action='store_true',
                       help='Skip ampersand checking')
    parser.add_argument('--no-special', action='store_true',
                       help='Skip special character checking')
    parser.add_argument('--no-accents', action='store_true',
                       help='Skip accent formatting checking')
    parser.add_argument('--no-names', action='store_true',
                       help='Skip name formatting checking')
    parser.add_argument('--no-entry-types', action='store_true',
                       help='Skip entry type and required fields checking')
    parser.add_argument('--no-dates', action='store_true',
                       help='Skip date/year validity checking')
    parser.add_argument('--no-identifiers', action='store_true',
                       help='Skip ISBN/ISSN/arXiv format checking')
    parser.add_argument('--no-consistency', action='store_true',
                       help='Skip field naming consistency checking')
    parser.add_argument('--no-completeness', action='store_true',
                       help='Skip recommended fields checking')
    parser.add_argument('--no-crossrefs', action='store_true',
                       help='Skip crossref/xdata/related validation')
    parser.add_argument('--no-duplicates', action='store_true',
                       help='Skip duplicate entry detection')

    # Update options
    parser.add_argument('--update-scholar', action='store_true',
                       help='Update entries with Semantic Scholar data (requires -o)')

    args = parser.parse_args()

    # Validate arguments
    if args.update_scholar and not args.output:
        parser.error("--update-scholar requires -o/--output to be specified")

    # Initialize diagnostic tool
    diagnostics = BibTeXDiagnostics(verbose=args.verbose, delay=args.delay)

    try:
        # Load BibTeX file
        bib_data = diagnostics.load_bibtex(args.input_file)

        if args.update_scholar:
            # Update mode
            bib_data = diagnostics.fix_with_semantic_scholar(bib_data)
            diagnostics.save_bibtex(bib_data, args.output)
            print(f"\n✓ Corrected BibTeX saved to: {args.output}")
        else:
            # Diagnostic mode
            diagnostics.run_diagnostics(
                bib_data,
                check_scholar=not args.no_scholar,
                check_doi=not args.no_doi,
                check_unicode=not args.no_unicode,
                check_ampersand=not args.no_ampersand,
                check_special=not args.no_special,
                check_accents=not args.no_accents,
                check_names=not args.no_names,
                check_entry_types=not args.no_entry_types,
                check_dates=not args.no_dates,
                check_identifiers=not args.no_identifiers,
                check_consistency=not args.no_consistency,
                check_completeness_flag=not args.no_completeness,
                check_crossrefs_flag=not args.no_crossrefs,
                check_duplicates=not args.no_duplicates
            )

        # Generate and output report
        report = diagnostics.generate_report()

        if args.report_file:
            # Save report to file
            with open(args.report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\n✓ Diagnostic report saved to: {args.report_file}")
        else:
            # Print to terminal
            print(report)

    except FileNotFoundError:
        print(f"Error: File '{args.input_file}' not found", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
