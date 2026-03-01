#!/usr/bin/env python3
"""
send_newsletter.py
Sends the latest FizzBuzz HTML newsletter to a list of recipients via SendGrid.

Usage:
    python3 send.py
    python3 send.py --file email/output/fizz_email_20240227_120000.html
    python3 send_newsletter.py --sample              # launch web GUI for sample sends
    python3 send_newsletter.py --sample --port 8080  # custom port

Setup:
    pip install sendgrid python-dotenv flask
    Add SENDGRID_API_KEY, SENDER_EMAIL, and SENDER_NAME to your .env file
    Create a .mailing_list file in the fizzbuzz root with one email per line
"""

import os
import re
import glob
import argparse
import webbrowser
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
    pattern = str(ROOT / "email" / "output" / "fizz_email_*.html")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            "No fizz_email_*.html files found in email/output/. "
            "Run generate-email.py first."
        )
    return Path(files[-1])


def load_html(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def prepare_for_email(html: str) -> str:
    """Minimal cleanup for MJML-compiled HTML before sending.

    MJML output is already email-safe (inlined styles, table layout, no CSS
    variables or animations). This function only strips stray markdown fences
    the LLM might have left in.
    """
    html = re.sub(r"^```html?\s*\n", "", html)
    html = re.sub(r"\n```\s*$", "", html)
    return html


def find_sample_newsletter() -> Path:
    """Return the most recent fizz_sample_*.html, falling back to fizz_email_*.html."""
    for prefix in ("fizz_sample_", "fizz_email_"):
        pattern = str(ROOT / "email" / "output" / f"{prefix}*.html")
        files = sorted(glob.glob(pattern))
        if files:
            return Path(files[-1])
    raise FileNotFoundError(
        "No fizz_sample_*.html or fizz_email_*.html files found in email/output/. "
        "Run generate-email.py first."
    )


# ── Sample-send web GUI ─────────────────────────────────────────────────────

SAMPLE_PAGE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FizzBuzz — Get a Sample</title>
<link href="https://fonts.googleapis.com/css2?family=Unbounded:wght@400;700;900&family=Open+Sans:wght@400;700&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    min-height:100vh;display:flex;align-items:center;justify-content:center;
    background:#0e0e14;color:#fefefe;font-family:'Open Sans',sans-serif;
    padding:2rem;
  }
  .card{
    background:#1a1a24;border-radius:20px;padding:3rem;max-width:460px;width:100%;
    box-shadow:0 0 60px rgba(200,241,53,.12);
    text-align:center;
  }
  h1{
    font-family:'Unbounded',sans-serif;font-weight:900;font-size:2.2rem;
    background:linear-gradient(135deg,#c8f135,#ff3d9a,#1a6bff);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    margin-bottom:.4rem;
  }
  .tagline{color:#aaa;font-size:.95rem;margin-bottom:2rem}
  .field{position:relative;margin-bottom:1.4rem;text-align:left}
  label{display:block;font-size:.8rem;color:#888;margin-bottom:.35rem;text-transform:uppercase;letter-spacing:.06em}
  input[type=email]{
    width:100%;padding:.85rem 1rem;border:2px solid #333;border-radius:10px;
    background:#0e0e14;color:#fefefe;font-size:1rem;outline:none;
    transition:border-color .2s;
  }
  input[type=email]:focus{border-color:#c8f135}
  button{
    width:100%;padding:.95rem;border:none;border-radius:10px;cursor:pointer;
    font-family:'Unbounded',sans-serif;font-weight:700;font-size:1rem;
    background:linear-gradient(135deg,#c8f135,#ffe916);color:#0e0e14;
    transition:transform .15s,box-shadow .15s;
  }
  button:hover{transform:translateY(-2px);box-shadow:0 6px 24px rgba(200,241,53,.3)}
  button:active{transform:translateY(0)}
  .msg{margin-top:1.2rem;padding:.8rem;border-radius:8px;font-size:.9rem;display:none}
  .msg.ok{display:block;background:rgba(200,241,53,.12);color:#c8f135;border:1px solid rgba(200,241,53,.25)}
  .msg.err{display:block;background:rgba(255,61,154,.12);color:#ff3d9a;border:1px solid rgba(255,61,154,.25)}
  .preview{margin-top:1.6rem;text-align:left}
  .preview summary{cursor:pointer;color:#888;font-size:.85rem}
  .preview iframe{
    width:100%;height:500px;border:2px solid #333;border-radius:10px;margin-top:.6rem;
    background:#fff;
  }
</style>
</head>
<body>
<div class="card">
  <h1>FizzBuzz</h1>
  <p class="tagline">Yale's Daily Digest — enter your email for a free sample issue.</p>
  <form id="f" method="post">
    <div class="field">
      <label for="email">Email address</label>
      <input type="email" id="email" name="email" placeholder="you@yale.edu" required autofocus>
    </div>
    <button type="submit">Send me a sample</button>
  </form>
  <div class="msg" id="msg"></div>
  <details class="preview">
    <summary>Preview this issue</summary>
    <iframe src="/preview" sandbox="allow-same-origin"></iframe>
  </details>
</div>
<script>
document.getElementById('f').addEventListener('submit',async e=>{
  e.preventDefault();
  const btn=e.target.querySelector('button');
  const msg=document.getElementById('msg');
  const email=document.getElementById('email').value;
  btn.disabled=true;btn.textContent='Sending...';
  msg.className='msg';
  try{
    const r=await fetch('/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email})});
    const d=await r.json();
    if(r.ok){msg.className='msg ok';msg.textContent=d.message;}
    else{msg.className='msg err';msg.textContent=d.error||'Something went wrong.';}
  }catch(err){msg.className='msg err';msg.textContent='Network error.';}
  btn.disabled=false;btn.textContent='Send me a sample';
});
</script>
</body>
</html>
"""


def run_sample_server(newsletter_path: Path, port: int):
    """Launch a local Flask app that lets visitors request a sample email."""
    from flask import Flask, request, jsonify

    raw_html = load_html(newsletter_path)
    prepared_html = prepare_for_email(raw_html)

    app = Flask(__name__)

    @app.route("/")
    def index():
        return SAMPLE_PAGE_HTML

    @app.route("/preview")
    def preview():
        return raw_html

    @app.route("/send", methods=["POST"])
    def send_sample():
        data = request.get_json(force=True)
        email = (data.get("email") or "").strip()
        if not email or "@" not in email:
            return jsonify(error="Please enter a valid email address."), 400
        try:
            status = send_newsletter(
                prepared_html, [email], EMAIL_SUBJECT
            )
        except Exception as exc:
            return jsonify(error=str(exc)), 500
        if status in (200, 202):
            return jsonify(message=f"Sample sent to {email}!")
        return jsonify(error=f"SendGrid returned HTTP {status}"), 502

    url = f"http://localhost:{port}"
    print(f"📄 Sample newsletter: {newsletter_path.name}")
    print(f"🌐 Server running at {url}")
    print(f"   Press Ctrl+C to stop.\n")
    webbrowser.open(url)
    app.run(host="0.0.0.0", port=port, debug=False)


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
    parser.add_argument(
        "--sample", "-s",
        action="store_true",
        help="Launch a web GUI where visitors can request a sample email"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=5050,
        help="Port for the sample-send web server (default: 5050)"
    )
    args = parser.parse_args()

    # ── Resolve newsletter file ──────────────────────────────────────────
    if args.file:
        newsletter_path = Path(args.file)
        if not newsletter_path.is_absolute():
            newsletter_path = ROOT / newsletter_path
    elif args.sample:
        newsletter_path = find_sample_newsletter()
    else:
        newsletter_path = find_latest_newsletter()

    # ── Sample mode: launch web GUI ──────────────────────────────────────
    if args.sample:
        run_sample_server(newsletter_path, args.port)
        return

    # ── Normal bulk-send mode ────────────────────────────────────────────
    recipients = load_mailing_list()

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
