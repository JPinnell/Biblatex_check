#!/usr/bin/env python3
"""Test the author name parsing fixes."""

import sys
sys.path.insert(0, '/home/user/Biblatex_check')

from biblatex_diagnostics import extract_author_components, extract_citation_key_components

def test_de_fornel():
    """Test that 'de Fornel, F.' is parsed correctly."""
    print("Testing 'de Fornel, F.'...")
    lastname, initials, particles = extract_author_components("de Fornel, F.")
    print(f"  Result: lastname='{lastname}', initials='{initials}', particles={particles}")

    # Also test the API format
    print("Testing 'Frederique de Fornel'...")
    lastname2, initials2, particles2 = extract_author_components("Frederique de Fornel")
    print(f"  Result: lastname='{lastname2}', initials='{initials2}', particles={particles2}")

    # Check if they match (should both have lastname='fornel' with 'de' as particle)
    if lastname == lastname2:
        print("  ✓ Last names match!")
    else:
        print(f"  ✗ Last names don't match: '{lastname}' vs '{lastname2}'")

    print()

def test_pfeifer():
    """Test that 'Pfeifer, Robert NC' is parsed correctly."""
    print("Testing 'Pfeifer, Robert NC'...")
    lastname, initials, particles = extract_author_components("Pfeifer, Robert NC")
    print(f"  Result: lastname='{lastname}', initials='{initials}', particles={particles}")

    # Also test the API format
    print("Testing 'Robert N. C. Pfeifer'...")
    lastname2, initials2, particles2 = extract_author_components("Robert N. C. Pfeifer")
    print(f"  Result: lastname='{lastname2}', initials='{initials2}', particles={particles2}")

    # Check if initials match (should both be 'RNC')
    if initials == initials2:
        print("  ✓ Initials match!")
    else:
        print(f"  ✗ Initials don't match: '{initials}' vs '{initials2}'")

    print()

def test_citation_key():
    """Test citation key parsing."""
    print("Testing citation key parsing...")

    # Test Lin2012
    author, year = extract_citation_key_components("Lin2012")
    print(f"  Lin2012: author='{author}', year='{year}'")

    # Test Pfeifer2009
    author, year = extract_citation_key_components("Pfeifer2009")
    print(f"  Pfeifer2009: author='{author}', year='{year}'")

    # Test with particles
    author, year = extract_citation_key_components("deFornel2012")
    print(f"  deFornel2012: author='{author}', year='{year}'")

    print()

if __name__ == "__main__":
    print("=" * 60)
    print("AUTHOR NAME PARSING TESTS")
    print("=" * 60)
    print()

    test_de_fornel()
    test_pfeifer()
    test_citation_key()

    print("=" * 60)
