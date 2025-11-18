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
from typing import Dict, List, Optional
from pybtex.database import parse_file, BibliographyData, Entry, Person
from pybtex.database.output.bibtex import Writer

# Crossref API endpoint (primary)
CROSSREF_API_BASE = "https://api.crossref.org"
MAILTO_EMAIL = os.environ.get('CROSSREF_MAILTO', 'research@example.com')

# Semantic Scholar API endpoint (fallback)
SEMANTIC_SCHOLAR_API_BASE = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_API_KEY = os.environ.get('SEMANTIC_SCHOLAR_API_KEY', None)


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
        """Compare fields between local entry and API result."""
        issues = []

        # Compare DOI
        if 'doi' in entry.fields:
            entry_doi = entry.fields['doi'].lower()
            api_doi = api_result.get('DOI', '').lower() if source == 'crossref' else api_result.get('doi', '').lower()
            if api_doi and entry_doi != api_doi:
                issues.append(f"DOI mismatch: '{entry_doi}' vs '{api_doi}'")

        # Compare year
        if 'year' in entry.fields or 'date' in entry.fields:
            entry_year = entry.fields.get('year', entry.fields.get('date', ''))[:4]
            if source == 'crossref':
                published = api_result.get('published', {}) or api_result.get('published-print', {})
                if published and 'date-parts' in published and published['date-parts']:
                    api_year = str(published['date-parts'][0][0])
                else:
                    api_year = None
            else:  # semantic scholar
                api_year = str(api_result.get('year', '')) if api_result.get('year') else None

            if api_year and entry_year and entry_year != api_year:
                issues.append(f"Year mismatch: '{entry_year}' vs '{api_year}'")

        # Compare authors (basic check - just count)
        if 'author' in entry.persons:
            entry_author_count = len(entry.persons['author'])
            if source == 'crossref':
                api_author_count = len(api_result.get('author', []))
            else:  # semantic scholar
                api_author_count = len(api_result.get('authors', []))

            if api_author_count and entry_author_count != api_author_count:
                issues.append(f"Author count mismatch: {entry_author_count} vs {api_author_count}")

        if issues:
            self.field_mismatches.append({
                'entry_id': key,
                'source': source,
                'issues': issues
            })

    def check_crossref(self, key: str, entry: Entry, update: bool = False) -> Optional[Entry]:
        """Check entry against Crossref API."""
        title = entry.fields.get('title', '').strip('{}').strip()
        if not title:
            return None

        self.log(f"Searching Crossref for: {title}")

        try:
            search_url = f"{CROSSREF_API_BASE}/works"
            params = {
                'query.title': title,
                'rows': 1,
                'select': 'DOI,title,author,published,container-title,volume,issue,page,publisher,ISBN,ISSN,type'
            }
            headers = {'User-Agent': f'biblatex-diagnostics/1.0 (mailto:{MAILTO_EMAIL})'}

            response = requests.get(search_url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('message') and data['message'].get('items') and len(data['message']['items']) > 0:
                result = data['message']['items'][0]
                crossref_title = ''.join(result.get('title', [''])).lower()
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
                    self._compare_fields(key, entry, result, 'crossref')
                    if update:
                        return self._crossref_to_entry(result, key, entry.type)
                    return result  # Return result for suggestion purposes
                else:
                    self.log(f"Title mismatch - but tracking as suggestion")
                    # Track as suggestion even if not exact match
                    suggestion_title = ''.join(result.get('title', []))
                    suggestion_authors = []
                    for author in result.get('author', [])[:3]:  # First 3 authors
                        given = author.get('given', '')
                        family = author.get('family', '')
                        if given and family:
                            suggestion_authors.append(f"{given} {family}")
                        elif family:
                            suggestion_authors.append(family)

                    self.suggestions.append({
                        'entry_id': key,
                        'source': 'crossref',
                        'suggestion': suggestion_title,
                        'authors': ', '.join(suggestion_authors) if suggestion_authors else 'N/A',
                        'doi': result.get('DOI', 'N/A')
                    })
                    return None
            else:
                self.log(f"Not found on Crossref")

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

    def generate_report(self) -> str:
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
            for sug in self.suggestions:
                report.append(f"  💡 {sug['entry_id']} - Did you mean?")
                report.append(f"      Title: {sug['suggestion']}")
                report.append(f"      Authors: {sug['authors']}")
                report.append(f"      DOI: {sug['doi']}")
                report.append(f"      Source: {sug['source']}")

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
        report = checker.generate_report()
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
