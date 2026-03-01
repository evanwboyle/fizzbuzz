#!/usr/bin/env python3
"""
assemble.py
Combines a raw AI output file with the MJML template, compiles to email-safe HTML.

Usage:
    python3 assemble.py                          # uses latest fizz_raw_*.html
    python3 assemble.py --file email/output/fizz_raw_20260228_153608.html
    python3 assemble.py --template email/input/template.mjml  # custom template

Assembly logic lives in generate-email.py; this script is a thin CLI wrapper.
"""

import glob
import argparse
from pathlib import Path

# Import shared assembly logic from generate-email.py
from importlib.util import spec_from_file_location, module_from_spec

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent

_spec = spec_from_file_location("generate_email", _SCRIPT_DIR / "generate-email.py")
_mod = module_from_spec(_spec)
_spec.loader.exec_module(_mod)

assemble_html = _mod.assemble_html
extract_block = _mod.extract_block


def find_latest_raw() -> Path:
    pattern = str(_SCRIPT_DIR / "output" / "fizz_raw_*.html")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            "No fizz_raw_*.html files found in email/output/. "
            "Run generate-email.py --raw first."
        )
    return Path(files[-1])


def main():
    parser = argparse.ArgumentParser(
        description="Assemble a raw AI output file with the MJML template"
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
        help="Path to the MJML template (default: email/input/template.mjml)",
    )
    args = parser.parse_args()

    # Resolve raw file
    if args.file:
        raw_path = Path(args.file)
        if not raw_path.is_absolute():
            raw_path = _ROOT / raw_path
    else:
        raw_path = find_latest_raw()

    if not raw_path.is_file():
        raise FileNotFoundError(f"Raw file not found: {raw_path}")

    # Resolve template
    if args.template:
        template_path = Path(args.template)
        if not template_path.is_absolute():
            template_path = _ROOT / template_path
    else:
        template_path = _SCRIPT_DIR / "input" / "template.mjml"

    if not template_path.is_file():
        raise FileNotFoundError(f"Template not found: {template_path}")

    print(f"Raw input:  {raw_path.name}")
    print(f"Template:   {template_path.name}")

    raw_output = raw_path.read_text(encoding="utf-8")
    mjml_template = template_path.read_text(encoding="utf-8")

    final_html = assemble_html(raw_output, mjml_template)
    if final_html is None:
        blocks = ["TICKER", "SECTIONS", "FOOTER_EXCEPT"]
        missing = [b for b in blocks if extract_block(raw_output, b) is None]
        raise ValueError(
            f"Could not find delimited blocks in {raw_path.name}: {', '.join(missing)}"
        )

    # Derive output name from raw file: fizz_raw_... -> fizz_email_...
    out_name = raw_path.name.replace("fizz_raw_", "fizz_email_")
    output_path = _SCRIPT_DIR / "output" / out_name

    output_path.write_text(final_html, encoding="utf-8")
    print(f"[Assembly OK]")
    print(f"Output:     {output_path}")
    print(f"Chars:      {len(final_html):,}")


if __name__ == "__main__":
    main()
