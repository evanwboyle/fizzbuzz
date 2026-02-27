import os
import sys
import pandas as pd
from datetime import datetime
from pathlib import Path
import anthropic

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


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
prompt_path = Path(__file__).resolve().parent / "prompt.md"
if not prompt_path.is_file():
    raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
prompt_template = prompt_path.read_text(encoding="utf-8")
prompt = prompt_template.replace("[PASTE CSV HERE]", csv_text)

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
        system="You are a witty college newsletter writer.",
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

# ---- Stream to file and console ----
token_count = 0
char_count = 0
with stream as s, open(output_file, "w", encoding="utf-8") as f:
    for text in s.text_stream:
        f.write(text)
        f.flush()
        char_count += len(text)
        # Print a progress dot every ~500 chars
        new_token_count = char_count // 500
        if new_token_count > token_count:
            dots = new_token_count - token_count
            print("." * dots, end="", flush=True)
            token_count = new_token_count

    # Get final message for metadata
    response = s.get_final_message()

print(f"\n\n--- Generation complete ---")
print(f"Output chars: {char_count:,}")
print(f"Input tokens: {response.usage.input_tokens:,}")
print(f"Output tokens: {response.usage.output_tokens:,}")
print(f"Stop reason: {response.stop_reason}")
if response.stop_reason == "max_tokens":
    print("WARNING: Output was truncated! The model hit the max_tokens limit.")
    print("The HTML file is likely incomplete.")
print(f"Saved to: {output_file}")