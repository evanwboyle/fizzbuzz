#!/usr/bin/env python3
"""
send_newsletter.py
Sends the latest FizzBuzz HTML newsletter to a list of recipients via SendGrid.

Usage:
    python3 send_newsletter.py
    python3 send_newsletter.py --file article-composition/fizz_email_20240227_120000.html

Setup:
    pip install sendgrid python-dotenv premailer
    Add SENDGRID_API_KEY, SENDER_EMAIL, and SENDER_NAME to your .env file
    Create a .mailing_list file in the fizzbuzz root with one email per line
"""

import os
import re
import glob
import argparse
from pathlib import Path
from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, To
from premailer import transform

# ── Load .env from fizzbuzz root ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# ── Configuration ─────────────────────────────────────────────────────────────
SENDGRID_API_KEY  = os.getenv("SENDGRID_API_KEY")
SENDER_EMAIL      = os.getenv("SENDER_EMAIL")
SENDER_NAME       = os.getenv("SENDER_NAME", "FizzBuzz")
EMAIL_SUBJECT     = os.getenv("EMAIL_SUBJECT", "📰 FizzBuzz — Yale's Daily Digest")
MAILING_LIST_PATH = ROOT / ".mailing_list"

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_mailing_list() -> list[str]:
    """Load recipients from .mailing_list in the fizzbuzz root (one email per line)."""
    if not MAILING_LIST_PATH.exists():
        raise FileNotFoundError(
            f".mailing_list not found at {MAILING_LIST_PATH}\n"
            "Create it with one email address per line."
        )
    emails = [
        line.strip()
        for line in MAILING_LIST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not emails:
        raise ValueError(".mailing_list exists but contains no email addresses.")
    return emails


def find_latest_newsletter() -> Path:
    """Return the most recently generated fizz_email_*.html file."""
    pattern = str(ROOT / "article-composition" / "fizz_email_*.html")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            "No fizz_email_*.html files found in article-composition/. "
            "Run generate-email.py first."
        )
    return Path(files[-1])


def load_html(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ── CSS variable map (must match :root in prompt.md) ─────────────────────────
CSS_VARS = {
    "var(--lime)":          "#c8f135",
    "var(--hot-pink)":      "#ff3d9a",
    "var(--electric-blue)": "#1a6bff",
    "var(--orange)":        "#ff6b1a",
    "var(--yellow)":        "#ffe916",
    "var(--bg)":            "#f0edff",
    "var(--dark)":          "#0e0e14",
    "var(--white)":         "#fefefe",
}

FONT_LINK = (
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Archivo+Black&family=Chivo+Mono:ital,wght@0,300;0,400;0,700;1,400'
    '&family=Unbounded:wght@400;700;900&family=Open+Sans:wght@400;700&display=swap" '
    'rel="stylesheet">'
)


def prepare_for_email(html: str) -> str:
    """Make the newsletter HTML email-client-friendly.

    1. Replace CSS custom properties with literal hex values
    2. Swap @import for a <link> tag (better email client support)
    3. Inline all CSS rules onto elements via premailer
    """
    # 0 — Strip markdown code fences if the LLM left them in
    html = re.sub(r"^```html?\s*\n", "", html)
    html = re.sub(r"\n```\s*$", "", html)

    # 1 — Replace CSS variables with literal values
    for var, value in CSS_VARS.items():
        html = html.replace(var, value)

    # 2 — Replace @import with <link> tag in <head>
    html = re.sub(
        r"@import\s+url\(['\"]https://fonts\.googleapis\.com[^)]+\)['\"]?\s*;?",
        "",
        html,
    )
    html = html.replace("</head>", f"  {FONT_LINK}\n</head>", 1)

    # 3 — Inline CSS (moves <style> rules to inline style attributes)
    html = transform(
        html,
        keep_style_tags=True,      # keep <style> as fallback for clients that support it
        strip_important=False,
        cssutils_logging_level=50,  # suppress cssutils warnings
    )

    # 4 — Prevent Gmail from collapsing repeated structural elements.
    #     Gmail's clipping heuristic triggers on identical adjacent blocks.
    #     Inserting a unique zero-width non-joiner (&#8204;) + hidden span
    #     before each section makes every block look distinct to the parser.
    counter = [0]

    def _unique_marker(match: re.Match) -> str:
        counter[0] += 1
        # Invisible span with unique id — Gmail sees different content each time
        marker = f'<span style="display:none !important;font-size:0;line-height:0;height:0;overflow:hidden;">&#8204;{counter[0]}</span>'
        return marker + match.group(0)

    html = re.sub(r'<div[^>]*class="[^"]*section[^"]*"', _unique_marker, html)
    html = re.sub(r'<div[^>]*class="[^"]*zigzag[^"]*"', _unique_marker, html)
    html = re.sub(r'<div[^>]*class="[^"]*camp-block[^"]*"', _unique_marker, html)
    html = re.sub(r'<div[^>]*class="[^"]*pull-quote[^"]*"', _unique_marker, html)

    return html


def send_newsletter(html_content: str, recipients: list[str], subject: str):
    if not SENDGRID_API_KEY:
        raise ValueError("SENDGRID_API_KEY not set in .env")
    if not SENDER_EMAIL:
        raise ValueError("SENDER_EMAIL not set in .env")

    message = Mail(
        from_email=(SENDER_EMAIL, SENDER_NAME),
        subject=subject,
        html_content=html_content,
    )
    message.to = [To(email) for email in recipients]

    client = SendGridAPIClient(SENDGRID_API_KEY)
    response = client.send(message)
    return response.status_code


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Send FizzBuzz newsletter via SendGrid")
    parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="Path to a specific HTML newsletter file (default: latest)"
    )
    args = parser.parse_args()

    recipients = load_mailing_list()

    if args.file:
        newsletter_path = Path(args.file)
        if not newsletter_path.is_absolute():
            newsletter_path = ROOT / newsletter_path
    else:
        newsletter_path = find_latest_newsletter()

    print(f"📄 Newsletter: {newsletter_path.name}")
    print(f"👥 Recipients: {len(recipients)}")
    print(f"📬 Sender: {SENDER_NAME} <{SENDER_EMAIL}>")
    print(f"📝 Subject: {EMAIL_SUBJECT}")
    print()

    html = load_html(newsletter_path)

    print("🔧 Inlining CSS for email compatibility...")
    html = prepare_for_email(html)

    print("🚀 Sending...")
    status = send_newsletter(html, recipients, EMAIL_SUBJECT)

    if status in (200, 202):
        print(f"✅ Sent successfully! (HTTP {status})")
    else:
        print(f"⚠️  Unexpected status code: {status}")


if __name__ == "__main__":
    main()
