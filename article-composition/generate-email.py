import os
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

# ---- Build the prompt ----
prompt = f"""
You are given a list of Yale Fizz posts from the past 24 hours.

Create a funny, engaging, and informative campus “news feed” email for students who are not on Fizz. The goal is to summarize what people are discussing so non-users feel fully caught up on campus discourse.

Content requirements:
- Cover major campus news, controversies, rumors, and trending arguments.
- Include upcoming parties and social events.
- Highlight anything students are unusually passionate, dramatic, or chaotic about.
- Gently and humorously critique the types of people posting.

Tone:
- Witty, culturally aware, slightly ruthless but playful.
- Observational and sharp.
- Funny but still informative.

Formatting:
- Write it as a visually stunning, highly stylized email.
- Use colorful section headers.
- Use bold and italics throughout.
- Keep paragraphs short.
- Prefer bullet points.
- Add personality and dramatic flair.
- Do NOT use emojis.
- Avoid overused quips like “Congratulations, you played yourself” or “cope unlocked.”

Images:
- Embed 2–3 relevant images pulled directly from the Fizz posts.
- Use the provided image URLs (assume they work).
- Place them naturally within sections and add short captions.

Language:
- Incorporate current Fizz slang such as chud and touse directly.
- Do not put slang in quotation marks.
- Infer meaning from context and use confidently.

Output:
Return ONLY valid HTML for the email body. Do not include explanations.

Here are the Fizz posts:

{csv_text}
"""

# ---- Call MiniMax via Anthropic SDK ----
print("Generating email (MiniMax via Anthropic SDK)...")
try:
    message = client.messages.create(
        model="MiniMax-M2.1",
        max_tokens=4000,
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

html_output = "".join(
    block.text for block in message.content if getattr(block, "type", None) == "text"
).strip()

if not html_output:
    raise RuntimeError("Model returned no text content.")

# ---- Save HTML file ----
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = f"fizz_email_{timestamp}.html"
with open(output_file, "w", encoding="utf-8") as f:
    f.write(html_output)

print("Done! Email saved as", output_file)