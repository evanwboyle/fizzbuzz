import os
import re
import pandas as pd
from datetime import datetime
from pathlib import Path
import anthropic

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
SCRIPT_DIR = Path(__file__).resolve().parent


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


load_env_file(ENV_PATH)

# ---- Load API config ----
# Set these in your environment before running:
# export ANTHROPIC_BASE_URL=https://api.minimax.io
# export ANTHROPIC_API_KEY="YOUR_MINIMAX_API_KEY"
# Backward compatibility:
# OPENAI_BASE_URL and OPENAI_API_KEY are also accepted.
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

# ---- Get CSV path ----
csv_path = "crawl-results-new.csv"

if not os.path.isfile(csv_path):
    raise FileNotFoundError("crawl-results-new.csv not found in current directory.")

# ---- Load Fizz posts ----
df = pd.read_csv(csv_path)
csv_text = df.to_string(index=False)

# ---- Load prompt template from prompt.md ----
prompt_path = SCRIPT_DIR / "prompt.md"
if not prompt_path.is_file():
    raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
prompt_template = prompt_path.read_text(encoding="utf-8")
prompt = prompt_template.replace("[PASTE CSV HERE]", csv_text)

# ---- Load HTML template ----
template_path = SCRIPT_DIR / "template.html"
if not template_path.is_file():
    raise FileNotFoundError(f"HTML template not found: {template_path}")
html_template = template_path.read_text(encoding="utf-8")

# ---- Prepare output file ----
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = f"fizz_email_{timestamp}.html"

# ---- Call MiniMax via Anthropic SDK (streaming) ----
print(f"Prompt size: {len(prompt):,} chars ({len(df)} posts loaded)")
print(f"Model: MiniMax-M2.1 | max_tokens: 16000")
print(f"Output: {output_file}")
print(f"Streaming...\n")

try:
    stream = client.messages.stream(
        model="MiniMax-M2.1",
        max_tokens=16000,
        system="You are a witty college newsletter writer. Output ONLY the delimited content blocks as instructed — no full HTML documents.",
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


# ---- Extract delimited blocks and assemble HTML ----
def extract_block(raw: str, name: str) -> str | None:
    pattern = rf"<!--{name}-->(.*?)<!--/{name}-->"
    match = re.search(pattern, raw, re.DOTALL)
    return match.group(1).strip() if match else None


issue_info = extract_block(raw_output, "ISSUE_INFO")
ticker = extract_block(raw_output, "TICKER")
sections = extract_block(raw_output, "SECTIONS")
footer_except = extract_block(raw_output, "FOOTER_EXCEPT")

if all([issue_info, ticker, sections, footer_except]):
    final_html = html_template
    final_html = final_html.replace("{{ISSUE_INFO}}", issue_info)
    final_html = final_html.replace("{{TICKER_CONTENT}}", ticker)
    final_html = final_html.replace("{{SECTIONS}}", sections)
    final_html = final_html.replace("{{FOOTER_EXCEPT}}", footer_except)
    print("\n[Template assembly: OK]")
else:
    missing = [name for name, val in [
        ("ISSUE_INFO", issue_info), ("TICKER", ticker),
        ("SECTIONS", sections), ("FOOTER_EXCEPT", footer_except)
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
