#!/usr/bin/env python3
"""
BibTeX Syntax Checker
Pre-validation tool that checks for common syntax errors before parsing.
This tool uses text-based analysis to identify issues that would prevent pybtex from parsing.
"""

import re
import sys
import argparse
from typing import List, Tuple, Dict, Set
from collections import defaultdict


class SyntaxIssue:
    """Represents a syntax issue in a BibTeX file."""

    def __init__(self, line_num: int, severity: str, message: str, context: str = ""):
        self.line_num = line_num
        self.severity = severity  # 'ERROR' or 'WARNING'
        self.message = message
        self.context = context

    def __str__(self):
        prefix = "✗" if self.severity == "ERROR" else "⚠"
        result = f"{prefix} Line {self.line_num}: {self.message}"
        if self.context:
            result += f"\n    Context: {self.context[:80]}"
        return result


class BibTeXSyntaxChecker:
    """Pre-validation syntax checker for BibTeX files."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.lines = []
        self.issues: List[SyntaxIssue] = []
        self.entry_keys: Dict[str, List[int]] = defaultdict(list)
        self.valid_entry_types = {
            'article', 'book', 'booklet', 'inbook', 'incollection', 'inproceedings',
            'manual', 'mastersthesis', 'misc', 'phdthesis', 'proceedings', 'techreport',
            'unpublished', 'online', 'patent', 'periodical', 'suppbook', 'suppcollection',
            'suppperiodical', 'conference', 'electronic'
        }

    def load_file(self):
        """Load the BibTeX file."""
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                self.lines = f.readlines()
        except Exception as e:
            print(f"Error reading file: {e}")
            sys.exit(1)

    def check_duplicate_keys(self):
        """Check for duplicate citation keys."""
        # Pattern to match entry declarations: @type{key,
        entry_pattern = re.compile(r'^\s*@(\w+)\s*\{\s*([^,\s]+)\s*,', re.IGNORECASE)

        for line_num, line in enumerate(self.lines, 1):
            match = entry_pattern.match(line)
            if match:
                entry_type, key = match.groups()
                self.entry_keys[key].append(line_num)

        # Report duplicates
        for key, line_nums in self.entry_keys.items():
            if len(line_nums) > 1:
                locations = ", ".join(str(ln) for ln in line_nums)
                self.issues.append(SyntaxIssue(
                    line_nums[0],
                    "ERROR",
                    f"Duplicate citation key '{key}' (also appears on lines: {locations})"
                ))

    def check_entry_types(self):
        """Check for invalid entry types."""
        entry_pattern = re.compile(r'^\s*@(\w+)\s*\{', re.IGNORECASE)

        for line_num, line in enumerate(self.lines, 1):
            match = entry_pattern.match(line)
            if match:
                entry_type = match.group(1).lower()
                if entry_type not in self.valid_entry_types:
                    self.issues.append(SyntaxIssue(
                        line_num,
                        "ERROR",
                        f"Invalid entry type '@{match.group(1)}' (valid types: article, book, inproceedings, etc.)",
                        line.strip()
                    ))

    def check_brace_balance(self):
        """Check for unmatched braces within entries."""
        inside_entry = False
        brace_count = 0
        entry_start = 0
        entry_key = ""

        entry_pattern = re.compile(r'^\s*@(\w+)\s*\{\s*([^,\s]+)', re.IGNORECASE)

        for line_num, line in enumerate(self.lines, 1):
            # Check if we're starting a new entry
            match = entry_pattern.match(line)
            if match:
                if inside_entry and brace_count != 0:
                    self.issues.append(SyntaxIssue(
                        entry_start,
                        "ERROR",
                        f"Unmatched braces in entry '{entry_key}' (started at line {entry_start})"
                    ))
                inside_entry = True
                brace_count = 0
                entry_start = line_num
                entry_key = match.group(2)

            if inside_entry:
                # Count braces (but ignore those in strings)
                # This is a simplified check - proper parsing would need to handle escaped braces
                for char in line:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1

                if brace_count < 0:
                    self.issues.append(SyntaxIssue(
                        line_num,
                        "ERROR",
                        f"Too many closing braces in entry '{entry_key}'",
                        line.strip()
                    ))
                    brace_count = 0  # Reset to continue checking

                if brace_count == 0 and inside_entry:
                    inside_entry = False

        # Check if last entry was properly closed
        if inside_entry and brace_count != 0:
            self.issues.append(SyntaxIssue(
                entry_start,
                "ERROR",
                f"Entry '{entry_key}' starting at line {entry_start} is not properly closed (unclosed braces)"
            ))

    def check_field_formatting(self):
        """Check for common field formatting issues."""
        inside_entry = False
        entry_key = ""
        entry_start = 0
        in_multiline_field = False
        multiline_brace_count = 0

        entry_pattern = re.compile(r'^\s*@(\w+)\s*\{\s*([^,\s]+)', re.IGNORECASE)
        field_pattern = re.compile(r'^\s*(\w+)\s*=', re.IGNORECASE)
        closing_pattern = re.compile(r'^\s*\}')

        for line_num, line in enumerate(self.lines, 1):
            # Skip comments
            if line.strip().startswith('%'):
                continue

            # Check if we're starting a new entry
            match = entry_pattern.match(line)
            if match:
                inside_entry = True
                entry_key = match.group(2)
                entry_start = line_num
                in_multiline_field = False
                multiline_brace_count = 0
                # Check if entry starts without a comma after key
                if not re.search(r',\s*$', line):
                    # Could be on the same line or next line - check next line
                    if line_num < len(self.lines):
                        next_line = self.lines[line_num]
                        if not field_pattern.match(next_line) and not closing_pattern.match(next_line):
                            self.issues.append(SyntaxIssue(
                                line_num,
                                "WARNING",
                                f"Entry declaration might be missing comma after key '{entry_key}'",
                                line.strip()
                            ))
                continue

            if inside_entry:
                # Check if this is a closing brace
                if closing_pattern.match(line):
                    inside_entry = False
                    in_multiline_field = False
                    continue

                # Check if this is a field declaration
                field_match = field_pattern.match(line)
                if field_match:
                    field_name = field_match.group(1)

                    # Count braces to detect multi-line field values
                    # After the '=' sign, count braces
                    after_equals = line.split('=', 1)[1] if '=' in line else ""
                    open_braces = after_equals.count('{')
                    close_braces = after_equals.count('}')
                    multiline_brace_count = open_braces - close_braces

                    if multiline_brace_count > 0:
                        # This field value continues on next line(s)
                        in_multiline_field = True
                        continue

                    # Single-line field - check if it needs a comma
                    if line_num < len(self.lines):
                        next_line = self.lines[line_num].strip()
                        if next_line and not next_line.startswith('%'):
                            # If next line is a field or closing brace, current line needs comma
                            if field_pattern.match(next_line) or closing_pattern.match(next_line):
                                if not re.search(r',\s*$', line):
                                    self.issues.append(SyntaxIssue(
                                        line_num,
                                        "ERROR",
                                        f"Field '{field_name}' in entry '{entry_key}' missing comma at end",
                                        line.strip()[:80]
                                    ))
                elif in_multiline_field:
                    # Continue counting braces for multi-line field
                    multiline_brace_count += line.count('{') - line.count('}')
                    if multiline_brace_count <= 0:
                        # Multi-line field ended, check for comma
                        in_multiline_field = False
                        if line_num < len(self.lines):
                            next_line = self.lines[line_num].strip()
                            if next_line and not next_line.startswith('%'):
                                if field_pattern.match(next_line) or closing_pattern.match(next_line):
                                    if not re.search(r',\s*$', line):
                                        self.issues.append(SyntaxIssue(
                                            line_num,
                                            "ERROR",
                                            f"Multi-line field in entry '{entry_key}' missing comma at end",
                                            line.strip()[:80]
                                        ))

    def check_string_delimiters(self):
        """Check for proper string delimiters in field values."""
        inside_entry = False
        entry_key = ""

        entry_pattern = re.compile(r'^\s*@(\w+)\s*\{\s*([^,\s]+)', re.IGNORECASE)
        field_pattern = re.compile(r'^\s*(\w+)\s*=\s*(.+)', re.IGNORECASE)

        for line_num, line in enumerate(self.lines, 1):
            if line.strip().startswith('%'):
                continue

            match = entry_pattern.match(line)
            if match:
                inside_entry = True
                entry_key = match.group(2)
                continue

            if inside_entry:
                field_match = field_pattern.match(line)
                if field_match:
                    field_name = field_match.group(1)
                    field_value = field_match.group(2).strip()

                    # Field values should start with { or "
                    if field_value and not field_value.startswith(('{', '"', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9')):
                        # Check if it's a string macro (all caps) or number
                        if not field_value[0].isupper() and not field_value.split()[0].isdigit():
                            self.issues.append(SyntaxIssue(
                                line_num,
                                "WARNING",
                                f"Field '{field_name}' in entry '{entry_key}' has unusual value delimiter",
                                line.strip()[:80]
                            ))

                if line.strip() == '}':
                    inside_entry = False

    def check_special_characters(self):
        """Check for unescaped special characters."""
        inside_entry = False
        entry_key = ""

        entry_pattern = re.compile(r'^\s*@(\w+)\s*\{\s*([^,\s]+)', re.IGNORECASE)

        for line_num, line in enumerate(self.lines, 1):
            if line.strip().startswith('%'):
                continue

            match = entry_pattern.match(line)
            if match:
                inside_entry = True
                entry_key = match.group(2)
                continue

            if inside_entry:
                # Check for unescaped ampersands (but not in URLs)
                if '&' in line and 'url' not in line.lower() and 'doi' not in line.lower():
                    if re.search(r'(?<!\\)&(?!amp;)', line):
                        self.issues.append(SyntaxIssue(
                            line_num,
                            "WARNING",
                            f"Entry '{entry_key}' may contain unescaped ampersand (use \\&)",
                            line.strip()[:80]
                        ))

                if line.strip() == '}':
                    inside_entry = False

    def check_all(self):
        """Run all syntax checks."""
        print(f"\nChecking syntax of: {self.filepath}")
        print("=" * 60)

        self.check_duplicate_keys()
        self.check_entry_types()
        self.check_brace_balance()
        self.check_field_formatting()
        self.check_string_delimiters()
        self.check_special_characters()

    def generate_report(self) -> str:
        """Generate a syntax report."""
        report = []

        # Sort issues by line number
        errors = [i for i in self.issues if i.severity == "ERROR"]
        warnings = [i for i in self.issues if i.severity == "WARNING"]

        errors.sort(key=lambda x: x.line_num)
        warnings.sort(key=lambda x: x.line_num)

        report.append("\n" + "=" * 60)
        report.append("BIBTEX SYNTAX CHECK REPORT")
        report.append("=" * 60)

        if errors:
            report.append(f"\nERRORS FOUND: {len(errors)}")
            report.append("-" * 60)
            for error in errors:
                report.append(str(error))

        if warnings:
            report.append(f"\nWARNINGS: {len(warnings)}")
            report.append("-" * 60)
            for warning in warnings:
                report.append(str(warning))

        if not errors and not warnings:
            report.append("\n✓ No syntax issues found!")
            report.append("\nNote: This checker validates basic syntax only.")
            report.append("For semantic validation (missing fields, formatting, etc.),")
            report.append("use 'biblatex_cleaner.py' after fixing syntax errors.")

        report.append("\n" + "=" * 60)

        # Add summary
        if errors:
            report.append("\nNEXT STEPS:")
            report.append("1. Fix the ERROR items above (these prevent parsing)")
            report.append("2. Review and fix WARNING items (recommended)")
            report.append("3. Run biblatex_cleaner.py for detailed formatting checks")
            report.append("4. Run biblatex_diagnostics.py to validate against APIs")
            report.append("=" * 60)

        return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(
        description='BibTeX Syntax Checker - Pre-validation before parsing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check syntax
  python biblatex_syntax_checker.py input.bib

  # Save report to file
  python biblatex_syntax_checker.py input.bib -r report.txt

This tool performs text-based analysis to find syntax errors that would
prevent pybtex from parsing your .bib file. Run this BEFORE other tools.
        """
    )

    parser.add_argument('input_file', help='Input BibTeX file')
    parser.add_argument('-r', '--report-file', help='Save report to file')

    args = parser.parse_args()

    # Initialize checker
    checker = BibTeXSyntaxChecker(args.input_file)

    try:
        checker.load_file()
        checker.check_all()
        report = checker.generate_report()

        if args.report_file:
            with open(args.report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\n✓ Report saved to: {args.report_file}")
        else:
            print(report)

        # Exit with error code if errors found
        errors = [i for i in checker.issues if i.severity == "ERROR"]
        if errors:
            sys.exit(1)

    except FileNotFoundError:
        print(f"Error: File '{args.input_file}' not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
