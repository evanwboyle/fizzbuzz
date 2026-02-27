# FizzBuzz

Automated, agentic Fizz Social Media Newsletter — a daily digest of Yale's anonymous Fizz app, transformed into a witty, AI-generated HTML newsletter and delivered straight to your inbox.

## What is FizzBuzz?

FizzBuzz scrapes posts from Yale's Fizz community, clusters them into thematic sections, and uses an LLM to synthesize them into an engaging, self-contained HTML newsletter. Think: exhausted campus journalist meets Gen Z gossip column, minus the emojis.

The pipeline handles everything end-to-end: real-time monitoring, historical crawling, data sanitization, and AI-powered editorial composition.

## Architecture

```
┌──────────────────────────────────────┐
│         FIZZ APP (Yale)              │
└──────────┬───────────────────────────┘
           │
     ┌─────┴──────┐
     │             │
     ▼             ▼
 Live Feed     Web Crawler
 (Pusher)      (Graph BFS)
     │             │
     ▼             ▼
 posts.json    crawl-results.json
     │             │
     └──────┬──────┘
            ▼
      sanitize.py
   (filter + flatten)
            │
            ▼
    crawl-results-new.csv
            │
            ▼
    generate-email.py
    (LLM + prompt.md)
            │
            ▼
    fizz_email_*.html
    (self-contained newsletter)
```

## Project Structure

```
fizzbuzz/
├── daily-email.sh              # Pipeline orchestrator (entry point)
├── live-scraping/              # Real-time Pusher listener
│   ├── index.js                # Listener daemon
│   ├── package.json            # Node.js dependencies
│   └── posts.json              # Output: accumulated posts
├── web-crawling/               # Historical post crawler
│   ├── crawl.mjs               # Graph traversal engine
│   └── crawl-results.json      # Output: posts + edges
├── article-composition/        # Newsletter generation
│   ├── sanitize.py             # Crawl results → CSV
│   ├── generate-email.py       # CSV → HTML newsletter (via LLM)
│   ├── prompt.md               # Newsletter style guide / prompt template
│   └── fizz_email_*.html       # Output: generated newsletters
├── openclaw-fizzbot/           # OpenClaw agent config (WhatsApp notifications)
│   └── openclaw-fizzbot.json5  # Agent definition
└── .env                        # Environment variables (not committed)
```

## Components

### Live Scraping (`live-scraping/index.js`)

A persistent daemon that connects to Fizz's Pusher channel and captures posts in real time.

- Listens on `private-community-Yale` for new posts
- Persists unique posts to `posts.json` with timestamps
- Auto-refreshes Firebase JWT every 55 minutes
- Optionally forwards posts to an OpenClaw agent for WhatsApp notifications

### Web Crawler (`web-crawling/crawl.mjs`)

A graph-traversal crawler that discovers posts through Fizz's "similar posts" API.

- Seeds from the discover feed, expands via BFS
- Tracks post-to-post edges (similarity graph)
- Supports full crawls, recent-only, and hybrid modes
- Saves incrementally to resume interrupted crawls

**CLI flags:**
| Flag | Description |
|------|-------------|
| *(none)* | Resume existing crawl or start fresh |
| `--restart` | Discard existing data, crawl from scratch |
| `--recent` | Only expand posts from the last 7 days |
| `--recent-hops N` | Seed from recent posts, follow N hops into older posts |

### Data Sanitizer (`article-composition/sanitize.py`)

Transforms raw crawl output into a clean CSV for newsletter generation.

- Filters to posts from the last 24 hours
- Extracts identity, engagement metrics, media URLs, and reply text
- Sorts by likes (descending)
- Outputs: `crawl-results-new.csv`

### Newsletter Generator (`article-composition/generate-email.py`)

Calls an LLM (MiniMax-M2.1 via Anthropic SDK) to produce a self-contained HTML newsletter.

- Loads the prompt template from `prompt.md`
- Injects the sanitized CSV data
- Streams the response to a timestamped HTML file
- Output is fully self-contained — no external stylesheets or scripts

### Prompt Template (`article-composition/prompt.md`)

The editorial brain of FizzBuzz. Defines:

- **Voice:** Witty, dry, slightly condescending campus journalism
- **Structure:** Masthead, ticker bar, 5-8 thematic sections, Post of the Day, footer
- **Design system:** Custom color palette (lime, hot-pink, electric-blue, orange, yellow), Google Fonts (Unbounded, Archivo Black, Open Sans, Chivo Mono), 660px max-width
- **Components:** Camp blocks, stat pills, pull quotes, image blocks, weather boxes
- **Rules:** No more than 2-3 images, rotate section label colors, synthesize narratives (don't just summarize)

### OpenClaw Agent (`openclaw-fizzbot/`)

An optional OpenClaw agent that reviews incoming Fizz posts and sends WhatsApp summaries for noteworthy content. Triggered by the live scraper's webhook.

## Prerequisites

- **Node.js** v16+
- **Python** 3.8+ with `pip`
- **Fizz account credentials** (Firebase refresh token)
- **MiniMax API key** (or compatible Anthropic-protocol endpoint)
- **OpenClaw** (optional, for WhatsApp notifications)

## Setup

1. **Clone the repository:**

   ```bash
   git clone <repo-url>
   cd fizzbuzz
   ```

2. **Install Node.js dependencies:**

   ```bash
   cd live-scraping && npm install && cd ..
   ```

3. **Set up the Python environment:**

   ```bash
   cd article-composition
   python3 -m venv .venv
   source .venv/bin/activate
   pip install anthropic pandas
   cd ..
   ```

4. **Configure environment variables:**

   Create a `.env` file in the project root:

   ```bash
   # Fizz API Authentication
   REFRESH_TOKEN=<your-fizz-refresh-token>
   FIREBASE_API_KEY=<your-firebase-api-key>
   FIZZ_API_BASE=https://api510.pineapple-connect.com
   CDN_BASE=https://cdn510.pineapple-connect.com

   # Pusher (Real-time Feed)
   PUSHER_APP_KEY=<your-pusher-key>
   PUSHER_CLUSTER=us3
   COMMUNITY=Yale

   # Output Paths
   OUTPUT_FILE=./posts.json
   CRAWL_OUTPUT_FILE=./crawl-results.json

   # Crawl Settings
   CRAWL_MAX_POSTS=50000
   CRAWL_MAX_DEPTH=16
   CRAWL_CONCURRENCY=5
   CRAWL_TOKEN_REFRESH_MS=3300000

   # LLM API (MiniMax via Anthropic SDK)
   ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic
   ANTHROPIC_API_KEY=<your-minimax-api-key>

   # OpenClaw (optional)
   OPENCLAW_URL=http://127.0.0.1:18789/hooks/agent
   OPENCLAW_TOKEN=<your-openclaw-token>
   NOTIFY_NUMBER=<your-phone-number>
   ```

5. **Make the pipeline script executable:**

   ```bash
   chmod +x daily-email.sh
   ```

## Usage

### Generate a Daily Newsletter

Run the full pipeline:

```bash
./daily-email.sh
```

This will:
1. Crawl recent Fizz posts (last 7 days)
2. Sanitize and filter to the last 24 hours
3. Generate an HTML newsletter via LLM

Output lands in `article-composition/fizz_email_YYYYMMDD_HHMMSS.html`. Open it in any browser.

Logs are written to `daily-email.log`.

### Run Individual Pipeline Steps

**Crawl posts:**

```bash
cd web-crawling
node crawl.mjs --recent          # Last 7 days only
node crawl.mjs                   # Full graph crawl (resume if partial)
node crawl.mjs --restart         # Full crawl from scratch
node crawl.mjs --recent-hops 3   # Recent + 3 hops into older posts
```

**Sanitize crawl results to CSV:**

```bash
cd article-composition
source .venv/bin/activate
python3 sanitize.py
```

**Generate the newsletter:**

```bash
cd article-composition
source .venv/bin/activate
python3 generate-email.py
```

### Start the Live Listener

Run the real-time post monitor as a background daemon:

```bash
cd live-scraping
node index.js
```

Posts are saved to `posts.json` as they arrive. Press `Ctrl+C` to stop.

### Schedule Daily Runs

Use cron to automate the newsletter:

```bash
crontab -e
```

Add a line like:

```
0 8 * * * /path/to/fizzbuzz/daily-email.sh >> /path/to/fizzbuzz/daily-email.log 2>&1
```

This runs the pipeline every day at 8 AM.

## Output Format

Generated newsletters are self-contained HTML files with:
- Embedded CSS (no external stylesheets)
- Google Fonts loaded via `<link>` tags
- Responsive layout (660px max-width)
- Custom color scheme and typography
- 5-8 thematic sections with editorial commentary
- Post of the Day highlight
- Stat pills, pull quotes, camp blocks, and other visual components

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `401 Unauthorized` during crawl | Your `REFRESH_TOKEN` has expired. Get a new one from the Fizz app. |
| Empty CSV after sanitization | No posts from the last 24 hours. Try running the crawler with `--recent` first. |
| LLM generation fails | Check your `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL`. Verify the MiniMax endpoint is reachable. |
| Pusher connection drops | The listener auto-reconnects. If persistent, check `PUSHER_APP_KEY` and network. |
| Token refresh errors | Firebase tokens expire. Ensure `FIREBASE_API_KEY` and `REFRESH_TOKEN` are valid. |
| Large crawl-results.json | Normal — full crawls can produce 30MB+ files. Use `--recent` for lighter runs. |
