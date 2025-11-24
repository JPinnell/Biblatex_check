#!/usr/bin/env python3
"""
BibTeX API Diagnostics Tool
Validates and corrects BibTeX entries by comparing against online sources (Crossref, Semantic Scholar, and Scholarly).
"""

import re
import sys
import os
import time
import random
import argparse
import requests
import unicodedata
from typing import Dict, List, Optional, Tuple
from pybtex.database import parse_file, BibliographyData, Entry, Person
from pybtex.database.output.bibtex import Writer

# Try to import scholarly (optional dependency)
try:
    from scholarly import scholarly, ProxyGenerator
    SCHOLARLY_AVAILABLE = True
except ImportError:
    SCHOLARLY_AVAILABLE = False
    scholarly = None
    ProxyGenerator = None

# Crossref API endpoint (primary)
CROSSREF_API_BASE = "https://api.crossref.org"
MAILTO_EMAIL = os.environ.get('CROSSREF_MAILTO', 'research@example.com')

# Semantic Scholar API endpoint (fallback)
SEMANTIC_SCHOLAR_API_BASE = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_API_KEY = os.environ.get('SEMANTIC_SCHOLAR_API_KEY', None)

# Name particles that should be ignored when comparing/sorting author names
NAME_PARTICLES = {'von', 'van', 'de', 'del', 'della', 'di', 'du', 'le', 'la', 'da', 'dos', 'das', 'ten', 'ter', 'den', 'der'}
NAME_SUFFIXES = {'jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv', 'v'}
SKIPPED_ENTRY_TYPES = {'phdthesis', 'misc', 'online'}


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


def remove_accents(text: str) -> str:
    """
    Remove accents from Unicode string and normalize special characters.

    Handles both combining accents (NFD decomposition) and special base characters
    like ø, æ, œ that don't decompose in NFD.
    """
    # First, replace special Unicode characters that don't decompose in NFD
    # These are distinct base characters, not letter + combining mark
    special_unicode_chars = {
        'ø': 'o', 'Ø': 'O',
        'æ': 'ae', 'Æ': 'AE',
        'œ': 'oe', 'Œ': 'OE',
        'å': 'a', 'Å': 'A',
        'ß': 'ss',
        'ð': 'd', 'Ð': 'D',
        'þ': 'th', 'Þ': 'TH',
        'ł': 'l', 'Ł': 'L',
    }

    for char, replacement in special_unicode_chars.items():
        text = text.replace(char, replacement)

    # Normalize to NFD (decomposed form) to handle combining accents
    nfd = unicodedata.normalize('NFD', text)
    # Filter out combining characters (accents)
    return ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')


def normalize_latex_text(text: str) -> str:
    """
    Normalize LaTeX text by converting LaTeX accents to their Unicode equivalents,
    then removing accents and punctuation for comparison.

    Examples:
        g{\\'e}r{\\^o}me -> gérôme -> gerome
        \\"{o} -> ö -> o
        Rosales-Guzmán -> RosalesGuzman
        Berg-Sørensen -> BergSorensen
        Berg-S{\\o}rensen -> BergSorensen
    """
    # Special LaTeX characters (must be handled before accent commands)
    # These are complete character replacements, not accents
    special_chars = {
        r'{\o}': 'o',
        r'\o{}': 'o',
        r'\o ': 'o',
        r'\o': 'o',
        r'{\O}': 'O',
        r'\O{}': 'O',
        r'\O ': 'O',
        r'\O': 'O',
        r'{\aa}': 'aa',
        r'\aa{}': 'aa',
        r'\aa ': 'aa',
        r'\aa': 'aa',
        r'{\AA}': 'AA',
        r'\AA{}': 'AA',
        r'\AA ': 'AA',
        r'\AA': 'AA',
        r'{\ae}': 'ae',
        r'\ae{}': 'ae',
        r'\ae ': 'ae',
        r'\ae': 'ae',
        r'{\AE}': 'AE',
        r'\AE{}': 'AE',
        r'\AE ': 'AE',
        r'\AE': 'AE',
        r'{\oe}': 'oe',
        r'\oe{}': 'oe',
        r'\oe ': 'oe',
        r'\oe': 'oe',
        r'{\OE}': 'OE',
        r'\OE{}': 'OE',
        r'\OE ': 'OE',
        r'\OE': 'OE',
        r'{\ss}': 'ss',
        r'\ss{}': 'ss',
        r'\ss ': 'ss',
        r'\ss': 'ss',
    }

    # Dotless base characters that are often combined with accent commands
    base_letters = {
        r'\i': 'i',
        r'\j': 'j',
        r'\l': 'l',
        r'\L': 'L',
    }

    # Replace special characters (order matters - longer patterns first)
    for latex_cmd, replacement in special_chars.items():
        text = text.replace(latex_cmd, replacement)

    # Replace base letters so accent removal works on LaTeX sequences like {\'{\i}}
    for base_cmd, replacement in base_letters.items():
        text = text.replace(base_cmd, replacement)

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

    # Handle braced accent commands like {\'e}
    for cmd in latex_accents.keys():
        # Match patterns like {\cmd{letter}} or {\\cmd letter}
        text = re.sub(r'\{' + re.escape(cmd) + r'\{([a-zA-Z])\}\}', r'\1', text)
        text = re.sub(r'\{' + re.escape(cmd) + r'([a-zA-Z])\}', r'\1', text)
        text = re.sub(re.escape(cmd) + r'\{([a-zA-Z])\}', r'\1', text)
        text = re.sub(re.escape(cmd) + r'([a-zA-Z])', r'\1', text)

    # Remove any remaining braces
    text = text.replace('{', '').replace('}', '')

    # Remove accents from any Unicode characters (handles Unicode like ø, ö, ä, etc.)
    text = remove_accents(text)

    # Remove hyphens, apostrophes, and other punctuation that shouldn't affect name matching
    # This helps match 'Rosales-Guzmán' with 'RosalesGuzman' in citation keys
    text = re.sub(r'[-\'`]', '', text)

    return text


def normalize_ampersand(text: str) -> str:
    """Normalize ampersands for comparison: &amp; -> & and \\& -> &"""
    text = text.replace('&amp;', '&')
    text = text.replace('\\&', '&')
    return text


def clean_api_field(text: str) -> str:
    """
    Clean up field values imported from APIs.
    Replaces HTML entities like &amp; with LaTeX equivalents like \\&.
    """
    if not isinstance(text, str):
        return text
    # Replace &amp; with \&
    text = text.replace('&amp;', '\\&')
    return text


def normalize_journal_name(journal: str) -> str:
    """
    Normalize journal name for comparison by:
    - Converting to lowercase
    - Removing LaTeX braces
    - Normalizing ampersands
    - Removing periods (for abbreviation matching)
    - Removing leading 'The'
    - Stripping whitespace

    Examples:
        '{IBM} Journal' -> 'ibm journal'
        'The Physics of Fluids' -> 'physics of fluids'
        'Particle {\\&} Systems' -> 'particle & systems'
        'Phys. Chem. Chem. Phys.' -> 'phys chem chem phys'
        'J. of Electrical Engineering' -> 'j of electrical engineering'
    """
    # Convert to lowercase
    journal = journal.lower()

    # Remove LaTeX braces
    journal = journal.replace('{', '').replace('}', '')

    # Normalize ampersands
    journal = normalize_ampersand(journal)

    # Remove periods (helps with abbreviation matching)
    journal = journal.replace('.', '')

    # Remove leading 'The ' or 'the '
    journal = journal.strip()
    if journal.startswith('the '):
        journal = journal[4:].strip()

    # Normalize whitespace
    journal = ' '.join(journal.split())

    return journal


def journals_match_fuzzy(journal1: str, journal2: str, threshold: float = 0.6) -> bool:
    """
    Compare two journal names with fuzzy matching to handle:
    - Abbreviations (e.g., 'Lab on a Chip' vs 'Lab Chip', 'Phys. Chem.' vs 'Physical Chemistry')
    - Articles ('The Physics of Fluids' vs 'Physics of Fluids')
    - Formatting differences (braces, ampersands, periods)

    Args:
        journal1: First journal name
        journal2: Second journal name
        threshold: Similarity threshold (0.0 to 1.0), default lowered to 0.6 for abbreviations

    Returns:
        True if journals match within threshold
    """
    # Normalize both journal names
    norm1 = normalize_journal_name(journal1)
    norm2 = normalize_journal_name(journal2)

    # Exact match after normalization
    if norm1 == norm2:
        return True

    # Calculate Jaccard similarity for fuzzy matching
    words1 = set(norm1.split())
    words2 = set(norm2.split())

    if not words1 or not words2:
        return False

    # Filter out common words that don't help distinguish journals
    stop_words = {'of', 'the', 'and', 'for', 'in', 'on'}
    words1_filtered = words1 - stop_words
    words2_filtered = words2 - stop_words

    # Check for exact word matches
    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))
    similarity = intersection / union if union > 0 else 0

    # Check if one is a substring of the other (for abbreviations)
    # e.g., "Lab Chip" is contained in "Lab on a Chip"
    if norm1 in norm2 or norm2 in norm1:
        # If one is substring of the other, be more lenient
        return similarity > 0.4

    # For abbreviations where all words of the shorter match the longer
    # e.g., "Lab Chip" vs "Lab on a Chip" - all words of "Lab Chip" are in "Lab on a Chip"
    smaller_set = words1 if len(words1) < len(words2) else words2
    larger_set = words2 if len(words1) < len(words2) else words1

    # If all words from the smaller set are in the larger set, accept it
    if smaller_set.issubset(larger_set):
        return True

    # Check for abbreviation matches: if words start with the same letters
    # e.g., 'phys' matches 'physical', 'chem' matches 'chemistry', 'j' matches 'journal'
    abbrev_matches = 0
    for w1 in words1_filtered:
        for w2 in words2_filtered:
            # Check if one is a prefix of the other
            # Allow single-letter abbreviations (e.g., 'j' for 'journal')
            if w1.startswith(w2) or w2.startswith(w1):
                # For very short words (1-2 chars), only match if it's the first letter
                min_len = min(len(w1), len(w2))
                max_len = max(len(w1), len(w2))
                if min_len <= 2 and max_len > 2:
                    # Short abbreviation - check if shorter word matches start of longer word
                    shorter = w1 if len(w1) < len(w2) else w2
                    longer = w2 if len(w1) < len(w2) else w1
                    if longer.startswith(shorter):
                        abbrev_matches += 1
                        break
                else:
                    # Regular prefix match
                    abbrev_matches += 1
                    break

    # If we have good abbreviation matches, be more lenient
    if abbrev_matches >= min(len(words1_filtered), len(words2_filtered)) * 0.5:
        return True

    return similarity >= threshold


def authors_initials_match(initials1: str, initials2: str) -> bool:
    """
    Check if two sets of initials match, being lenient with:
    - Full first name vs initials (e.g., 'S' matches 'Scot' or 'SC')
    - Different numbers of initials (e.g., 'S' matches 'SC')

    Args:
        initials1: First set of initials (e.g., 'S', 'SC', 'SJC')
        initials2: Second set of initials

    Returns:
        True if initials are compatible
    """
    # If either is empty, we can't compare
    if not initials1 or not initials2:
        return True  # Be lenient when initials are missing

    # Normalize to uppercase
    i1 = initials1.upper().replace('.', '').replace(' ', '')
    i2 = initials2.upper().replace('.', '').replace(' ', '')

    # Exact match
    if i1 == i2:
        return True

    # Check if one is a prefix of the other
    # e.g., 'S' matches 'SC' (first initial matches)
    if i1.startswith(i2) or i2.startswith(i1):
        return True

    # Check if they share at least the first initial
    if i1[0] == i2[0]:
        return True

    return False


def normalize_with_transliterations(text: str) -> List[str]:
    """
    Generate multiple normalized versions of text to handle common transliterations.

    German/Scandinavian transliterations:
        ö -> o or oe
        ä -> a or ae
        ü -> u or ue
        ø -> o or oe
        å -> a or aa

    Returns:
        List of normalized variants (always includes the base normalized version)
        For names in "Last, First" format, returns both full name and last name only variants

    Examples:
        'Engström' -> ['engstrom', 'engstroem']
        'Müller' -> ['muller', 'mueller']
        'Engström, David' -> ['engstrom, david', 'engstroem, david', 'engstrom', 'engstroem']
    """
    # Base normalization
    base = normalize_latex_text(text).lower()
    variants = [base]

    # If this is a "Last, First" format, also extract just the last name
    if ',' in text:
        lastname_only = text.split(',')[0].strip()
        lastname_base = normalize_latex_text(lastname_only).lower()
        if lastname_base not in variants:
            variants.append(lastname_base)

    # Generate transliterated variants by replacing normalized vowels with their transliterations
    # We check the original text for these characters before normalization
    original_lower = text.lower()

    # Check if original had special characters that might have transliterations
    has_special = any(c in original_lower for c in ['ö', 'ä', 'ü', 'ø', 'å', 'œ'])

    if has_special:
        # Create variant with German/Scandinavian transliterations
        # Start with the original and apply transliterations before other normalization
        variant = text
        variant = variant.replace('ö', 'oe').replace('Ö', 'Oe')
        variant = variant.replace('ä', 'ae').replace('Ä', 'Ae')
        variant = variant.replace('ü', 'ue').replace('Ü', 'Ue')
        variant = variant.replace('ø', 'oe').replace('Ø', 'Oe')
        variant = variant.replace('å', 'aa').replace('Å', 'Aa')
        variant = variant.replace('œ', 'oe').replace('Œ', 'Oe')
        # Now normalize the variant (remove LaTeX, hyphens, etc.)
        variant = re.sub(r'[-\'`]', '', variant).lower()
        if variant != base and variant not in variants:
            variants.append(variant)

        # Also add just the last name variant if in "Last, First" format
        if ',' in variant:
            lastname_variant = variant.split(',')[0].strip()
            if lastname_variant not in variants:
                variants.append(lastname_variant)

    return variants


def extract_citation_key_components(citation_key: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract author last name and year from citation key.

    Common patterns:
        - AuthorYEAR (e.g., Smith2020, deFornel2012)
        - Author_YEAR (e.g., Smith_2020)
        - AuthorYEARkeyword (e.g., Smith2020quantum)

    Returns:
        (author_lastname, year) tuple, or (None, None) if pattern not recognized
    """
    # Pattern 1: Look for 4-digit year (1900-2099)
    year_match = re.search(r'(19|20)\d{2}', citation_key)
    if not year_match:
        return (None, None)

    year = year_match.group(0)
    year_pos = year_match.start()

    # Extract author name before the year
    author_part = citation_key[:year_pos].rstrip('_-')
    if not author_part:
        return (None, None)

    # Normalize the author name (remove accents, lowercase)
    author_normalized = normalize_latex_text(author_part).lower()

    return (author_normalized, year)


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

        # Handle particles in comma-separated format (e.g., "de Fornel, F.")
        # Split last_part to check for leading particles
        last_parts_words = last_part.split()
        if len(last_parts_words) > 1:
            # Check if any leading words are particles
            particle_count = 0
            for word in last_parts_words[:-1]:  # All words except the last
                if word.lower() in NAME_PARTICLES:
                    particles.append(word.lower())
                    particle_count += 1
                else:
                    break  # Stop at first non-particle

            # Update last_part to exclude particles
            if particle_count > 0:
                last_part = ' '.join(last_parts_words[particle_count:])
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
                # Check if this part is grouped initials (e.g., "NC", "ABC")
                # Grouped initials are: all uppercase, 2-4 letters, no dots
                part_no_dots = part.replace('.', '')
                if len(part_no_dots) >= 2 and len(part_no_dots) <= 4 and part_no_dots.isupper():
                    # This appears to be grouped initials - add each letter
                    initials += part_no_dots
                else:
                    # Regular name part - add first letter only
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
    """Validates BibTeX entries against online APIs (Crossref + Semantic Scholar + Scholarly)."""

    def __init__(self, verbose: bool = False, delay: float = 0.05, use_scholarly: bool = True):
        """
        Initialize the API checker.

        Args:
            verbose: Enable verbose output
            delay: Delay between Crossref API queries (default: 0.05s for 20 req/sec)
            use_scholarly: Enable Scholarly API (requires scholarly package)
        """
        self.verbose = verbose
        self.delay = delay
        self.use_scholarly = use_scholarly and SCHOLARLY_AVAILABLE
        self.matches = []
        self.mismatches = []
        self.not_found = []
        self.field_mismatches = []  # Track field-level mismatches
        self.suggestions = []  # Track close matches for not-found entries
        self.scholarly_session_active = False  # Track if Scholarly session is active

        # Initialize Scholarly session once (keep session alive for multiple queries)
        if self.use_scholarly:
            try:
                self.log("Initializing Scholarly session (without proxy for direct access)...")
                # Don't use proxy - user mentioned they don't have one
                # Just initialize the scholarly session once and keep it alive
                self.scholarly_session_active = True
                self.log("Scholarly session initialized successfully")
            except Exception as e:
                self.log(f"Warning: Could not initialize Scholarly session: {e}")
                self.use_scholarly = False
                self.scholarly_session_active = False

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
        """
        Save BibTeX database to file preserving original formatting.
        CRITICAL: Does NOT modify any existing field values - writes them exactly as stored.
        """
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

                # Add fields - preserve EXACT values, don't modify braces
                for field, value in entry.fields.items():
                    items.append(('field', field, value))

                # Write all items with commas except the last
                for idx, (item_type, name, value) in enumerate(items):
                    is_last = (idx == len(items) - 1)
                    comma = '' if is_last else ','

                    # Write value EXACTLY as it is stored - DO NOT add/remove braces
                    # The value is already in the correct format from the original file
                    f.write(f"    {name} = {{{value}}}{comma}\n")

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

        # Extract citation key components (author and year)
        key_author, key_year = extract_citation_key_components(key)

        # Check for unclosed LaTeX math mode in title
        if 'title' in entry.fields:
            title = entry.fields['title']
            if check_unclosed_math_mode(title):
                issues.append(f"Unclosed LaTeX math mode ($) in title")

        # Determine if we should skip DOI checking
        # Skip for: pre-1950 papers, phdthesis, book, misc entries
        entry_year_int = None
        if 'year' in entry.fields:
            try:
                entry_year_int = int(entry.fields['year'][:4])
            except (ValueError, TypeError):
                pass
        elif 'date' in entry.fields:
            try:
                entry_year_int = int(entry.fields['date'][:4])
            except (ValueError, TypeError):
                pass

        skip_doi_check = (
            (entry_year_int is not None and entry_year_int < 1950) or
            entry.type.lower() in ['phdthesis', 'book', 'misc']
        )

        # Compare DOI (but skip for certain entry types and old papers)
        if 'doi' in entry.fields and not skip_doi_check:
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

            # Check if citation key year matches entry year
            if key_year and entry_year != key_year:
                issues.append(f"Citation key year mismatch: key contains '{key_year}' but entry has year '{entry_year}'")

        # Compare journal/journaltitle (check both - BibTeX/BibLaTeX agnostic)
        entry_journal = entry.fields.get('journal') or entry.fields.get('journaltitle')
        if entry_journal and source == 'crossref':
            api_journal_list = api_result.get('container-title', [])
            if api_journal_list:
                api_journal = api_journal_list[0] if isinstance(api_journal_list, list) else api_journal_list
                # Use fuzzy matching to handle abbreviations, "The" prefix, and formatting differences
                if not journals_match_fuzzy(entry_journal, api_journal):
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
            # Note: "others" is counted as an author by pybtex, so we need to exclude it
            # Flag if there are 5 or fewer REAL authors (not counting "others")
            if 'and others' in entry_author_str.lower():
                # Count real authors (excluding "others")
                real_author_count = sum(1 for p in entry_authors if str(p).lower() != 'others')
                if real_author_count <= 5:
                    issues.append(f"Found 'and others' with only {real_author_count} real authors - possible hallucination")

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
            elif source == 'semantic_scholar':
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
            elif source == 'scholarly':
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
            # Skip count comparison if entry has "and others" (indicates truncated author list)
            has_others = any(a['lastname'] == 'others' for a in entry_author_info)
            if api_author_count and entry_author_count != api_author_count and not has_others:
                entry_names = ' and '.join([a['original'] for a in entry_author_info])
                api_names = ' and '.join([a['original'] for a in api_author_info])
                issues.append(f"Author count mismatch: '{entry_names}' vs '{api_names}'")

            # Compare author order and details
            if api_author_info and entry_author_info:
                # Check first author match (critical for citation key)
                # Skip if first author is "others" (should be rare, but possible)
                if len(entry_author_info) > 0 and len(api_author_info) > 0 and entry_author_info[0]['lastname'] != 'others':
                    entry_first = entry_author_info[0]
                    api_first = api_author_info[0]

                    first_author_mismatch = False
                    if entry_first['lastname'] != api_first['lastname']:
                        first_author_mismatch = True
                        issues.append(
                            f"First author mismatch: '{entry_first['original']}' vs '{api_first['original']}' - "
                            f"KEY MAY NEED TO CHANGE"
                        )
                    elif entry_first['initials'] and api_first['initials'] and not authors_initials_match(entry_first['initials'], api_first['initials']):
                        issues.append(
                            f"First author initials mismatch: '{entry_first['original']}' vs '{api_first['original']}'"
                        )

                    # Check if citation key author matches first author
                    if key_author:
                        # Normalize key author to strip accents/hyphens in case raw key kept them
                        normalized_key_author = normalize_latex_text(key_author).lower()

                        # The key author might not include particles, so check both with and without
                        entry_first_lastname = normalize_latex_text(entry_first['lastname']).lower()
                        # Also try with particles prepended
                        entry_first_with_particles = entry_first_lastname
                        if entry_first['particles']:
                            particles_normalized = ''.join(normalize_latex_text(p).lower() for p in entry_first['particles'])
                            entry_first_with_particles = particles_normalized + entry_first_lastname

                        # Generate transliteration variants to handle names like 'Engström' vs 'Engstroem'
                        entry_variants = normalize_with_transliterations(entry_first['original'])
                        if entry_first_lastname not in entry_variants:
                            entry_variants.append(entry_first_lastname)
                        if entry_first_with_particles not in entry_variants:
                            entry_variants.append(entry_first_with_particles)

                        # Check if key author matches any variant
                        matches_any_variant = (
                            normalized_key_author == entry_first_lastname or
                            normalized_key_author == entry_first_with_particles or
                            normalized_key_author in entry_variants
                        )

                        if not matches_any_variant:
                            issues.append(
                                f"Citation key author mismatch: key contains '{key_author}' but first author is '{entry_first['original']}'"
                            )

                # Check for author order issues (compare all authors in sequence)
                max_check = min(len(entry_author_info), len(api_author_info))
                for i in range(max_check):
                    entry_auth = entry_author_info[i]
                    api_auth = api_author_info[i]

                    # Skip if we already reported first author mismatch
                    if i == 0 and first_author_mismatch:
                        continue

                    # Skip comparison if entry author is "others" (BibTeX/BibLaTeX "et al.")
                    if entry_auth['lastname'] == 'others':
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
                    elif entry_auth['initials'] and api_auth['initials'] and not authors_initials_match(entry_auth['initials'], api_auth['initials']):
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
                        api_title = ''.join(result.get('title', [''])).lower()
                        entry_title_lower = title.lower() if title else ''

                        # Check if both DOI and title match before auto-updating
                        title_matches = self._titles_match(entry_title_lower, api_title) if title else False

                        self.log(f"✓ Found by DOI on Crossref")
                        self.matches.append({
                            'entry_id': key,
                            'source': 'crossref',
                            'title': title,
                            'api_title': ''.join(result.get('title', ['']))
                        })
                        # Compare fields
                        self._compare_fields(key, entry, result, 'crossref')

                        # Only auto-update if both DOI and title match
                        if update and title_matches:
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

                    # Only auto-update if entry also has a DOI that matches the API DOI
                    api_doi = first_result.get('DOI', '').lower()
                    entry_doi = doi.lower() if doi else ''
                    doi_matches = (entry_doi and api_doi and entry_doi == api_doi)

                    if update and doi_matches:
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

                    # Only auto-update if entry also has a DOI that matches
                    entry_doi = entry.fields.get('doi', '').strip().lower()
                    api_doi = result.get('doi', '').lower() if result.get('doi') else ''
                    doi_matches = (entry_doi and api_doi and entry_doi == api_doi)

                    if update and doi_matches:
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

    def check_scholarly(self, key: str, entry: Entry, update: bool = False) -> Optional[Entry]:
        """Check entry against Google Scholar via Scholarly API."""
        if not self.use_scholarly:
            return None

        title = entry.fields.get('title', '').strip('{}').strip()
        if not title:
            return None

        self.log(f"Searching Google Scholar for: {title}")

        try:
            # Search for the publication
            search_query = scholarly.search_pubs(title)
            result = next(search_query, None)

            if result:
                gs_title = result.get('bib', {}).get('title', '').lower()
                entry_title = title.lower()

                if self._titles_match(entry_title, gs_title):
                    self.log(f"✓ Match found on Google Scholar")

                    # Convert scholarly result to a format similar to other APIs
                    bib = result.get('bib', {})
                    api_result = {
                        'title': bib.get('title', ''),
                        'authors': [{'name': author} for author in bib.get('author', [])],
                        'year': int(bib.get('pub_year', 0)) if bib.get('pub_year') else None,
                        'venue': bib.get('venue', ''),
                        'doi': result.get('pub_url', ''),  # Scholarly doesn't always provide DOI
                    }

                    self.matches.append({
                        'entry_id': key,
                        'source': 'scholarly',
                        'title': title,
                        'api_title': gs_title
                    })

                    # Compare fields
                    self._compare_fields(key, entry, api_result, 'scholarly')

                    # Note: We don't auto-update from Scholarly as it's less reliable than Crossref/SS
                    return result
                else:
                    self.log(f"Title mismatch")
                    self.mismatches.append({
                        'entry_id': key,
                        'title': title,
                        'api_title': gs_title
                    })
            else:
                self.log(f"Not found on Google Scholar")

        except Exception as e:
            self.log(f"Google Scholar error: {str(e)}")

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
        fields = {'title': '{' + clean_api_field(title) + '}'}

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
                fields['journaltitle'] = clean_api_field(container)
            elif etype in ['inproceedings', 'incollection']:
                fields['booktitle'] = clean_api_field(container)

        # Add volume, number, pages
        if 'volume' in crossref_result:
            fields['volume'] = clean_api_field(str(crossref_result['volume']))
        if 'issue' in crossref_result:
            fields['number'] = clean_api_field(str(crossref_result['issue']))
        if 'page' in crossref_result:
            # Format pages with double hyphens (--)
            pages = crossref_result['page']
            # Replace single dash with double hyphen
            pages = pages.replace('–', '--')  # en-dash to double hyphen
            pages = pages.replace('—', '--')  # em-dash to double hyphen
            # Only replace single hyphen if it's not already a double hyphen
            if '--' not in pages:
                pages = pages.replace('-', '--')
            fields['pages'] = clean_api_field(pages)

        # Add publisher and DOI
        if 'publisher' in crossref_result:
            fields['publisher'] = clean_api_field(crossref_result['publisher'])
        if 'DOI' in crossref_result:
            fields['doi'] = clean_api_field(crossref_result['DOI'])

        # Add ISBN/ISSN
        if 'ISBN' in crossref_result and crossref_result['ISBN']:
            isbn_value = crossref_result['ISBN'][0] if isinstance(crossref_result['ISBN'], list) else crossref_result['ISBN']
            fields['isbn'] = clean_api_field(isbn_value)
        if 'ISSN' in crossref_result and crossref_result['ISSN']:
            issn_value = crossref_result['ISSN'][0] if isinstance(crossref_result['ISSN'], list) else crossref_result['ISSN']
            fields['issn'] = clean_api_field(issn_value)

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
        fields = {'title': '{' + clean_api_field(ss_result.get('title', '')) + '}'}

        # Add year and venue
        if 'year' in ss_result and ss_result['year']:
            fields['year'] = str(ss_result['year'])
        if 'venue' in ss_result and ss_result['venue']:
            if etype == 'article':
                fields['journaltitle'] = clean_api_field(ss_result['venue'])
            elif etype == 'inproceedings':
                fields['booktitle'] = clean_api_field(ss_result['venue'])

        # Add DOI and arXiv
        if 'doi' in ss_result and ss_result['doi']:
            fields['doi'] = clean_api_field(ss_result['doi'])
        external_ids = ss_result.get('externalIds', {})
        if external_ids.get('ArXiv'):
            fields['eprint'] = clean_api_field(external_ids['ArXiv'])
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
        """Validate all entries against APIs (comprehensive search using all 3 APIs)."""
        total = len(bib_data.entries)
        api_list = "Crossref, Semantic Scholar"
        if self.use_scholarly:
            api_list += ", and Google Scholar"
        print(f"\nValidating {total} entries against APIs ({api_list})...")
        print("=" * 60)

        for idx, (key, entry) in enumerate(bib_data.entries.items(), 1):
            print(f"\n[{idx}/{total}] Checking: {key}")

            if (entry.type or '').lower() in SKIPPED_ENTRY_TYPES:
                print(f"  - Skipping entry type '{entry.type}' for API checks")
                continue

            # Try Crossref first (most reliable and comprehensive)
            crossref_found = self.check_crossref(key, entry, update=False)
            time.sleep(self.delay)

            # Fallback to Semantic Scholar if Crossref didn't find it
            if not crossref_found and not any(m['entry_id'] == key and m['source'] == 'crossref' for m in self.matches):
                self.check_semantic_scholar(key, entry, update=False)
                time.sleep(1.0 if SEMANTIC_SCHOLAR_API_KEY else 5.0)

            # Final fallback to Google Scholar if neither Crossref nor Semantic Scholar found it
            if self.use_scholarly and not any(m['entry_id'] == key for m in self.matches):
                self.check_scholarly(key, entry, update=False)
                time.sleep(2.0)  # Be respectful to Google Scholar

            # Track if not found in any of the APIs
            if not any(m['entry_id'] == key for m in self.matches):
                self.not_found.append(key)

    def add_missing_fields(self, bib_data: BibliographyData,
                           target_fields: Optional[List[str]] = None) -> BibliographyData:
        """
        Add missing fields to entries by querying APIs.
        Only processes entries that are missing the specified fields and have a DOI.
        Adds only the missing fields without replacing the entire entry.

        Args:
            bib_data: The bibliography database
            target_fields: List of field names to add if missing (default: ['pages', 'number', 'volume'])

        Returns:
            Updated BibliographyData object

        Note:
            Uses Crossref API first, then falls back to Scholarly with random delays (5-12s)
            to avoid rate limiting. Scholarly session is kept alive across queries.
        """
        if target_fields is None:
            target_fields = ['pages', 'number', 'volume']

        # STEP 1: Filter entries that have missing target fields AND have a DOI
        print(f"\nScanning for entries with missing fields ({', '.join(target_fields)})...")
        entries_to_process = []

        for key, entry in bib_data.entries.items():
            # Skip certain entry types
            if (entry.type or '').lower() in SKIPPED_ENTRY_TYPES:
                continue

            # Must have DOI for safe matching
            doi = entry.fields.get('doi', '').strip()
            if not doi:
                continue

            # Check which target fields are missing
            # IMPORTANT: 'number' and 'issue' are BibTeX/BibLaTeX alternatives - treat as same field
            missing_fields = []
            for field in target_fields:
                if field in ['number', 'issue']:
                    # Check if EITHER number OR issue exists (they're alternatives)
                    if 'number' not in entry.fields and 'issue' not in entry.fields:
                        missing_fields.append('number')  # Report as 'number' missing
                else:
                    # Regular field - just check if it exists
                    if field not in entry.fields:
                        missing_fields.append(field)

            # Only process if at least one target field is missing
            if missing_fields:
                entries_to_process.append((key, entry, missing_fields))

        total = len(bib_data.entries)
        to_process = len(entries_to_process)
        print(f"Found {to_process} entries (out of {total}) with missing fields and DOI")

        if to_process == 0:
            print("\nNo entries need processing. All entries either:")
            print("  - Already have the target fields, OR")
            print("  - Don't have a DOI, OR")
            print("  - Are skipped entry types (phdthesis, misc, online)")
            return bib_data

        print("=" * 60)

        updated_count = 0
        crossref_count = 0
        scholarly_count = 0

        # STEP 2: Process only the filtered entries
        for idx, (key, entry, missing_fields) in enumerate(entries_to_process, 1):
            print(f"\n[{idx}/{to_process}] Processing: {key}")
            print(f"  - Missing: {', '.join(missing_fields)}")

            title = entry.fields.get('title', '').strip('{}').strip()
            doi = entry.fields.get('doi', '').strip()

            # Track which fields were added
            fields_added = []
            fields_still_missing = list(missing_fields)

            # Try Crossref API first (using DOI for exact match)
            try:
                self.log(f"Querying Crossref for DOI: {doi}")
                doi_url = f"{CROSSREF_API_BASE}/works/{doi}"
                headers = {'User-Agent': f'biblatex-diagnostics/1.0 (mailto:{MAILTO_EMAIL})'}

                response = requests.get(doi_url, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()

                if data.get('message'):
                    result = data['message']

                    # DOI lookup is authoritative - if we got a result, trust it
                    # Just do a basic sanity check on title (relaxed matching)
                    api_title = ''.join(result.get('title', [''])).lower()
                    entry_title_lower = title.lower() if title else ''

                    # Very relaxed title check - just check if some words overlap
                    # or skip if entry has no title (some entries may not have title in local file)
                    title_ok = False
                    if not title:
                        # No local title, trust the DOI
                        title_ok = True
                        self.log("✓ No local title, trusting DOI match")
                    elif api_title and entry_title_lower:
                        # Remove punctuation and compare word overlap
                        entry_words = set(re.sub(r'[^\w\s]', '', entry_title_lower).split())
                        api_words = set(re.sub(r'[^\w\s]', '', api_title).split())
                        if entry_words and api_words:
                            overlap = len(entry_words & api_words) / len(entry_words | api_words)
                            if overlap > 0.7:  # 70% word overlap for minor differences (caps, punctuation, spacing)
                                title_ok = True
                                self.log(f"✓ Title overlap {overlap:.2%}, accepting DOI match")
                            else:
                                # Lower overlap indicates potential mismatch - warn but trust DOI
                                self.log(f"⚠ Low title overlap {overlap:.2%} but DOI matches - proceeding cautiously")
                                print(f"  ⚠ Warning: Title mismatch (local: '{title[:50]}...', API: '{api_title[:50]}...') but DOI matches")
                                title_ok = True
                    else:
                        # Can't compare, trust DOI
                        title_ok = True

                    if title_ok:
                        # Add missing fields from Crossref result
                        if 'pages' in fields_still_missing and 'page' in result:
                            pages = result['page']
                            # Format pages with double hyphens (--)
                            pages = pages.replace('–', '--')  # en-dash to double hyphen
                            pages = pages.replace('—', '--')  # em-dash to double hyphen
                            if '--' not in pages:
                                pages = pages.replace('-', '--')
                            entry.fields['pages'] = clean_api_field(pages)
                            fields_added.append('pages')
                            fields_still_missing.remove('pages')

                        if 'volume' in fields_still_missing and 'volume' in result:
                            entry.fields['volume'] = clean_api_field(str(result['volume']))
                            fields_added.append('volume')
                            fields_still_missing.remove('volume')

                        # Crossref uses 'issue' field, we store as 'number' (BibTeX standard)
                        # Note: number/issue are treated as alternatives, so only 'number' appears in missing list
                        if 'number' in fields_still_missing and 'issue' in result:
                            entry.fields['number'] = clean_api_field(str(result['issue']))
                            fields_added.append('number')
                            fields_still_missing.remove('number')

                        if fields_added:
                            print(f"  ✓ Added from Crossref: {', '.join(fields_added)}")
                            crossref_count += 1
                            updated_count += 1

            except Exception as e:
                self.log(f"Crossref error: {str(e)}")
                print(f"  - Crossref query failed: {str(e)}")

            time.sleep(self.delay)

            # If any fields are still missing, try Scholarly API as fallback
            if fields_still_missing and self.use_scholarly and self.scholarly_session_active and title:
                # Random delay before Scholarly query (5-12 seconds) to avoid rate limiting
                delay = random.uniform(5.0, 12.0)
                self.log(f"Waiting {delay:.1f}s before Scholarly query...")
                time.sleep(delay)

                print(f"  - Trying Scholarly for remaining fields: {', '.join(fields_still_missing)}")

                try:
                    # Clean the title for Scholarly search - remove LaTeX formatting
                    # Scholarly doesn't understand LaTeX, so we need to normalize it
                    search_title = title
                    # Remove common LaTeX commands and braces
                    search_title = re.sub(r'\{([^}]*)\}', r'\1', search_title)  # Remove braces but keep content
                    search_title = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', search_title)  # Remove \command{text}
                    search_title = re.sub(r'\\[a-zA-Z]+', '', search_title)  # Remove other commands
                    search_title = search_title.replace('--', '-')  # Double dash to single
                    search_title = ' '.join(search_title.split())  # Normalize whitespace

                    self.log(f"Original title: {title}")
                    self.log(f"Searching Scholarly with: '{search_title}'")

                    # Search by title in Scholarly (using persistent session)
                    try:
                        search_query = scholarly.search_pubs(search_title)
                        result = next(search_query, None)
                    except StopIteration:
                        result = None
                        self.log("Scholarly search returned StopIteration (no results)")
                    except Exception as search_error:
                        result = None
                        error_msg = str(search_error)
                        self.log(f"Scholarly search exception: {error_msg}")
                        print(f"  ⚠ Scholarly search error: {error_msg}")
                        # Check if we might be blocked
                        if "429" in error_msg or "captcha" in error_msg.lower() or "blocked" in error_msg.lower():
                            print(f"  ⚠ WARNING: Google Scholar is likely blocking requests!")
                            print(f"  ⚠ Try waiting several minutes or use a VPN/proxy")
                            self.scholarly_session_active = False  # Disable further Scholarly queries
                        # Re-raise to be caught by outer exception handler
                        raise

                    if result:
                        # Log the full result for debugging
                        self.log(f"Scholarly result: {result}")

                        gs_title = result.get('bib', {}).get('title', '').lower()
                        entry_title = search_title.lower()  # Use cleaned title for comparison

                        self.log(f"Scholarly returned title: '{gs_title}'")
                        self.log(f"Comparing with: '{entry_title}'")

                        # Relaxed title matching for Scholarly
                        entry_words = set(re.sub(r'[^\w\s]', '', entry_title).split())
                        gs_words = set(re.sub(r'[^\w\s]', '', gs_title).split())
                        overlap = 0
                        if entry_words and gs_words:
                            overlap = len(entry_words & gs_words) / len(entry_words | gs_words)
                            self.log(f"Word overlap: {overlap:.2%}")
                            self.log(f"Entry words: {sorted(entry_words)}")
                            self.log(f"GS words: {sorted(gs_words)}")

                        if overlap > 0.5:  # 50% overlap for Scholarly (no DOI verification)
                            self.log(f"✓ Title overlap {overlap:.2%} with Scholarly")
                            bib = result.get('bib', {})
                            scholarly_fields_added = []

                            # Try to extract missing fields from Scholarly
                            if 'pages' in fields_still_missing:
                                pages_data = bib.get('pages', '')
                                if pages_data:
                                    # Ensure double hyphen format
                                    pages_data = str(pages_data)
                                    pages_data = pages_data.replace('–', '--')
                                    pages_data = pages_data.replace('—', '--')
                                    if '--' not in pages_data and '-' in pages_data:
                                        pages_data = pages_data.replace('-', '--')
                                    entry.fields['pages'] = pages_data
                                    scholarly_fields_added.append('pages')
                                    fields_still_missing.remove('pages')

                            if 'volume' in fields_still_missing:
                                volume_data = bib.get('volume', '')
                                if volume_data:
                                    entry.fields['volume'] = str(volume_data)
                                    scholarly_fields_added.append('volume')
                                    fields_still_missing.remove('volume')

                            if 'number' in fields_still_missing:
                                # Scholarly may have 'number' or 'issue' field
                                number_data = bib.get('number', '') or bib.get('issue', '')
                                if number_data:
                                    entry.fields['number'] = str(number_data)
                                    scholarly_fields_added.append('number')
                                    fields_still_missing.remove('number')

                            if scholarly_fields_added:
                                print(f"  ✓ Added from Scholarly: {', '.join(scholarly_fields_added)}")
                                scholarly_count += 1
                                if not fields_added:  # Only increment if Crossref didn't update
                                    updated_count += 1
                                fields_added.extend(scholarly_fields_added)
                        else:
                            print(f"  ✗ Title overlap too low ({overlap:.2%}) with Scholarly")
                            print(f"     Local title:  '{entry_title[:80]}...'")
                            print(f"     Scholar title: '{gs_title[:80]}...'")
                            # Show first 5 words from each to diagnose the mismatch
                            local_sample = sorted(entry_words)[:5]
                            scholar_sample = sorted(gs_words)[:5]
                            print(f"     Local words (first 5):  {local_sample}")
                            print(f"     Scholar words (first 5): {scholar_sample}")
                            self.log(f"  Expected overlap >50%, got {overlap:.2%}")
                            self.log(f"  Full local words: {sorted(entry_words)}")
                            self.log(f"  Full Scholar words: {sorted(gs_words)}")
                    else:
                        print(f"  ✗ No results from Scholarly")
                        self.log("Scholarly search returned no results")
                        self.log(f"  This could indicate Google Scholar is rate-limiting/blocking requests")
                        self.log(f"  Try: 1) Wait several minutes, 2) Use VPN, or 3) Reduce query rate")

                except Exception as e:
                    self.log(f"Scholarly error: {str(e)}")
                    print(f"  - Scholarly query failed: {str(e)}")

            # Report final status
            if fields_still_missing:
                print(f"  - Still missing: {', '.join(fields_still_missing)}")

        print(f"\n{'=' * 60}")
        print(f"Updated {updated_count}/{to_process} entries that needed processing")
        print(f"  - Fields added via Crossref: {crossref_count} entries")
        print(f"  - Fields added via Scholarly: {scholarly_count} entries")

        return bib_data

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

            if (entry.type or '').lower() in SKIPPED_ENTRY_TYPES:
                print(f"  - Skipping entry type '{entry.type}' for API updates")
                continue

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

            # Calculate title similarity (Jaccard index)
            sug_title = sug.get('suggestion', '').lower()
            title_similarity = 0
            if entry_title and sug_title:
                # Calculate word overlap
                entry_words = set(re.sub(r'[^\w\s]', '', entry_title).split())
                sug_words = set(re.sub(r'[^\w\s]', '', sug_title).split())
                if entry_words and sug_words:
                    title_similarity = len(entry_words & sug_words) / len(entry_words | sug_words)

            # Check first author match
            author_matches = False
            sug_authors_str = sug.get('authors', '')
            if sug_authors_str and sug_authors_str != 'N/A':
                # Get first author from suggestion
                first_sug_author = sug_authors_str.split(',')[0].strip()
                sug_first_lastname, _, _ = extract_author_components(first_sug_author)

                if entry_first_author_lastname and sug_first_lastname:
                    if entry_first_author_lastname == sug_first_lastname:
                        author_matches = True

            # Check year match
            year_matches = False
            sug_year = sug.get('year', 'N/A')
            if entry_year and sug_year != 'N/A' and str(entry_year) == str(sug_year):
                year_matches = True

            # Priority ranking:
            # 1. High title match (>0.8): 200 points
            # 2. Very good title match (>0.7): 180 points
            # 3. Good title match (>0.6) + same author: 150 points
            # 4. Good title match (>0.6) + same year: 120 points
            # 5. Moderate title match (>0.5): 100 points
            # 6. Lower title matches get proportional scores

            if title_similarity > 0.8:
                score = 200
            elif title_similarity > 0.7:
                score = 180
            elif title_similarity > 0.6 and author_matches:
                score = 150
            elif title_similarity > 0.6 and year_matches:
                score = 120
            elif title_similarity > 0.6:
                score = 110
            elif title_similarity > 0.5:
                score = 100
            else:
                score = int(title_similarity * 100)

            # Bonus for matching author (if not already counted above)
            if author_matches and title_similarity <= 0.6:
                score += 30

            # Bonus for matching year (if not already counted above)
            if year_matches and title_similarity <= 0.6:
                score += 20

            # Bonus points for certain search strategies
            strategy = sug.get('strategy', '')
            if strategy == 'author_year':
                score += 5
            elif strategy == 'author_keywords':
                score += 3

            scored_suggestions.append((score, sug, title_similarity))

        # Sort by score (highest first), then by title similarity as tiebreaker
        scored_suggestions.sort(key=lambda x: (x[0], x[2]), reverse=True)

        # Return just the suggestions (without scores and similarity)
        return [sug for score, sug, similarity in scored_suggestions]

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
        description='BibTeX API Diagnostics - Compare entries against Crossref, Semantic Scholar, and Google Scholar',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate all entries against APIs
  python biblatex_diagnostics.py input.bib

  # Update entries with API data
  python biblatex_diagnostics.py input.bib --update -o corrected.bib

  # Add missing fields (pages, volume, number) to entries
  python biblatex_diagnostics.py input.bib --add-missing-fields -o corrected.bib

  # Add specific missing fields
  python biblatex_diagnostics.py input.bib --add-missing-fields --fields pages volume -o corrected.bib

  # Save validation report to file
  python biblatex_diagnostics.py input.bib -r report.txt

  # Disable Google Scholar (use only Crossref and Semantic Scholar)
  python biblatex_diagnostics.py input.bib --no-scholarly
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
    parser.add_argument('--add-missing-fields', action='store_true',
                       help='Add missing fields to entries (pages, volume, number) without replacing entire entries. '
                            'Requires DOI for safe matching. Falls back to Scholarly with random delays (5-12s). '
                            'Use with -o to save results.')
    parser.add_argument('--fields', nargs='+', default=['pages', 'number', 'volume'],
                       help='Specify which fields to add when using --add-missing-fields '
                            '(default: pages number volume)')
    parser.add_argument('--no-scholarly', action='store_true',
                       help='Disable Google Scholar API (only use Crossref and Semantic Scholar)')

    args = parser.parse_args()

    if args.update and not args.output:
        parser.error("--update requires -o/--output")

    if args.add_missing_fields and not args.output:
        parser.error("--add-missing-fields requires -o/--output")

    if args.update and args.add_missing_fields:
        parser.error("Cannot use both --update and --add-missing-fields at the same time")

    # Clean file paths
    args.input_file = clean_filepath(args.input_file)
    if args.output:
        args.output = clean_filepath(args.output)
    if args.report_file:
        args.report_file = clean_filepath(args.report_file)

    # Initialize checker
    checker = BibTeXAPIChecker(verbose=args.verbose, delay=args.delay, use_scholarly=not args.no_scholarly)

    try:
        # Load BibTeX file
        bib_data = checker.load_bibtex(args.input_file)

        if args.add_missing_fields:
            # Add missing fields mode
            bib_data = checker.add_missing_fields(
                bib_data,
                target_fields=args.fields
            )
            checker.save_bibtex(bib_data, args.output)
            print(f"\n✓ Updated BibTeX with missing fields saved to: {args.output}")
        elif args.update:
            # Update mode
            bib_data = checker.update_with_apis(bib_data)
            checker.save_bibtex(bib_data, args.output)
            print(f"\n✓ Corrected BibTeX saved to: {args.output}")
        else:
            # Validation mode
            checker.validate_all_entries(bib_data)

        # Generate report (only for validation mode)
        if not args.update and not args.add_missing_fields:
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
