#!/usr/bin/env python3
"""
assemble.py
Combines a raw AI output file with the HTML template to produce a styled newsletter.

Usage:
    python3 assemble.py                          # uses latest fizz_raw_*.html
    python3 assemble.py --file email/output/fizz_raw_20260228_153608.html
    python3 assemble.py --template email/input/template.html  # custom template
"""

import re
import glob
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent


def extract_block(raw: str, name: str) -> str | None:
    pattern = rf"<!--{name}-->(.*?)<!--/{name}-->"
    match = re.search(pattern, raw, re.DOTALL)
    return match.group(1).strip() if match else None


def find_latest_raw() -> Path:
    pattern = str(SCRIPT_DIR / "output" / "fizz_raw_*.html")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            "No fizz_raw_*.html files found in email/output/. "
            "Run generate-email.py --raw first."
        )
    return Path(files[-1])


def assemble(raw_path: Path, template_path: Path) -> str:
    raw_output = raw_path.read_text(encoding="utf-8")
    html_template = template_path.read_text(encoding="utf-8")

    issue_info = extract_block(raw_output, "ISSUE_INFO")
    ticker = extract_block(raw_output, "TICKER")
    sections = extract_block(raw_output, "SECTIONS")
    footer_except = extract_block(raw_output, "FOOTER_EXCEPT")

    blocks = {
        "ISSUE_INFO": issue_info,
        "TICKER": ticker,
        "SECTIONS": sections,
        "FOOTER_EXCEPT": footer_except,
    }

    missing = [name for name, val in blocks.items() if val is None]
    if missing:
        raise ValueError(
            f"Could not find delimited blocks in {raw_path.name}: {', '.join(missing)}"
        )

    final = html_template
    final = final.replace("{{ISSUE_INFO}}", issue_info)
    final = final.replace("{{TICKER_CONTENT}}", ticker)
    final = final.replace("{{SECTIONS}}", sections)
    final = final.replace("{{FOOTER_EXCEPT}}", footer_except)
    return final


def main():
    parser = argparse.ArgumentParser(
        description="Assemble a raw AI output file with the HTML template"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="Path to a raw AI output file (default: latest fizz_raw_*.html)",
    )
    parser.add_argument(
        "--template", "-t",
        type=str,
        default=None,
        help="Path to the HTML template (default: email/input/template.html)",
    )
    args = parser.parse_args()

    # Resolve raw file
    if args.file:
        raw_path = Path(args.file)
        if not raw_path.is_absolute():
            raw_path = ROOT / raw_path
    else:
        raw_path = find_latest_raw()

    if not raw_path.is_file():
        raise FileNotFoundError(f"Raw file not found: {raw_path}")

    # Resolve template
    if args.template:
        template_path = Path(args.template)
        if not template_path.is_absolute():
            template_path = ROOT / template_path
    else:
        template_path = SCRIPT_DIR / "input" / "template.html"

    if not template_path.is_file():
        raise FileNotFoundError(f"Template not found: {template_path}")

    print(f"Raw input:  {raw_path.name}")
    print(f"Template:   {template_path.name}")

    final_html = assemble(raw_path, template_path)

    # Derive output name from raw file: fizz_raw_... -> fizz_email_...
    out_name = raw_path.name.replace("fizz_raw_", "fizz_email_")
    output_path = SCRIPT_DIR / "output" / out_name

    output_path.write_text(final_html, encoding="utf-8")
    print(f"[Assembly OK]")
    print(f"Output:     {output_path}")
    print(f"Chars:      {len(final_html):,}")


if __name__ == "__main__":
    main()
