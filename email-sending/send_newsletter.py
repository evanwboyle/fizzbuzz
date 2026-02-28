#!/usr/bin/env python3
"""
send_newsletter.py
Sends the latest FizzBuzz HTML newsletter to a list of recipients via SendGrid.

Usage:
    python3 send_newsletter.py
    python3 send_newsletter.py --file article-composition/fizz_email_20240227_120000.html

Setup:
    pip install sendgrid python-dotenv
    Add SENDGRID_API_KEY, SENDER_EMAIL, and SENDER_NAME to your .env file
    Create a .mailing_list file in the fizzbuzz root with one email per line
"""

import os
import glob
import argparse
from pathlib import Path
from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, To

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

    print("🚀 Sending...")
    status = send_newsletter(html, recipients, EMAIL_SUBJECT)

    if status in (200, 202):
        print(f"✅ Sent successfully! (HTTP {status})")
    else:
        print(f"⚠️  Unexpected status code: {status}")


if __name__ == "__main__":
    main()
