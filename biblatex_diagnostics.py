#!/usr/bin/env python3
"""
BibTeX Diagnostic Tool
A comprehensive tool for validating and correcting BibTeX entries using Google Scholar as ground truth.
"""

import re
import sys
import time
import argparse
import requests
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from pybtex.database import parse_file, BibliographyData, Entry
from pybtex.database.output.bibtex import Writer

try:
    from scholarly import scholarly
    SCHOLARLY_AVAILABLE = True
except ImportError:
    SCHOLARLY_AVAILABLE = False
    print("Warning: scholarly package not fully functional. Google Scholar features may be limited.")


class BibTeXDiagnostics:
    """Main diagnostic class for BibTeX file validation and correction."""

    def __init__(self, verbose: bool = False, delay: float = 5.0):
        """
        Initialize the diagnostic tool.

        Args:
            verbose: Enable verbose output
            delay: Delay between Google Scholar queries (seconds) to avoid rate limiting
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

    def check_google_scholar(self, key: str, entry: Entry, update: bool = False) -> Optional[Entry]:
        """
        Check entry against Google Scholar and optionally update it.

        Args:
            key: BibTeX entry key
            entry: BibTeX entry
            update: If True, return the Google Scholar entry for updating

        Returns:
            Google Scholar entry if found and update=True, otherwise None
        """
        if not SCHOLARLY_AVAILABLE:
            return None

        title = entry.fields.get('title', '').strip('{}').strip()
        if not title:
            self.issues.append(f"Entry {key} has no title")
            return None

        self.log(f"Searching Google Scholar for: {title}")

        try:
            # Search for the paper by title
            search_query = scholarly.search_pubs(title)
            result = next(search_query, None)

            if result:
                # Check if titles match (allowing for some variation)
                gs_title = result.get('bib', {}).get('title', '').lower()
                entry_title = title.lower()

                # Simple similarity check
                if self._titles_match(entry_title, gs_title):
                    self.log(f"✓ Match found on Google Scholar: {result['bib']['title']}")

                    if update:
                        # Convert to BibTeX format
                        gs_entry = self._scholarly_to_entry(result, key, entry.type)
                        return gs_entry
                    else:
                        # Just report the match
                        self.corrections.append({
                            'entry_id': key,
                            'type': 'google_scholar_match',
                            'message': f"Found matching entry on Google Scholar",
                            'gs_data': result['bib']
                        })
                else:
                    self.issues.append(f"Entry {key}: Title mismatch - '{title}' vs '{result['bib']['title']}'")
            else:
                self.issues.append(f"Entry {key}: Not found on Google Scholar")

        except Exception as e:
            self.issues.append(f"Entry {key}: Google Scholar error - {str(e)}")

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

    def _scholarly_to_entry(self, scholarly_result: Dict, entry_key: str, entry_type: str) -> Entry:
        """Convert scholarly result to pybtex Entry format."""
        bib_data = scholarly_result.get('bib', {})

        # Determine entry type
        if 'venue' in bib_data:
            venue = bib_data['venue'].lower()
            if 'journal' in venue or 'trans' in venue:
                etype = 'article'
            elif 'conference' in venue or 'proc' in venue:
                etype = 'inproceedings'
            else:
                etype = entry_type or 'article'
        else:
            etype = entry_type or 'article'

        # Create fields dict
        fields = {
            'title': '{' + bib_data.get('title', '') + '}',
            'year': str(bib_data.get('pub_year', '')),
        }

        # Add venue
        if 'venue' in bib_data:
            if etype == 'article':
                fields['journal'] = bib_data['venue']
            else:
                fields['booktitle'] = bib_data['venue']

        # Add abstract if available
        if 'abstract' in bib_data:
            fields['abstract'] = '{' + bib_data['abstract'] + '}'

        # Try to get DOI
        if 'pub_url' in scholarly_result:
            doi_match = re.search(r'10\.\d{4,}/[^\s]+', scholarly_result['pub_url'])
            if doi_match:
                fields['doi'] = doi_match.group(0)

        # Handle authors
        from pybtex.database import Person
        persons = {}
        if 'author' in bib_data:
            author_list = []
            authors = bib_data['author']
            if isinstance(authors, str):
                authors = [authors]
            for author in authors:
                # Parse author name
                author_list.append(Person(author))
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

    def run_diagnostics(self, bib_data: BibliographyData, check_scholar: bool = True,
                       check_doi: bool = True, check_unicode: bool = True,
                       check_ampersand: bool = True, check_special: bool = True) -> None:
        """
        Run all selected diagnostics on the BibTeX database.

        Args:
            bib_data: The BibTeX database to check
            check_scholar: Check against Google Scholar
            check_doi: Validate DOIs
            check_unicode: Check for unicode issues
            check_ampersand: Check for unescaped ampersands
            check_special: Check for special character issues
        """
        total_entries = len(bib_data.entries)
        print(f"\nRunning diagnostics on {total_entries} entries...")
        print("=" * 60)

        for idx, (key, entry) in enumerate(bib_data.entries.items(), 1):
            print(f"\n[{idx}/{total_entries}] Checking: {key}")

            if check_scholar and SCHOLARLY_AVAILABLE:
                self.check_google_scholar(key, entry, update=False)
                time.sleep(self.delay)  # Rate limiting

            if check_doi:
                self.validate_doi(key, entry)

            if check_unicode:
                self.check_unicode_issues(key, entry)

            if check_ampersand:
                self.check_unescaped_ampersand(key, entry)

            if check_special:
                self.check_special_characters(key, entry)

    def fix_with_google_scholar(self, bib_data: BibliographyData) -> BibliographyData:
        """
        Update BibTeX entries with Google Scholar data where matches are found.

        Args:
            bib_data: The BibTeX database to update

        Returns:
            Updated BibTeX database
        """
        if not SCHOLARLY_AVAILABLE:
            print("Error: scholarly package not available. Cannot update with Google Scholar.")
            return bib_data

        total_entries = len(bib_data.entries)
        print(f"\nUpdating {total_entries} entries with Google Scholar data...")
        print("=" * 60)

        updated_count = 0

        for idx, (key, entry) in enumerate(list(bib_data.entries.items()), 1):
            print(f"\n[{idx}/{total_entries}] Processing: {key}")

            gs_entry = self.check_google_scholar(key, entry, update=True)

            if gs_entry:
                # Update entry with Google Scholar data
                bib_data.entries[key] = gs_entry
                updated_count += 1
                print(f"  ✓ Updated with Google Scholar data")
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
        description='BibTeX Diagnostic Tool - Validate and correct BibTeX entries using Google Scholar',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all diagnostics (no modifications)
  python biblatex_diagnostics.py input.bib

  # Update entries with Google Scholar data
  python biblatex_diagnostics.py input.bib --update-scholar -o corrected.bib

  # Run specific diagnostics only
  python biblatex_diagnostics.py input.bib --no-scholar --check-doi --check-unicode

  # Verbose output with custom delay
  python biblatex_diagnostics.py input.bib -v --delay 3.0
        """
    )

    parser.add_argument('input_file', help='Input BibTeX file')
    parser.add_argument('-o', '--output', help='Output file for corrected BibTeX')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--delay', type=float, default=5.0,
                       help='Delay between Google Scholar queries (default: 5.0 seconds)')

    # Diagnostic options
    parser.add_argument('--no-scholar', action='store_true',
                       help='Skip Google Scholar checking')
    parser.add_argument('--no-doi', action='store_true',
                       help='Skip DOI validation')
    parser.add_argument('--no-unicode', action='store_true',
                       help='Skip unicode character checking')
    parser.add_argument('--no-ampersand', action='store_true',
                       help='Skip ampersand checking')
    parser.add_argument('--no-special', action='store_true',
                       help='Skip special character checking')

    # Update options
    parser.add_argument('--update-scholar', action='store_true',
                       help='Update entries with Google Scholar data (requires -o)')

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
            bib_data = diagnostics.fix_with_google_scholar(bib_data)
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
                check_special=not args.no_special
            )

        # Print report
        print(diagnostics.generate_report())

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
