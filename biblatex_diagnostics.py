#!/usr/bin/env python3
"""
BibTeX API Diagnostics Tool
Validates and corrects BibTeX entries by comparing against online sources (Crossref and Semantic Scholar).
"""

import re
import sys
import os
import time
import argparse
import requests
import unicodedata
from typing import Dict, List, Optional, Tuple
from pybtex.database import parse_file, BibliographyData, Entry, Person
from pybtex.database.output.bibtex import Writer

# Crossref API endpoint (primary)
CROSSREF_API_BASE = "https://api.crossref.org"
MAILTO_EMAIL = os.environ.get('CROSSREF_MAILTO', 'research@example.com')

# Semantic Scholar API endpoint (fallback)
SEMANTIC_SCHOLAR_API_BASE = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_API_KEY = os.environ.get('SEMANTIC_SCHOLAR_API_KEY', None)

# Name particles that should be ignored when comparing/sorting author names
NAME_PARTICLES = {'von', 'van', 'de', 'del', 'della', 'di', 'du', 'le', 'la', 'da', 'dos', 'das', 'ten', 'ter', 'den', 'der'}
NAME_SUFFIXES = {'jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv', 'v'}


def remove_accents(text: str) -> str:
    """Remove accents from Unicode string."""
    # Normalize to NFD (decomposed form)
    nfd = unicodedata.normalize('NFD', text)
    # Filter out combining characters (accents)
    return ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')


def normalize_latex_text(text: str) -> str:
    """
    Normalize LaTeX text by converting LaTeX accents to their Unicode equivalents,
    then removing accents for comparison.

    Examples:
        g{\\'e}r{\\^o}me -> gérôme -> gerome
        \\"{o} -> ö -> o
    """
    # Common LaTeX accent commands
    latex_accents = {
        r"\'": '',  # acute
        r'\`': '',  # grave
        r'\^': '',  # circumflex
        r'\"': '',  # umlaut
        r'\~': '',  # tilde
        r'\=': '',  # macron
        r'\.': '',  # dot above
        r'\u': '',  # breve
        r'\v': '',  # caron
        r'\H': '',  # double acute
        r'\c': '',  # cedilla
        r'\k': '',  # ogonek
        r'\r': '',  # ring above
    }

    # First, handle braced accent commands like {\'e}
    for cmd in latex_accents.keys():
        # Match patterns like {\cmd{letter}} or {\\cmd letter}
        text = re.sub(r'\{' + re.escape(cmd) + r'\{([a-zA-Z])\}\}', r'\1', text)
        text = re.sub(r'\{' + re.escape(cmd) + r'([a-zA-Z])\}', r'\1', text)
        text = re.sub(re.escape(cmd) + r'\{([a-zA-Z])\}', r'\1', text)
        text = re.sub(re.escape(cmd) + r'([a-zA-Z])', r'\1', text)

    # Remove any remaining braces
    text = text.replace('{', '').replace('}', '')

    # Remove accents from any Unicode characters
    text = remove_accents(text)

    return text


def normalize_ampersand(text: str) -> str:
    """Normalize ampersands for comparison: &amp; -> & and \\& -> &"""
    text = text.replace('&amp;', '&')
    text = text.replace('\\&', '&')
    return text


def extract_author_components(person_str: str) -> Tuple[str, str, List[str]]:
    """
    Extract last name, initials, and particles from author name.

    Returns:
        (lastname, initials, particles) tuple

    Examples:
        "John von Neumann" -> ("neumann", "J", ["von"])
        "De Gennes, Pierre-Gilles" -> ("gennes", "PG", ["de"])
        "Smith Jr., John" -> ("smith", "J", ["jr"])
    """
    person_str = person_str.strip()
    particles = []

    # Check for comma-separated format (Last, First)
    if ',' in person_str:
        parts = person_str.split(',')
        last_part = parts[0].strip()
        first_part = parts[1].strip() if len(parts) > 1 else ''
    else:
        # Space-separated format
        parts = person_str.split()
        if len(parts) == 0:
            return ('', '', [])
        elif len(parts) == 1:
            return (normalize_latex_text(parts[0]).lower(), '', [])

        # Find the last name (rightmost non-particle, non-suffix word)
        last_idx = len(parts) - 1

        # Check if last word is a suffix
        if parts[last_idx].lower().rstrip('.') in NAME_SUFFIXES:
            particles.append(parts[last_idx].lower().rstrip('.'))
            last_idx -= 1

        if last_idx < 0:
            return ('', '', particles)

        last_part = parts[last_idx]
        first_part = ' '.join(parts[:last_idx])

        # Check for particles before last name
        while last_idx > 0 and parts[last_idx - 1].lower() in NAME_PARTICLES:
            last_idx -= 1
            particles.insert(0, parts[last_idx].lower())
            last_part = parts[-1]
            first_part = ' '.join(parts[:last_idx])

    # Normalize last name
    lastname = normalize_latex_text(last_part).lower().strip()

    # Extract initials from first name
    initials = ''
    if first_part:
        # Remove LaTeX formatting and get first letters
        first_normalized = normalize_latex_text(first_part)
        # Split by spaces and hyphens
        name_parts = re.split(r'[\s\-]+', first_normalized)
        for part in name_parts:
            part = part.strip()
            if part and part.lower() not in NAME_PARTICLES and part.lower().rstrip('.') not in NAME_SUFFIXES:
                initials += part[0].upper()

    return (lastname, initials, particles)


def check_unclosed_math_mode(text: str) -> bool:
    """Check if there are unclosed $ symbols in LaTeX text."""
    # Count $ symbols that aren't escaped
    dollar_count = 0
    i = 0
    while i < len(text):
        if text[i] == '$':
            # Check if it's escaped
            if i == 0 or text[i-1] != '\\':
                dollar_count += 1
        i += 1

    # Should be even (each opening $ has a closing $)
    return dollar_count % 2 != 0


def check_page_range_format(pages: str) -> Optional[str]:
    """
    Check if page range uses double hyphen (--).
    Returns error message if format is wrong, None if correct.
    """
    if not pages or '--' in pages:
        return None  # Already correct or no pages

    # Check for single dash or other dash characters
    if '-' in pages or '–' in pages or '—' in pages:
        return f"Page range should use double hyphen '--' not single dash: '{pages}'"

    return None


class BibTeXAPIChecker:
    """Validates BibTeX entries against online APIs (Crossref + Semantic Scholar)."""

    def __init__(self, verbose: bool = False, delay: float = 0.05):
        """
        Initialize the API checker.

        Args:
            verbose: Enable verbose output
            delay: Delay between Crossref API queries (default: 0.05s for 20 req/sec)
        """
        self.verbose = verbose
        self.delay = delay
        self.matches = []
        self.mismatches = []
        self.not_found = []
        self.field_mismatches = []  # Track field-level mismatches
        self.suggestions = []  # Track close matches for not-found entries

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

            print("SUGGESTION: Fix syntax errors first using the syntax checker:")
            print(f"  python3 biblatex_syntax_checker.py {filepath}\n")

            print("Then use 'biblatex_cleaner.py' for detailed formatting validation:")
            print(f"  python3 biblatex_cleaner.py {filepath}\n")

            print("After fixing all syntax and formatting issues, use this tool")
            print("(biblatex_diagnostics.py) to validate entries against online APIs.\n")
            print(f"{'='*60}")
            raise

    def save_bibtex(self, bib_data: BibliographyData, filepath: str):
        """Save BibTeX database to file with proper formatting."""
        with open(filepath, 'w', encoding='utf-8') as f:
            for key, entry in bib_data.entries.items():
                # Write entry header
                f.write(f"@{entry.type}{{{key},\n")

                # Collect all items (persons + fields) to determine last item
                items = []

                # Add persons (author, editor, etc.)
                for role, persons in entry.persons.items():
                    if persons:
                        names = []
                        for person in persons:
                            names.append(str(person))
                        author_str = ' and '.join(names)
                        items.append(('person', role, author_str))

                # Add fields
                for field, value in entry.fields.items():
                    items.append(('field', field, value))

                # Write all items with commas except the last
                for idx, (item_type, name, value) in enumerate(items):
                    is_last = (idx == len(items) - 1)
                    comma = '' if is_last else ','

                    # Format value with braces
                    if not value.startswith('{'):
                        value = '{' + value + '}'

                    f.write(f"    {name} = {value}{comma}\n")

                # Close entry
                f.write("}\n\n")

        self.log(f"Saved corrected BibTeX to: {filepath}")

    def _titles_match(self, title1: str, title2: str) -> bool:
        """Check if two titles match using fuzzy matching."""
        # Remove common punctuation and extra spaces
        clean1 = re.sub(r'[^\w\s]', '', title1.lower()).strip()
        clean2 = re.sub(r'[^\w\s]', '', title2.lower()).strip()

        # Calculate Jaccard similarity
        words1 = set(clean1.split())
        words2 = set(clean2.split())

        if not words1 or not words2:
            return False

        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        similarity = intersection / union if union > 0 else 0

        return similarity > 0.7  # 70% similarity threshold

    def _compare_fields(self, key: str, entry: Entry, api_result: Dict, source: str):
        """Compare fields between local entry and API result (BibTeX/BibLaTeX agnostic)."""
        issues = []

        # Check for unclosed LaTeX math mode in title
        if 'title' in entry.fields:
            title = entry.fields['title']
            if check_unclosed_math_mode(title):
                issues.append(f"Unclosed LaTeX math mode ($) in title")

        # Compare DOI
        if 'doi' in entry.fields:
            entry_doi = entry.fields['doi'].lower()
            api_doi = api_result.get('DOI', '').lower() if source == 'crossref' else api_result.get('doi', '').lower()
            if api_doi and entry_doi != api_doi:
                issues.append(f"DOI mismatch: '{entry_doi}' vs '{api_doi}'")

        # Compare year (check both 'year' and 'date' fields - BibTeX/BibLaTeX agnostic)
        entry_year = None
        if 'year' in entry.fields:
            entry_year = entry.fields['year'][:4]
        elif 'date' in entry.fields:
            entry_year = entry.fields['date'][:4]

        if entry_year:
            if source == 'crossref':
                published = api_result.get('published', {}) or api_result.get('published-print', {})
                if published and 'date-parts' in published and published['date-parts']:
                    api_year = str(published['date-parts'][0][0])
                else:
                    api_year = None
            else:  # semantic scholar
                api_year = str(api_result.get('year', '')) if api_result.get('year') else None

            if api_year and entry_year != api_year:
                issues.append(f"Year mismatch: '{entry_year}' vs '{api_year}'")

        # Compare journal/journaltitle (check both - BibTeX/BibLaTeX agnostic)
        entry_journal = entry.fields.get('journal') or entry.fields.get('journaltitle')
        if entry_journal and source == 'crossref':
            api_journal_list = api_result.get('container-title', [])
            if api_journal_list:
                api_journal = api_journal_list[0] if isinstance(api_journal_list, list) else api_journal_list
                # Normalize ampersands for comparison (API returns &amp;, BibTeX uses \&)
                entry_journal_clean = normalize_ampersand(entry_journal.lower().strip())
                api_journal_clean = normalize_ampersand(api_journal.lower().strip())
                if entry_journal_clean != api_journal_clean:
                    issues.append(f"Journal mismatch: '{entry_journal}' vs '{api_journal}'")

        # Check page range format
        if 'pages' in entry.fields:
            page_error = check_page_range_format(entry.fields['pages'])
            if page_error:
                issues.append(page_error)

        # Compare authors (improved with accent handling, particles, and order checking)
        if 'author' in entry.persons:
            entry_authors = entry.persons['author']
            entry_author_count = len(entry_authors)

            # Check for "et al." in author list
            entry_author_str = ' and '.join([str(p) for p in entry_authors])
            if 'et al.' in entry_author_str.lower():
                issues.append("Found 'et al.' in author list - recommend changing to 'and others'")

            # Check for "and others" with too few authors (likely hallucination)
            if 'and others' in entry_author_str.lower() and entry_author_count < 5:
                issues.append(f"Found 'and others' with only {entry_author_count} authors - possible hallucination")

            # Extract entry author components (last name, initials, particles)
            entry_author_info = []
            for person in entry_authors:
                person_str = str(person)
                lastname, initials, particles = extract_author_components(person_str)
                entry_author_info.append({
                    'original': person_str,
                    'lastname': lastname,
                    'initials': initials,
                    'particles': particles
                })

            # Extract API author information
            api_author_info = []
            api_author_count = 0
            if source == 'crossref':
                api_authors = api_result.get('author', [])
                api_author_count = len(api_authors)
                for author in api_authors:
                    given = author.get('given', '')
                    family = author.get('family', '')
                    full_name = f"{given} {family}".strip() if given else family
                    lastname, initials, particles = extract_author_components(full_name)
                    api_author_info.append({
                        'original': full_name,
                        'lastname': lastname,
                        'initials': initials,
                        'particles': particles
                    })
            else:  # semantic scholar
                api_authors = api_result.get('authors', [])
                api_author_count = len(api_authors)
                for author in api_authors:
                    name = author.get('name', '')
                    lastname, initials, particles = extract_author_components(name)
                    api_author_info.append({
                        'original': name,
                        'lastname': lastname,
                        'initials': initials,
                        'particles': particles
                    })

            # Compare author count (show actual author lists)
            if api_author_count and entry_author_count != api_author_count:
                entry_names = ' and '.join([a['original'] for a in entry_author_info])
                api_names = ' and '.join([a['original'] for a in api_author_info])
                issues.append(f"Author count mismatch: '{entry_names}' vs '{api_names}'")

            # Compare author order and details
            if api_author_info and entry_author_info:
                # Check first author match (critical for citation key)
                if len(entry_author_info) > 0 and len(api_author_info) > 0:
                    entry_first = entry_author_info[0]
                    api_first = api_author_info[0]

                    first_author_mismatch = False
                    if entry_first['lastname'] != api_first['lastname']:
                        first_author_mismatch = True
                        issues.append(
                            f"First author mismatch: '{entry_first['original']}' vs '{api_first['original']}' - "
                            f"KEY MAY NEED TO CHANGE"
                        )
                    elif entry_first['initials'] and api_first['initials'] and entry_first['initials'] != api_first['initials']:
                        issues.append(
                            f"First author initials mismatch: '{entry_first['original']}' vs '{api_first['original']}'"
                        )

                # Check for author order issues (compare all authors in sequence)
                max_check = min(len(entry_author_info), len(api_author_info))
                for i in range(max_check):
                    entry_auth = entry_author_info[i]
                    api_auth = api_author_info[i]

                    # Skip if we already reported first author mismatch
                    if i == 0 and first_author_mismatch:
                        continue

                    # Check last name and initials
                    if entry_auth['lastname'] != api_auth['lastname']:
                        # Check if this author appears elsewhere in the list (wrong order)
                        found_elsewhere = False
                        for j, other_api in enumerate(api_author_info):
                            if j != i and entry_auth['lastname'] == other_api['lastname']:
                                issues.append(
                                    f"Author order mismatch at position {i+1}: "
                                    f"'{entry_auth['original']}' should be at position {j+1}"
                                )
                                found_elsewhere = True
                                break

                        if not found_elsewhere:
                            # Author in entry but not in API at any position
                            issues.append(
                                f"Author at position {i+1} not in API: '{entry_auth['original']}' vs '{api_auth['original']}'"
                            )
                    elif entry_auth['initials'] and api_auth['initials'] and entry_auth['initials'] != api_auth['initials']:
                        issues.append(
                            f"Author initials mismatch at position {i+1}: "
                            f"'{entry_auth['original']}' vs '{api_auth['original']}'"
                        )

        if issues:
            self.field_mismatches.append({
                'entry_id': key,
                'source': source,
                'issues': issues
            })

    def check_crossref(self, key: str, entry: Entry, update: bool = False) -> Optional[Entry]:
        """Check entry against Crossref API."""
        title = entry.fields.get('title', '').strip('{}').strip()
        doi = entry.fields.get('doi', '').strip()

        # Get author names for additional search strategies
        author_names = []
        if 'author' in entry.persons:
            for person in entry.persons['author']:
                # Get last name
                person_str = str(person)
                parts = person_str.split()
                if parts:
                    author_names.append(parts[-1])  # Last name

        entry_year = None
        if 'year' in entry.fields:
            entry_year = entry.fields['year'][:4]
        elif 'date' in entry.fields:
            entry_year = entry.fields['date'][:4]

        try:
            search_url = f"{CROSSREF_API_BASE}/works"
            headers = {'User-Agent': f'biblatex-diagnostics/1.0 (mailto:{MAILTO_EMAIL})'}

            # Track seen DOIs across all searches for this entry
            seen_dois = set()

            # STRATEGY 0: Search by DOI if available (most accurate)
            if doi:
                self.log(f"Searching Crossref by DOI: {doi}")
                doi_url = f"{CROSSREF_API_BASE}/works/{doi}"

                try:
                    response = requests.get(doi_url, headers=headers, timeout=10)
                    response.raise_for_status()
                    data = response.json()

                    if data.get('message'):
                        result = data['message']
                        self.log(f"✓ Found by DOI on Crossref")
                        self.matches.append({
                            'entry_id': key,
                            'source': 'crossref',
                            'title': title,
                            'api_title': ''.join(result.get('title', ['']))
                        })
                        # Compare fields
                        self._compare_fields(key, entry, result, 'crossref')
                        if update:
                            return self._crossref_to_entry(result, key, entry.type)
                        return result
                except Exception as e:
                    self.log(f"DOI lookup failed: {str(e)}, falling back to title search")

            # If no DOI or DOI search failed, fall back to title search
            if not title:
                return None

            self.log(f"Searching Crossref for: {title}")

            # Strategy 1: Search by title (get top 5 results)
            params = {
                'query.title': title,
                'rows': 5,  # Get multiple results for suggestions
                'select': 'DOI,title,author,published,container-title,volume,issue,page,publisher,ISBN,ISSN,type'
            }

            response = requests.get(search_url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('message') and data['message'].get('items') and len(data['message']['items']) > 0:
                results = data['message']['items']

                # Check first result for exact match
                first_result = results[0]
                crossref_title = ''.join(first_result.get('title', [''])).lower()
                entry_title = title.lower()

                if self._titles_match(entry_title, crossref_title):
                    self.log(f"✓ Match found on Crossref")
                    self.matches.append({
                        'entry_id': key,
                        'source': 'crossref',
                        'title': title,
                        'api_title': crossref_title
                    })
                    # Compare fields even if not updating
                    self._compare_fields(key, entry, first_result, 'crossref')
                    if update:
                        return self._crossref_to_entry(first_result, key, entry.type)
                    return first_result  # Return result for suggestion purposes
                else:
                    self.log(f"No exact match - generating suggestions")
                    for result in results[:5]:  # Top 5 results
                        doi = result.get('DOI', '')
                        if doi and doi not in seen_dois:
                            seen_dois.add(doi)

                            suggestion_title = ''.join(result.get('title', []))
                            suggestion_authors = []
                            for author in result.get('author', [])[:3]:  # First 3 authors
                                given = author.get('given', '')
                                family = author.get('family', '')
                                if given and family:
                                    suggestion_authors.append(f"{given} {family}")
                                elif family:
                                    suggestion_authors.append(family)

                            # Extract year and journal
                            published = result.get('published', {}) or result.get('published-print', {})
                            suggestion_year = 'N/A'
                            if published and 'date-parts' in published and published['date-parts']:
                                date_parts = published['date-parts'][0]
                                if date_parts and len(date_parts) > 0:
                                    suggestion_year = str(date_parts[0])

                            container_title = result.get('container-title', [])
                            suggestion_journal = container_title[0] if container_title else 'N/A'

                            self.suggestions.append({
                                'entry_id': key,
                                'source': 'crossref',
                                'suggestion': suggestion_title,
                                'authors': ', '.join(suggestion_authors) if suggestion_authors else 'N/A',
                                'year': suggestion_year,
                                'journal': suggestion_journal,
                                'doi': result.get('DOI', 'N/A'),
                                'strategy': 'title_search'
                            })

            # Strategy 2: If we have author names and year, try author + year search
            if author_names and entry_year and not self.matches:
                self.log(f"Trying author+year search: {author_names[0]} {entry_year}")
                query = f"{author_names[0]} {entry_year}"
                params = {
                    'query': query,
                    'rows': 5,
                    'select': 'DOI,title,author,published,container-title,volume,issue,page,publisher,ISBN,ISSN,type'
                }

                response = requests.get(search_url, params=params, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()

                if data.get('message') and data['message'].get('items'):
                    for result in data['message']['items'][:5]:
                        doi = result.get('DOI', '')
                        if doi and doi not in seen_dois:
                            seen_dois.add(doi)

                            suggestion_title = ''.join(result.get('title', []))
                            suggestion_authors = []
                            for author in result.get('author', [])[:3]:
                                given = author.get('given', '')
                                family = author.get('family', '')
                                if given and family:
                                    suggestion_authors.append(f"{given} {family}")
                                elif family:
                                    suggestion_authors.append(family)

                            published = result.get('published', {}) or result.get('published-print', {})
                            suggestion_year = 'N/A'
                            if published and 'date-parts' in published and published['date-parts']:
                                date_parts = published['date-parts'][0]
                                if date_parts and len(date_parts) > 0:
                                    suggestion_year = str(date_parts[0])

                            container_title = result.get('container-title', [])
                            suggestion_journal = container_title[0] if container_title else 'N/A'

                            self.suggestions.append({
                                'entry_id': key,
                                'source': 'crossref',
                                'suggestion': suggestion_title,
                                'authors': ', '.join(suggestion_authors) if suggestion_authors else 'N/A',
                                'year': suggestion_year,
                                'journal': suggestion_journal,
                                'doi': result.get('DOI', 'N/A'),
                                'strategy': 'author_year'
                            })

            # Strategy 3: If we have author names, try searching by author + title keywords
            if author_names and not self.matches:
                self.log(f"Trying author+keywords search with {author_names[0]}")
                # Take key words from title
                title_words = title.lower().split()
                # Remove common words
                stop_words = {'the', 'a', 'an', 'of', 'in', 'on', 'at', 'to', 'for', 'with', 'and', 'or', 'but'}
                key_words = [w for w in title_words if w not in stop_words and len(w) > 3][:3]

                if key_words:
                    query = f"{' '.join(key_words)} {author_names[0]}"
                    params = {
                        'query': query,
                        'rows': 3,
                        'select': 'DOI,title,author,published,container-title,volume,issue,page,publisher,ISBN,ISSN,type'
                    }

                    response = requests.get(search_url, params=params, headers=headers, timeout=10)
                    response.raise_for_status()
                    data = response.json()

                    if data.get('message') and data['message'].get('items'):
                        for result in data['message']['items'][:3]:
                            doi = result.get('DOI', '')
                            if doi and doi not in seen_dois:
                                seen_dois.add(doi)

                                suggestion_title = ''.join(result.get('title', []))
                                suggestion_authors = []
                                for author in result.get('author', [])[:3]:
                                    given = author.get('given', '')
                                    family = author.get('family', '')
                                    if given and family:
                                        suggestion_authors.append(f"{given} {family}")
                                    elif family:
                                        suggestion_authors.append(family)

                                published = result.get('published', {}) or result.get('published-print', {})
                                suggestion_year = 'N/A'
                                if published and 'date-parts' in published and published['date-parts']:
                                    date_parts = published['date-parts'][0]
                                    if date_parts and len(date_parts) > 0:
                                        suggestion_year = str(date_parts[0])

                                container_title = result.get('container-title', [])
                                suggestion_journal = container_title[0] if container_title else 'N/A'

                                self.suggestions.append({
                                    'entry_id': key,
                                    'source': 'crossref',
                                    'suggestion': suggestion_title,
                                    'authors': ', '.join(suggestion_authors) if suggestion_authors else 'N/A',
                                    'year': suggestion_year,
                                    'journal': suggestion_journal,
                                    'doi': result.get('DOI', 'N/A'),
                                    'strategy': 'author_keywords'
                                })

            return None
        except Exception as e:
            self.log(f"Crossref error: {str(e)}")

        return None

    def check_semantic_scholar(self, key: str, entry: Entry, update: bool = False) -> Optional[Entry]:
        """Check entry against Semantic Scholar API."""
        title = entry.fields.get('title', '').strip('{}').strip()
        if not title:
            return None

        self.log(f"Searching Semantic Scholar for: {title}")

        try:
            search_url = f"{SEMANTIC_SCHOLAR_API_BASE}/paper/search"
            params = {
                'query': title,
                'limit': 1,
                'fields': 'title,authors,year,venue,doi,publicationTypes,externalIds'
            }
            headers = {'User-Agent': 'biblatex-diagnostics/1.0'}
            if SEMANTIC_SCHOLAR_API_KEY:
                headers['x-api-key'] = SEMANTIC_SCHOLAR_API_KEY

            response = requests.get(search_url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('data') and len(data['data']) > 0:
                result = data['data'][0]
                ss_title = result.get('title', '').lower()
                entry_title = title.lower()

                if self._titles_match(entry_title, ss_title):
                    self.log(f"✓ Match found on Semantic Scholar")
                    self.matches.append({
                        'entry_id': key,
                        'source': 'semantic_scholar',
                        'title': title,
                        'api_title': ss_title
                    })
                    # Compare fields even if not updating
                    self._compare_fields(key, entry, result, 'semantic_scholar')
                    if update:
                        return self._semantic_scholar_to_entry(result, key, entry.type)
                else:
                    self.log(f"Title mismatch")
                    self.mismatches.append({
                        'entry_id': key,
                        'title': title,
                        'api_title': ss_title
                    })
            else:
                self.log(f"Not found on Semantic Scholar")

        except Exception as e:
            self.log(f"Semantic Scholar error: {str(e)}")

        return None

    def _crossref_to_entry(self, crossref_result: Dict, entry_key: str, entry_type: str) -> Entry:
        """Convert Crossref result to pybtex Entry format."""
        # Determine entry type - prefer original type when sensible
        cr_type = crossref_result.get('type', '').lower()
        container_title = crossref_result.get('container-title', [])

        # If there's a container-title, it's likely an article/chapter, not a book
        # Preserve the original type in these cases
        if container_title and entry_type in ['article', 'inproceedings', 'incollection']:
            etype = entry_type
        else:
            # Otherwise use Crossref's type mapping
            type_mapping = {
                'journal-article': 'article',
                'proceedings-article': 'inproceedings',
                'book-chapter': 'incollection',
                'book': 'book',
                'monograph': 'book',
                'dissertation': 'phdthesis',
                'report': 'techreport',
            }
            etype = type_mapping.get(cr_type, entry_type or 'article')

        # Create fields
        title = ''.join(crossref_result.get('title', []))
        fields = {'title': '{' + title + '}'}

        # Add year
        published = crossref_result.get('published', {}) or crossref_result.get('published-print', {})
        if published and 'date-parts' in published and published['date-parts']:
            date_parts = published['date-parts'][0]
            if date_parts and len(date_parts) > 0:
                fields['year'] = str(date_parts[0])

        # Add journal/booktitle
        container_title = crossref_result.get('container-title', [])
        if container_title:
            container = container_title[0] if isinstance(container_title, list) else container_title
            if etype == 'article':
                fields['journaltitle'] = container
            elif etype in ['inproceedings', 'incollection']:
                fields['booktitle'] = container

        # Add volume, number, pages
        if 'volume' in crossref_result:
            fields['volume'] = str(crossref_result['volume'])
        if 'issue' in crossref_result:
            fields['number'] = str(crossref_result['issue'])
        if 'page' in crossref_result:
            fields['pages'] = crossref_result['page']

        # Add publisher and DOI
        if 'publisher' in crossref_result:
            fields['publisher'] = crossref_result['publisher']
        if 'DOI' in crossref_result:
            fields['doi'] = crossref_result['DOI']

        # Add ISBN/ISSN
        if 'ISBN' in crossref_result and crossref_result['ISBN']:
            fields['isbn'] = crossref_result['ISBN'][0] if isinstance(crossref_result['ISBN'], list) else crossref_result['ISBN']
        if 'ISSN' in crossref_result and crossref_result['ISSN']:
            fields['issn'] = crossref_result['ISSN'][0] if isinstance(crossref_result['ISSN'], list) else crossref_result['ISSN']

        # Handle authors
        persons = {}
        if 'author' in crossref_result and crossref_result['author']:
            author_list = []
            for author in crossref_result['author']:
                given = author.get('given', '')
                family = author.get('family', '')
                if given and family:
                    author_list.append(Person(f"{given} {family}"))
                elif family:
                    author_list.append(Person(family))
            if author_list:
                persons['author'] = author_list

        return Entry(etype, fields=fields, persons=persons)

    def _semantic_scholar_to_entry(self, ss_result: Dict, entry_key: str, entry_type: str) -> Entry:
        """Convert Semantic Scholar result to pybtex Entry format."""
        # Determine entry type
        pub_types = ss_result.get('publicationTypes', [])
        if 'JournalArticle' in pub_types:
            etype = 'article'
        elif 'Conference' in pub_types or 'ConferencePaper' in pub_types:
            etype = 'inproceedings'
        elif 'Book' in pub_types:
            etype = 'book'
        else:
            etype = entry_type or 'article'

        # Create fields
        fields = {'title': '{' + ss_result.get('title', '') + '}'}

        # Add year and venue
        if 'year' in ss_result and ss_result['year']:
            fields['year'] = str(ss_result['year'])
        if 'venue' in ss_result and ss_result['venue']:
            if etype == 'article':
                fields['journaltitle'] = ss_result['venue']
            elif etype == 'inproceedings':
                fields['booktitle'] = ss_result['venue']

        # Add DOI and arXiv
        if 'doi' in ss_result and ss_result['doi']:
            fields['doi'] = ss_result['doi']
        external_ids = ss_result.get('externalIds', {})
        if external_ids.get('ArXiv'):
            fields['eprint'] = external_ids['ArXiv']
            fields['eprinttype'] = 'arxiv'

        # Handle authors
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

    def validate_all_entries(self, bib_data: BibliographyData):
        """Validate all entries against APIs."""
        total = len(bib_data.entries)
        print(f"\nValidating {total} entries against APIs...")
        print("=" * 60)

        for idx, (key, entry) in enumerate(bib_data.entries.items(), 1):
            print(f"\n[{idx}/{total}] Checking: {key}")

            # Try Crossref first
            crossref_found = self.check_crossref(key, entry, update=False)
            time.sleep(self.delay)

            # Fallback to Semantic Scholar if Crossref didn't find it
            if not crossref_found and not any(m['entry_id'] == key and m['source'] == 'crossref' for m in self.matches):
                self.check_semantic_scholar(key, entry, update=False)
                time.sleep(1.0 if SEMANTIC_SCHOLAR_API_KEY else 5.0)

            # Track if not found in either
            if not any(m['entry_id'] == key for m in self.matches):
                self.not_found.append(key)

    def update_with_apis(self, bib_data: BibliographyData) -> BibliographyData:
        """Update entries with API data."""
        total = len(bib_data.entries)
        print(f"\nUpdating {total} entries with API data...")
        print("=" * 60)

        updated_count = 0
        crossref_count = 0
        semantic_scholar_count = 0

        for idx, (key, entry) in enumerate(list(bib_data.entries.items()), 1):
            print(f"\n[{idx}/{total}] Processing: {key}")

            # Try Crossref first
            updated_entry = self.check_crossref(key, entry, update=True)
            if updated_entry:
                crossref_count += 1
                print(f"  ✓ Updated with Crossref data")
            time.sleep(self.delay)

            # Fallback to Semantic Scholar
            if not updated_entry:
                updated_entry = self.check_semantic_scholar(key, entry, update=True)
                if updated_entry:
                    semantic_scholar_count += 1
                    print(f"  ✓ Updated with Semantic Scholar data")
                time.sleep(1.0 if SEMANTIC_SCHOLAR_API_KEY else 5.0)

            if updated_entry:
                bib_data.entries[key] = updated_entry
                updated_count += 1
            else:
                print(f"  ✗ No update available")

        print(f"\n{'=' * 60}")
        print(f"Updated {updated_count}/{total} entries")
        print(f"  - Crossref: {crossref_count}")
        print(f"  - Semantic Scholar: {semantic_scholar_count}")

        return bib_data

    def _rank_suggestions(self, entry_id: str, entry_suggestions: List[Dict], bib_data: BibliographyData) -> List[Dict]:
        """
        Rank suggestions by relevance (first author match, title similarity, year).

        Args:
            entry_id: The BibTeX entry ID
            entry_suggestions: List of suggestion dictionaries
            bib_data: The BibTeX database to get entry details

        Returns:
            Sorted list of suggestions (most relevant first)
        """
        if entry_id not in bib_data.entries:
            return entry_suggestions

        entry = bib_data.entries[entry_id]

        # Get entry's first author last name
        entry_first_author_lastname = None
        if 'author' in entry.persons and len(entry.persons['author']) > 0:
            first_author_str = str(entry.persons['author'][0])
            entry_first_author_lastname, _, _ = extract_author_components(first_author_str)

        # Get entry's year
        entry_year = None
        if 'year' in entry.fields:
            entry_year = entry.fields['year'][:4]
        elif 'date' in entry.fields:
            entry_year = entry.fields['date'][:4]

        # Get entry's title
        entry_title = entry.fields.get('title', '').strip('{}').strip().lower()

        # Calculate score for each suggestion
        scored_suggestions = []
        for sug in entry_suggestions:
            score = 0

            # Check first author match (highest priority: +100 points)
            sug_authors_str = sug.get('authors', '')
            if sug_authors_str and sug_authors_str != 'N/A':
                # Get first author from suggestion
                first_sug_author = sug_authors_str.split(',')[0].strip()
                sug_first_lastname, _, _ = extract_author_components(first_sug_author)

                if entry_first_author_lastname and sug_first_lastname:
                    if entry_first_author_lastname == sug_first_lastname:
                        score += 100  # Same first author
                    elif entry_first_author_lastname in sug_first_lastname or sug_first_lastname in entry_first_author_lastname:
                        score += 50  # Partial match

            # Check title similarity (+50 points for good match)
            sug_title = sug.get('suggestion', '').lower()
            if entry_title and sug_title:
                # Calculate word overlap
                entry_words = set(re.sub(r'[^\w\s]', '', entry_title).split())
                sug_words = set(re.sub(r'[^\w\s]', '', sug_title).split())
                if entry_words and sug_words:
                    overlap = len(entry_words & sug_words) / len(entry_words | sug_words)
                    score += int(overlap * 50)

            # Check year match (+30 points)
            sug_year = sug.get('year', 'N/A')
            if entry_year and sug_year != 'N/A' and str(entry_year) == str(sug_year):
                score += 30

            # Bonus points for certain search strategies
            strategy = sug.get('strategy', '')
            if strategy == 'author_year':
                score += 10
            elif strategy == 'author_keywords':
                score += 5

            scored_suggestions.append((score, sug))

        # Sort by score (highest first)
        scored_suggestions.sort(key=lambda x: x[0], reverse=True)

        # Return just the suggestions (without scores)
        return [sug for score, sug in scored_suggestions]

    def generate_report(self, bib_data: Optional[BibliographyData] = None) -> str:
        """Generate validation report."""
        report = []
        report.append("\n" + "=" * 60)
        report.append("BIBTEX API VALIDATION REPORT")
        report.append("=" * 60)

        report.append(f"\nMatches: {len(self.matches)}")
        for match in self.matches:
            report.append(f"  ✓ {match['entry_id']}: Found on {match['source']}")

        if self.field_mismatches:
            report.append(f"\nField Mismatches: {len(self.field_mismatches)}")
            for fm in self.field_mismatches:
                report.append(f"  ⚠ {fm['entry_id']} ({fm['source']}):")
                for issue in fm['issues']:
                    report.append(f"      - {issue}")

        if self.mismatches:
            report.append(f"\nTitle Mismatches: {len(self.mismatches)}")
            for mm in self.mismatches:
                report.append(f"  ⚠ {mm['entry_id']}: '{mm['title']}' != '{mm['api_title']}'")

        if self.not_found:
            report.append(f"\nNot Found: {len(self.not_found)}")
            for nf in self.not_found:
                report.append(f"  ✗ {nf}: Not found in any API")

        if self.suggestions:
            report.append(f"\nSuggestions (possible matches): {len(self.suggestions)}")
            # Group suggestions by entry_id
            by_entry = {}
            for sug in self.suggestions:
                entry_id = sug['entry_id']
                if entry_id not in by_entry:
                    by_entry[entry_id] = []
                by_entry[entry_id].append(sug)

            for entry_id, entry_suggestions in by_entry.items():
                # Rank suggestions if we have bib_data
                if bib_data:
                    entry_suggestions = self._rank_suggestions(entry_id, entry_suggestions, bib_data)

                report.append(f"\n  💡 {entry_id} - Did you mean one of these?")
                for idx, sug in enumerate(entry_suggestions[:5], 1):  # Show up to 5 suggestions
                    report.append(f"      [{idx}] {sug['suggestion']}")
                    report.append(f"          Authors: {sug['authors']}")
                    report.append(f"          Year: {sug['year']}")
                    report.append(f"          Journal: {sug['journal']}")
                    report.append(f"          DOI: {sug['doi']}")
                    strategy_label = sug.get('strategy', 'title_search')
                    report.append(f"          (Found via: {strategy_label})")

        report.append("\n" + "=" * 60)
        return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(
        description='BibTeX API Diagnostics - Compare entries against Crossref and Semantic Scholar',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate all entries against APIs
  python biblatex_diagnostics.py input.bib

  # Update entries with API data
  python biblatex_diagnostics.py input.bib --update -o corrected.bib

  # Save validation report to file
  python biblatex_diagnostics.py input.bib -r report.txt
        """
    )

    parser.add_argument('input_file', help='Input BibTeX file')
    parser.add_argument('-o', '--output', help='Output file for corrected BibTeX')
    parser.add_argument('-r', '--report-file', help='Save validation report to file')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--delay', type=float, default=0.05,
                       help='Delay between Crossref queries (default: 0.05s for 20 req/sec)')
    parser.add_argument('--update', action='store_true',
                       help='Update entries with API data (requires -o)')

    args = parser.parse_args()

    if args.update and not args.output:
        parser.error("--update requires -o/--output")

    # Initialize checker
    checker = BibTeXAPIChecker(verbose=args.verbose, delay=args.delay)

    try:
        # Load BibTeX file
        bib_data = checker.load_bibtex(args.input_file)

        if args.update:
            # Update mode
            bib_data = checker.update_with_apis(bib_data)
            checker.save_bibtex(bib_data, args.output)
            print(f"\n✓ Corrected BibTeX saved to: {args.output}")
        else:
            # Validation mode
            checker.validate_all_entries(bib_data)

        # Generate report
        report = checker.generate_report(bib_data)
        if args.report_file:
            with open(args.report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\n✓ Validation report saved to: {args.report_file}")
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
