import os
import re
import json
import argparse
import subprocess
import tempfile
from datetime import datetime, date
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
SCRIPT_DIR = Path(__file__).resolve().parent

# ── Color definitions ────────────────────────────────────────────────

PILL_COLORS = {
    "pink":   ("background:#ff3d9a;color:#ffffff;", "#ff3d9a"),
    "blue":   ("background:#1a6bff;color:#ffffff;", "#1a6bff"),
    "lime":   ("background:#c8f135;color:#0e0e14;", "#c8f135"),
    "orange": ("background:#ff6b1a;color:#ffffff;", "#ff6b1a"),
    "yellow": ("background:#ffe916;color:#0e0e14;", "#ffe916"),
    "dark":   ("background:#0e0e14;color:#c8f135;", "#0e0e14"),
}

CAMP_COLORS = {
    "lime":   ("background-color=\"#e6ffb0\"", "border=\"2px solid #c8f135\""),
    "green":  ("background-color=\"#e6ffb0\"", "border=\"2px solid #c8f135\""),
    "pink":   ("background-color=\"#fff0fa\"", "border=\"2px solid #ff3d9a\""),
    "orange": ("background-color=\"#fff3e8\"", "border=\"2px solid #ff6b1a\""),
    "blue":   ("background-color=\"#dff4ff\"", "border=\"2px solid #1a6bff\""),
}

CAPTION_COLORS = {
    "lime":   "background:#c8f135;color:#0e0e14;",
    "blue":   "background:#1a6bff;color:#ffffff;",
    "pink":   "background:#ff3d9a;color:#ffffff;",
}


# ── Shorthand expansion ─────────────────────────────────────────────

def _attr(tag: str, name: str, default: str = "") -> str:
    """Extract an attribute value from a tag string."""
    m = re.search(rf'{name}="([^"]*)"', tag)
    return m.group(1) if m else default


def expand_shorthand(raw: str) -> str:
    """Convert compact fb- shorthand tags into full MJML markup."""
    out = raw

    # ── fb-zigzag (self-closing) ──
    out = re.sub(
        r'<fb-zigzag\s*/?>',
        '<mj-section padding="0">\n  <mj-column><mj-text padding="0"><div style="height:12px;background:repeating-linear-gradient(135deg,#c8f135 0px,#c8f135 8px,#ff3d9a 8px,#ff3d9a 16px,#1a6bff 16px,#1a6bff 24px,#ff6b1a 24px,#ff6b1a 32px,#ffe916 32px,#ffe916 40px);"></div></mj-text></mj-column>\n</mj-section>',
        out,
    )

    # ── fb-section / fb-title ──
    # Regex to find nested fb-* components (except fb-title) that the model
    # may have placed inside a section. These need to live OUTSIDE the
    # mj-section so subsequent handlers can expand them properly.
    _NESTED_FB_RE = re.compile(
        r'(<fb-(?:image|quote|stats|camp|weather|potd)\b[\s\S]*?(?:/>|</fb-(?:image|quote|stats|camp|weather|potd)>))',
    )

    def _expand_section(m):
        tag = m.group(1)
        body = m.group(2)
        color = _attr(tag, "color", "pink")
        label = _attr(tag, "label", "Section")
        pill_style = PILL_COLORS.get(color, PILL_COLORS["pink"])[0]

        # Extract title
        title_m = re.search(r'<fb-title>(.*?)</fb-title>', body, re.DOTALL)
        title_html = title_m.group(1).strip() if title_m else ""
        body_no_title = re.sub(r'<fb-title>.*?</fb-title>', '', body, flags=re.DOTALL)

        # Pull out any nested fb-* components so they don't get trapped in mj-text
        nested_components = _NESTED_FB_RE.findall(body_no_title)
        body_content = _NESTED_FB_RE.sub('', body_no_title).strip()

        section_mjml = (
            f'<mj-section background-color="#fefefe" padding="0 24px">\n'
            f'  <mj-column>\n'
            f'    <mj-text padding="8px 0 0 0" font-family="\'Chivo Mono\', monospace" font-size="9px" font-weight="700" letter-spacing="1px">\n'
            f'      <span style="{pill_style}padding:4px 10px;text-transform:uppercase;">{label}</span>\n'
            f'    </mj-text>\n'
            f'    <mj-text padding="8px 0 16px 0" font-family="\'Archivo Black\', sans-serif" font-size="24px" line-height="1.2" color="#0e0e14">\n'
            f'      {title_html}\n'
            f'    </mj-text>\n'
            f'    <mj-text padding="0 0 12px 0" font-family="\'Open Sans\', Arial, sans-serif" font-size="14px" line-height="1.6" color="#0e0e14">\n'
            f'      {body_content}\n'
            f'    </mj-text>\n'
            f'  </mj-column>\n'
            f'</mj-section>'
        )

        # Append extracted components after the section for later expansion
        if nested_components:
            section_mjml += '\n' + '\n'.join(nested_components)

        return section_mjml

    out = re.sub(r'<fb-section([^>]*)>(.*?)</fb-section>', _expand_section, out, flags=re.DOTALL)

    # ── fb-camp ──
    def _expand_camp(m):
        tag = m.group(1)
        body = m.group(2).strip()
        name = _attr(tag, "name", "Camp")
        color = _attr(tag, "color", "lime")
        bg, border = CAMP_COLORS.get(color, CAMP_COLORS["lime"])

        return (
            f'<mj-section {bg} padding="0 24px" {border}>\n'
            f'  <mj-column>\n'
            f'    <mj-text padding="16px 16px 0 16px" font-family="\'Chivo Mono\', monospace" font-size="10px" font-weight="700" letter-spacing="1px" text-transform="uppercase" color="#0e0e14">\n'
            f'      {name}\n'
            f'    </mj-text>\n'
            f'    <mj-text padding="8px 16px 16px 16px" font-family="\'Open Sans\', Arial, sans-serif" font-size="14px" line-height="1.6" color="#0e0e14">\n'
            f'      {body}\n'
            f'    </mj-text>\n'
            f'  </mj-column>\n'
            f'</mj-section>'
        )

    out = re.sub(r'<fb-camp([^>]*)>(.*?)</fb-camp>', _expand_camp, out, flags=re.DOTALL)

    # ── fb-stats / fb-stat ──
    def _expand_stats(m):
        body = m.group(1)
        pills = []
        for sm in re.finditer(r'<fb-stat([^>]*)>(.*?)</fb-stat>', body, re.DOTALL):
            color = _attr(sm.group(1), "color", "lime")
            text = sm.group(2).strip()
            style = PILL_COLORS.get(color, PILL_COLORS["lime"])[0]
            pills.append(f'<span style="{style}padding:6px 12px;border-radius:20px;">{text}</span>')

        return (
            '<mj-section background-color="#fefefe" padding="0 24px">\n'
            '  <mj-column>\n'
            '    <mj-text padding="8px 0" font-family="\'Chivo Mono\', monospace" font-size="10px" font-weight="700">\n'
            f'      {"&nbsp;".join(pills)}\n'
            '    </mj-text>\n'
            '  </mj-column>\n'
            '</mj-section>'
        )

    out = re.sub(r'<fb-stats>(.*?)</fb-stats>', _expand_stats, out, flags=re.DOTALL)

    # ── fb-quote ──
    def _expand_quote(m):
        tag = m.group(1)
        body = m.group(2).strip()
        attribution = _attr(tag, "attribution", "")

        result = (
            '<mj-section background-color="#0e0e14" padding="0 24px" border-left="4px solid #ff3d9a">\n'
            '  <mj-column>\n'
            '    <mj-text padding="24px" font-family="\'Open Sans\', Arial, sans-serif" font-size="16px" font-weight="700" color="#fefefe" line-height="1.5">\n'
            f'      <p>&ldquo;{body}&rdquo;</p>\n'
            '    </mj-text>\n'
        )
        if attribution:
            result += (
                f'    <mj-text padding="0 24px 24px 24px" font-family="\'Chivo Mono\', monospace" font-size="10px" color="#888888">\n'
                f'      {attribution}\n'
                f'    </mj-text>\n'
            )
        result += '  </mj-column>\n</mj-section>'
        return result

    out = re.sub(r'<fb-quote([^>]*)>(.*?)</fb-quote>', _expand_quote, out, flags=re.DOTALL)

    # ── fb-image (self-closing) ──
    def _expand_image(m):
        tag = m.group(1)
        src = _attr(tag, "src")
        # Gmail mobile requires a recognizable image extension in the URL
        if src and not re.search(r'\.(jpe?g|png|gif|webp|svg)(\?|#|$)', src, re.I):
            src += "#.jpg"
        alt = _attr(tag, "alt", "image")
        caption = _attr(tag, "caption", "")
        color = _attr(tag, "color", "lime")
        cap_style = CAPTION_COLORS.get(color, CAPTION_COLORS["lime"])

        result = (
            '<mj-section background-color="#fefefe" padding="0 24px">\n'
            '  <mj-column>\n'
            f'    <mj-image src="{src}" alt="{alt}" padding="20px 0 0 0" width="612px" />\n'
        )
        if caption:
            result += (
                f'    <mj-text padding="0" font-family="\'Chivo Mono\', monospace" font-size="10px" font-weight="700" letter-spacing="1px" text-transform="uppercase">\n'
                f'      <div style="{cap_style}padding:8px 12px;">{caption}</div>\n'
                f'    </mj-text>\n'
            )
        result += '  </mj-column>\n</mj-section>'
        return result

    # Match <fb-image .../>, <fb-image ...>, and <fb-image ...></fb-image>
    out = re.sub(r'<fb-image([\s\S]*?)/\s*>', _expand_image, out)
    out = re.sub(r'<fb-image([^>]*)>(?:\s*</fb-image>)?', _expand_image, out)

    # ── fb-weather ──
    def _expand_weather(m):
        body = m.group(1).strip()
        return (
            '<mj-section background-color="#dff4ff" padding="0 24px" border="2px solid #1a6bff">\n'
            '  <mj-column>\n'
            '    <mj-text padding="16px" font-family="\'Chivo Mono\', monospace" font-size="11px" font-weight="700" color="#0e0e14">\n'
            f'      {body}\n'
            '    </mj-text>\n'
            '  </mj-column>\n'
            '</mj-section>'
        )

    out = re.sub(r'<fb-weather>(.*?)</fb-weather>', _expand_weather, out, flags=re.DOTALL)

    # ── fb-potd ──
    def _expand_potd(m):
        tag = m.group(1)
        body = m.group(2).strip()
        likes = _attr(tag, "likes", "")
        annotation = _attr(tag, "annotation", "")
        footer_text = f"{likes} &mdash; {annotation}" if likes else annotation

        return (
            '<mj-section background-color="#ffe916" padding="24px">\n'
            '  <mj-column>\n'
            '    <mj-text padding="0 0 12px 0" font-family="\'Archivo Black\', sans-serif" font-size="19px" line-height="1.4" color="#0e0e14">\n'
            f'      <p>&ldquo;{body}&rdquo;</p>\n'
            '    </mj-text>\n'
            '    <mj-text padding="0" font-family="\'Chivo Mono\', monospace" font-size="10px" color="rgba(14,14,20,0.7)">\n'
            f'      {footer_text}\n'
            '    </mj-text>\n'
            '  </mj-column>\n'
            '</mj-section>'
        )

    out = re.sub(r'<fb-potd([^>]*)>(.*?)</fb-potd>', _expand_potd, out, flags=re.DOTALL)

    return out


# ── Shared helpers (also used by assemble.py) ────────────────────────

def extract_block(raw: str, name: str) -> str | None:
    pattern = rf"<!--{name}-->(.*?)<!--/{name}-->"
    match = re.search(pattern, raw, re.DOTALL)
    return match.group(1).strip() if match else None


def load_editors_note() -> tuple[str, str]:
    """Return (header_mjml, footer_mjml) from editors-note.json, or empty strings."""
    header_mjml = ""
    footer_mjml = ""
    editors_note_path = SCRIPT_DIR / "input" / "editors-note.json"
    if not editors_note_path.is_file():
        return header_mjml, footer_mjml
    try:
        editors_note = json.loads(editors_note_path.read_text(encoding="utf-8"))
        note_date = editors_note.get("date", "")
        today_str = date.today().isoformat()
        if note_date != today_str:
            print(f"[Editor's note: skipped (date {note_date!r} != today {today_str!r})]")
            return header_mjml, footer_mjml
        header_note = editors_note.get("header", "").strip()
        footer_note = editors_note.get("footer", "").strip()
        if header_note:
            header_mjml = (
                '<mj-section background-color="#0e0e14" padding="10px 32px" border-top="2px solid #ff3d9a">'
                '<mj-column>'
                '<mj-text padding="0" font-family="\'Open Sans\', Arial, sans-serif" font-size="12px" font-style="italic" color="#aaaaaa" line-height="1.6">'
                f'<span style="font-family:\'Chivo Mono\',monospace;font-size:9px;font-weight:700;font-style:normal;text-transform:uppercase;letter-spacing:1px;color:#ff3d9a;">NOTES FROM THE EDITOR:</span> {header_note}'
                '</mj-text>'
                '</mj-column>'
                '</mj-section>'
            )
            print("[Editor's note (header): loaded]")
        if footer_note:
            footer_mjml = (
                '<mj-section background-color="#0e0e14" padding="10px 32px 0 32px" border-bottom="2px solid #c8f135">'
                '<mj-column>'
                '<mj-text padding="0" font-family="\'Open Sans\', Arial, sans-serif" font-size="12px" font-style="italic" color="#aaaaaa" line-height="1.6">'
                f'<span style="font-family:\'Chivo Mono\',monospace;font-size:9px;font-weight:700;font-style:normal;text-transform:uppercase;letter-spacing:1px;color:#ff3d9a;">NOTES FROM THE EDITOR:</span> {footer_note}'
                '</mj-text>'
                '</mj-column>'
                '</mj-section>'
            )
            print("[Editor's note (footer): loaded]")
        if not header_note and not footer_note:
            print("[Editor's note: date matches but both header and footer are empty]")
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[Editor's note: skipped (parse error: {e})]")
    return header_mjml, footer_mjml


VERSION = "1.0.0"


def build_issue_info() -> str:
    """Build issue info from edition-memory.log line count and today's date."""
    memory_path = SCRIPT_DIR / "input" / "edition-memory.log"
    if memory_path.is_file():
        lines = [l for l in memory_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        # Next issue is line count
        issue_num = len(lines)
    else:
        issue_num = 1
    today = date.today()
    date_str = today.strftime("%B %-d, %Y")
    return f"{date_str}<br>No. {issue_num}<br>v{VERSION}"


def compile_mjml(mjml_source: str) -> str:
    """Compile MJML markup to email-safe HTML using npx mjml."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mjml", delete=False, encoding="utf-8"
    ) as tmp_in:
        tmp_in.write(mjml_source)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path.replace(".mjml", ".html")
    try:
        result = subprocess.run(
            ["npx", "mjml", tmp_in_path, "-o", tmp_out_path,
             "--config.minify", "true"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"[MJML compiler stderr]: {result.stderr.strip()}")
        html = Path(tmp_out_path).read_text(encoding="utf-8")
        # Strip MSO/Outlook conditional comments to reduce size for Gmail
        html = re.sub(r'<!--\[if [^\]]*\]>.*?<!\[endif\]-->', '', html, flags=re.DOTALL)
        html = re.sub(r'<!--\[if [^\]]*\]><!-->', '', html)
        html = re.sub(r'<!--<!\[endif\]-->', '', html)
        # Collapse runs of whitespace (newlines/spaces) into single spaces
        html = re.sub(r'\s+', ' ', html)
        # Restore newlines around block tags for readability
        html = re.sub(r'>\s+<', '>\n<', html)
        return html
    finally:
        for p in (tmp_in_path, tmp_out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def assemble_html(raw_output: str, mjml_template: str) -> str | None:
    """Substitute AI content blocks into the MJML template and compile to HTML.

    Returns the compiled email-safe HTML, or None if required blocks are missing.
    """
    ticker = extract_block(raw_output, "TICKER")
    sections_raw = extract_block(raw_output, "SECTIONS")
    sections = expand_shorthand(sections_raw) if sections_raw else None
    footer_except = extract_block(raw_output, "FOOTER_EXCEPT")

    blocks = {
        "TICKER": ticker,
        "SECTIONS": sections,
        "FOOTER_EXCEPT": footer_except,
    }

    missing = [name for name, val in blocks.items() if val is None]
    if missing:
        return None

    editors_header, editors_footer = load_editors_note()
    issue_info = build_issue_info()

    mjml_source = mjml_template
    mjml_source = mjml_source.replace("{{ISSUE_INFO}}", issue_info)
    mjml_source = mjml_source.replace("{{TICKER_CONTENT}}", ticker)
    mjml_source = mjml_source.replace("{{SECTIONS}}", sections)
    mjml_source = mjml_source.replace("{{FOOTER_EXCEPT}}", footer_except)
    mjml_source = mjml_source.replace("{{EDITORS_NOTE_HEADER}}", editors_header)
    mjml_source = mjml_source.replace("{{EDITORS_NOTE_FOOTER}}", editors_footer)

    print("[Compiling MJML to email-safe HTML...]")
    return compile_mjml(mjml_source)


# ── Main generation flow ─────────────────────────────────────────────

def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def main():
    import pandas as pd
    import anthropic

    load_env_file(ENV_PATH)

    # ---- Load API config ----
    base_url = os.getenv("ANTHROPIC_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.minimax.io/anthropic"))
    api_key = os.getenv("ANTHROPIC_API_KEY", os.getenv("OPENAI_API_KEY", ""))

    if not api_key or api_key.startswith("YOUR_"):
        raise RuntimeError(
            "Please set ANTHROPIC_API_KEY (or OPENAI_API_KEY) in .env or your shell to your MiniMax API key"
        )

    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=base_url,
    )

    # ---- Parse arguments ----
    parser = argparse.ArgumentParser(description="Generate FizzBuzz newsletter via AI")
    parser.add_argument(
        "--raw", action="store_true",
        help="Save raw AI output only (no template assembly). Use assemble.py later to combine with template.",
    )
    args = parser.parse_args()

    # ---- Get CSV path ----
    csv_path = str(Path(__file__).resolve().parents[1] / "data" / "crawl-results-new.csv")

    if not os.path.isfile(csv_path):
        raise FileNotFoundError("data/crawl-results-new.csv not found. Run sanitize.py first.")

    # ---- Load Fizz posts ----
    df = pd.read_csv(csv_path, comment="#")
    csv_text = df.to_string(index=False)

    # ---- Load slang glossary ----
    slang_path = SCRIPT_DIR / "input" / "slang-glossary.txt"
    if slang_path.is_file():
        slang_glossary = slang_path.read_text(encoding="utf-8").strip()
    else:
        slang_glossary = "(No slang glossary yet.)"

    # ---- Load edition memory log ----
    memory_path = SCRIPT_DIR / "input" / "edition-memory.log"
    if memory_path.is_file():
        memory_log = memory_path.read_text(encoding="utf-8").strip()
    else:
        memory_log = "(No previous editions yet.)"

    # ---- Load editor alignment note ----
    alignment_path = SCRIPT_DIR / "input" / "alignment.json"
    editor_alignment = "(No editor alignment note for this edition.)"
    if alignment_path.is_file():
        try:
            alignment_data = json.loads(alignment_path.read_text(encoding="utf-8"))
            alignment_date = alignment_data.get("date", "")
            today_str = date.today().isoformat()
            alignment_msg = alignment_data.get("message", "").strip()
            if alignment_date == today_str and alignment_msg:
                editor_alignment = alignment_msg
                print(f"[Editor alignment: loaded]")
            elif alignment_date != today_str:
                print(f"[Editor alignment: skipped (date {alignment_date!r} != today {today_str!r})]")
            else:
                print("[Editor alignment: date matches but message is empty]")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[Editor alignment: skipped (parse error: {e})]")

    # ---- Load prompt template from prompt.md ----
    prompt_path = SCRIPT_DIR / "input" / "prompt.md"
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
    prompt_template = prompt_path.read_text(encoding="utf-8")
    prompt = prompt_template.replace("[PASTE CSV HERE]", csv_text)
    prompt = prompt.replace("[EDITION_MEMORY_LOG]", memory_log)
    prompt = prompt.replace("[SLANG_GLOSSARY]", slang_glossary)
    prompt = prompt.replace("[EDITOR_ALIGNMENT]", editor_alignment)

    # ---- Load MJML template (unless --raw) ----
    mjml_template = None
    if not args.raw:
        template_path = SCRIPT_DIR / "input" / "template.mjml"
        if not template_path.is_file():
            raise FileNotFoundError(f"MJML template not found: {template_path}")
        mjml_template = template_path.read_text(encoding="utf-8")

    # ---- Prepare output file ----
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "fizz_raw" if args.raw else "fizz_email"
    output_file = str(SCRIPT_DIR / "output" / f"{prefix}_{timestamp}.html")

    # ---- Call MiniMax via Anthropic SDK (streaming) ----
    print(f"Prompt size: {len(prompt):,} chars ({len(df)} posts loaded)")
    print(f"Model: MiniMax-M2.5 | max_tokens: 16000")
    print(f"Output: {output_file}")
    print(f"Streaming...\n")

    try:
        stream = client.messages.stream(
            model="MiniMax-M2.5",
            max_tokens=16000,
            system="You are a witty college newsletter writer. Output ONLY the delimited content blocks as instructed. Use fb-* shorthand tags (fb-section, fb-quote, fb-image, fb-zigzag, fb-stats, fb-camp, fb-potd, fb-weather) for the SECTIONS block — no raw MJML, no raw HTML divs, no full documents.",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        }
                    ],
                }
            ],
        )
    except anthropic.AuthenticationError as exc:
        raise RuntimeError(
            "Authentication failed. Ensure your MiniMax key is set as ANTHROPIC_API_KEY "
            "(or OPENAI_API_KEY) and your endpoint is ANTHROPIC_BASE_URL=https://api.minimax.io"
        ) from exc

    # ---- Stream and collect AI output ----
    raw_chunks = []
    token_count = 0
    char_count = 0
    with stream as s:
        for text in s.text_stream:
            raw_chunks.append(text)
            char_count += len(text)
            # Print a progress dot every ~500 chars
            new_token_count = char_count // 500
            if new_token_count > token_count:
                dots = new_token_count - token_count
                print("." * dots, end="", flush=True)
                token_count = new_token_count

        # Get final message for metadata
        response = s.get_final_message()

    raw_output = "".join(raw_chunks)

    # ---- Save edition memory (regardless of HTML assembly success) ----
    edition_memory = extract_block(raw_output, "EDITION_MEMORY")
    if edition_memory:
        memory_line = edition_memory.strip()
        with open(memory_path, "a", encoding="utf-8") as mf:
            mf.write(memory_line + "\n")
        print(f"\n[Edition memory saved to {memory_path.name}]")
    else:
        print("\nWARNING: No EDITION_MEMORY block found in AI output. Memory not updated.")

    # ---- Extract and report unknown slang ----
    unknown_slang = extract_block(raw_output, "UNKNOWN_SLANG")
    if unknown_slang and unknown_slang.strip():
        # Read existing glossary terms to avoid duplicates
        existing_terms = set()
        if slang_path.is_file():
            for line in slang_path.read_text(encoding="utf-8").splitlines():
                term = line.split("=")[0].strip().lower()
                if term:
                    existing_terms.add(term)

        new_terms = [t.strip() for t in unknown_slang.split(",") if t.strip()]
        new_terms = [t for t in new_terms if t.lower() not in existing_terms]

        if new_terms:
            with open(slang_path, "a", encoding="utf-8") as sf:
                for term in new_terms:
                    sf.write(f"{term} = ???\n")
            print(f"[New slang added to {slang_path.name}: {', '.join(new_terms)}]")
            print(f"  -> Edit {slang_path.name} to fill in definitions for terms marked '???'")
        else:
            print("[No new unknown slang found.]")
    else:
        print("[No unknown slang reported.]")

    if args.raw:
        final_html = raw_output
        print("[Raw mode: skipping MJML assembly]")
        print(f"  -> Run assemble.py to combine with template later.")
    else:
        assembled = assemble_html(raw_output, mjml_template)
        if assembled:
            final_html = assembled
            print("[Template assembly: OK]")
        else:
            missing = [name for name, val in [
                ("TICKER", extract_block(raw_output, "TICKER")),
                ("SECTIONS", extract_block(raw_output, "SECTIONS")),
                ("FOOTER_EXCEPT", extract_block(raw_output, "FOOTER_EXCEPT")),
            ] if val is None]
            print(f"\nWARNING: Could not find delimited blocks: {', '.join(missing)}")
            print("Falling back to raw AI output.")
            final_html = raw_output

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(final_html)

    print(f"\n--- Generation complete ---")
    print(f"AI output chars: {char_count:,}")
    print(f"Final HTML chars: {len(final_html):,}")
    print(f"Input tokens: {response.usage.input_tokens:,}")
    print(f"Output tokens: {response.usage.output_tokens:,}")
    print(f"Stop reason: {response.stop_reason}")
    if response.stop_reason == "max_tokens":
        print("WARNING: Output was truncated! The model hit the max_tokens limit.")
        print("The HTML file is likely incomplete.")
    print(f"Saved to: {output_file}")


if __name__ == "__main__":
    main()
