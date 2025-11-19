#!/usr/bin/env python3
"""
Test script to verify the field validation improvements work correctly.
"""

import sys
sys.path.insert(0, '/home/user/Biblatex_check')

from biblatex_diagnostics import (
    normalize_journal_name,
    journals_match_fuzzy,
    authors_initials_match,
    normalize_latex_text
)

def test_journal_matching():
    """Test journal name fuzzy matching."""
    print("Testing Journal Name Matching")
    print("=" * 60)

    test_cases = [
        # (journal1, journal2, should_match, description)
        ('Physics of Fluids', 'The Physics of Fluids', True, '"The" prefix'),
        ('Lab on a Chip', 'Lab Chip', True, 'Abbreviation'),
        ('Particle {\\&} Particle Systems Characterization',
         'Particle &amp; Particle Systems Characterization', True, 'Ampersand encoding'),
        ('{IBM} Journal of Research and Development',
         'IBM Journal of Research and Development', True, 'LaTeX braces'),
        ('Nature', 'Science', False, 'Different journals'),
    ]

    for journal1, journal2, should_match, description in test_cases:
        result = journals_match_fuzzy(journal1, journal2)
        status = "✓" if result == should_match else "✗"
        print(f"{status} {description}:")
        print(f"   '{journal1}' vs '{journal2}'")
        print(f"   Match: {result}, Expected: {should_match}")
        print()

def test_author_initials():
    """Test author initials matching."""
    print("\nTesting Author Initials Matching")
    print("=" * 60)

    test_cases = [
        # (initials1, initials2, should_match, description)
        ('S', 'SC', True, 'First initial matches'),
        ('S', 'Scot C', True, 'Initial vs full name'),
        ('SC', 'Scot C', True, 'Initials vs full name'),
        ('J', 'M', False, 'Different initials'),
    ]

    for init1, init2, should_match, description in test_cases:
        result = authors_initials_match(init1, init2)
        status = "✓" if result == should_match else "✗"
        print(f"{status} {description}:")
        print(f"   '{init1}' vs '{init2}'")
        print(f"   Match: {result}, Expected: {should_match}")
        print()

def test_latex_normalization():
    """Test LaTeX text normalization."""
    print("\nTesting LaTeX Text Normalization")
    print("=" * 60)

    test_cases = [
        ("Rosales-Guzm{\'{a}}n", "rosalesguzman", 'Accent normalization'),
        ("Engström", "engstrom", 'Unicode character normalization'),
        ("M{\\\"u}ller", "muller", 'Umlaut normalization'),
    ]

    for latex_text, expected, description in test_cases:
        result = normalize_latex_text(latex_text).lower().replace('-', '')
        status = "✓" if result == expected else "✗"
        print(f"{status} {description}:")
        print(f"   Input: '{latex_text}'")
        print(f"   Output: '{result}'")
        print(f"   Expected: '{expected}'")
        print()

def test_journal_normalization():
    """Test journal name normalization."""
    print("\nTesting Journal Name Normalization")
    print("=" * 60)

    test_cases = [
        ('{IBM} Journal', 'ibm journal', 'Remove braces'),
        ('The Physics of Fluids', 'physics of fluids', 'Remove "The" prefix'),
        ('Particle {\\&} Systems', 'particle & systems', 'Normalize ampersand'),
    ]

    for journal, expected, description in test_cases:
        result = normalize_journal_name(journal)
        status = "✓" if result == expected else "✗"
        print(f"{status} {description}:")
        print(f"   Input: '{journal}'")
        print(f"   Output: '{result}'")
        print(f"   Expected: '{expected}'")
        print()

if __name__ == '__main__':
    test_journal_matching()
    test_author_initials()
    test_latex_normalization()
    test_journal_normalization()

    print("\n" + "=" * 60)
    print("All tests completed!")
