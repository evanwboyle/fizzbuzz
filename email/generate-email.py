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
        # Next issue is line count + 1 (current edition hasn't been logged yet)
        issue_num = len(lines) + 1
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
            ["npx", "mjml", tmp_in_path, "-o", tmp_out_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"[MJML compiler stderr]: {result.stderr.strip()}")
        html = Path(tmp_out_path).read_text(encoding="utf-8")
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
    sections = extract_block(raw_output, "SECTIONS")
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
    df = pd.read_csv(csv_path)
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
    print(f"Model: MiniMax-M2.1 | max_tokens: 16000")
    print(f"Output: {output_file}")
    print(f"Streaming...\n")

    try:
        stream = client.messages.stream(
            model="MiniMax-M2.1",
            max_tokens=16000,
            system="You are a witty college newsletter writer. Output ONLY the delimited content blocks as instructed. Use MJML components (mj-section, mj-column, mj-text, mj-image) for the SECTIONS block — no raw HTML divs with CSS classes, no full documents.",
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
