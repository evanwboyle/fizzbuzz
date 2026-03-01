#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGS_DIR="$PROJECT_DIR/logs"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="$LOGS_DIR/daily-email_${TIMESTAMP}.log"

# Ensure logs directory exists
mkdir -p "$LOGS_DIR"

# ── Logging ──────────────────────────────────────────────────────────────────
# Everything the user sees in the console is also copied to the log file.
log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" | tee -a "$LOG_FILE"
}

# Run a command, streaming stdout+stderr to both console and log
run() {
  log ">>> $*"
  "$@" 2>&1 | tee -a "$LOG_FILE"
  local rc=${PIPESTATUS[0]}
  if [ $rc -ne 0 ]; then
    log "ERROR: command exited with code $rc"
    return $rc
  fi
}

# Prompt the user for yes/no (default no)
ask_yn() {
  local prompt="$1"
  local answer
  while true; do
    echo -n "$prompt [y/N]: " | tee -a "$LOG_FILE"
    read -r answer
    echo "$answer" >> "$LOG_FILE"
    case "$answer" in
      [Yy]|[Yy]es) return 0 ;;
      [Nn]|[Nn]o|"") return 1 ;;
      *) echo "Please enter y or n." | tee -a "$LOG_FILE" ;;
    esac
  done
}

# ── Load .env ────────────────────────────────────────────────────────────────
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

TEST_EMAIL="${TEST_EMAIL_RECIPIENT:-}"

# ── Parse arguments ──────────────────────────────────────────────────────────
MODE="interactive"
for arg in "$@"; do
  case "$arg" in
    --auto) MODE="auto" ;;
    --help|-h)
      echo "Usage: daily-email.sh [--auto]"
      echo ""
      echo "  (default)   Interactive mode — walk through each step with prompts"
      echo "  --auto      Automatic mode (WIP)"
      exit 0
      ;;
  esac
done

# ══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE MODE
# ══════════════════════════════════════════════════════════════════════════════
interactive_mode() {
  log "=== FizzBuzz Daily Email — Interactive Mode ==="
  log "Log file: $LOG_FILE"
  echo ""

  # ── Step 1: Crawl ────────────────────────────────────────────────────────
  if ask_yn "STEP 1/5: Scrape recent posts with crawl.mjs --recent-hops 2?"; then
    echo "────────────────────────────────────────────────────────"
    cd "$PROJECT_DIR/scraping"
    run node crawl.mjs --recent-hops 2
    log "Crawl complete."
  else
    log "Skipped crawl step."
  fi
  echo ""

  # ── Step 2: Sanitize ─────────────────────────────────────────────────────
  if ask_yn "STEP 2/5: Sanitize crawl data to CSV?"; then
    echo "────────────────────────────────────────────────────────"
    cd "$PROJECT_DIR/email"
    run python3 sanitize.py
    log "Sanitize complete."
    echo ""

    # Show head of CSV so the user can verify
    CSV_FILE="$PROJECT_DIR/data/crawl-results-new.csv"
    if [ -f "$CSV_FILE" ]; then
      log "Preview of sanitized CSV (first 10 lines):"
      echo "────────────────────────────────────────────────────────"
      head -n 10 "$CSV_FILE" | tee -a "$LOG_FILE"
      echo ""
      local line_count
      line_count=$(wc -l < "$CSV_FILE" | tr -d ' ')
      log "Total rows in CSV: $line_count"
    fi
  else
    log "Skipped sanitize step."
  fi
  echo ""

  # ── Step 3: Generate raw AI output ──────────────────────────────────────
  if ask_yn "STEP 3/5: Generate raw AI output?"; then
    echo "────────────────────────────────────────────────────────"
    cd "$PROJECT_DIR/email"
    run python3 generate-email.py --raw
    log "Raw AI generation complete."
  else
    log "Skipped raw generation."
  fi
  echo ""

  # Find the latest raw output
  LATEST_RAW=$(ls -t "$PROJECT_DIR/email/output"/fizz_raw_*.html 2>/dev/null | head -1)
  if [ -z "$LATEST_RAW" ]; then
    log "ERROR: No raw output found in email/output/"
    exit 1
  fi
  log "Raw output: $(basename "$LATEST_RAW")"

  # Show a quick summary of what the model produced
  echo "────────────────────────────────────────────────────────"
  local img_count
  img_count=$(grep -oc 'fb-image\|mj-image\|<img' "$LATEST_RAW" 2>/dev/null || echo "0")
  log "Images found in raw output: $img_count"
  echo ""

  # ── Step 4: Assemble email ────────────────────────────────────────────
  if ask_yn "STEP 4/5: Assemble raw output into email template?"; then
    echo "────────────────────────────────────────────────────────"
    cd "$PROJECT_DIR/email"
    run python3 assemble.py --file "$LATEST_RAW"
    log "Assembly complete."
  else
    log "Skipped assembly."
  fi
  echo ""

  # Find the latest assembled email
  LATEST_EMAIL=$(ls -t "$PROJECT_DIR/email/output"/fizz_email_*.html 2>/dev/null | head -1)
  if [ -z "$LATEST_EMAIL" ]; then
    log "ERROR: No assembled email found in email/output/"
    exit 1
  fi
  log "Assembled email: $(basename "$LATEST_EMAIL")"
  echo ""

  # ── Step 5: Review & Send ────────────────────────────────────────────────
  log "STEP 5/5: Review & Send"
  echo "────────────────────────────────────────────────────────"

  # Ask to view in browser
  if ask_yn "Open the email in your browser to preview?"; then
    log "Opening email in browser..."
    open "$LATEST_EMAIL" 2>/dev/null || xdg-open "$LATEST_EMAIL" 2>/dev/null || {
      log "Could not open browser. File is at: $LATEST_EMAIL"
    }
    echo ""
    echo "Take a look — we'll continue when you're ready."
    echo -n "Press Enter to continue..." | tee -a "$LOG_FILE"
    read -r
    echo "" >> "$LOG_FILE"
  fi
  echo ""

  # Ask to send test email
  if [ -n "$TEST_EMAIL" ]; then
    if ask_yn "Send a test email to $TEST_EMAIL?"; then
      log "Sending test email to $TEST_EMAIL..."
      cd "$PROJECT_DIR/email"
      run python3 send.py --to "$TEST_EMAIL" --file "$LATEST_EMAIL"
      log "Test email sent."
      echo ""
      echo "Check your inbox. We'll continue when you're ready."
      echo -n "Press Enter to continue..." | tee -a "$LOG_FILE"
      read -r
      echo "" >> "$LOG_FILE"
    fi
  else
    log "WARNING: TEST_EMAIL_RECIPIENT not set in .env — skipping test send."
  fi
  echo ""

  # Ask to send to mailing list
  MAILING_LIST="$PROJECT_DIR/.mailing_list"
  if [ -f "$MAILING_LIST" ]; then
    local recipient_count
    recipient_count=$(grep -cv '^\s*#\|^\s*$' "$MAILING_LIST" 2>/dev/null || echo "0")
    log "Mailing list has $recipient_count recipient(s)."

    if ask_yn "Send the email to the full mailing list ($recipient_count recipients)?"; then
      log "Sending to mailing list..."
      cd "$PROJECT_DIR/email"
      run python3 send.py --file "$LATEST_EMAIL"
      log "Mailing list send complete."
    else
      log "Skipped mailing list send."
    fi
  else
    log "WARNING: .mailing_list not found — skipping mailing list send."
  fi

  echo ""
  log "=== FizzBuzz Daily Email — Done ==="
  log "Log saved to: $LOG_FILE"
}

# ══════════════════════════════════════════════════════════════════════════════
# AUTO MODE (WIP)
# ══════════════════════════════════════════════════════════════════════════════
auto_mode() {
  log "=== FizzBuzz Daily Email — Auto Mode (WIP) ==="
  log "Auto mode is not yet implemented."
  log "Use interactive mode (no flags) for now."
  log "=== Done ==="
}

# ── Run ──────────────────────────────────────────────────────────────────────
case "$MODE" in
  interactive) interactive_mode ;;
  auto)        auto_mode ;;
esac
