#!/usr/bin/env bash
set -euo pipefail


PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$PROJECT_DIR/daily-email.log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== Starting daily email pipeline ==="

# Step 1: Crawl recent posts
log "Running crawl (--recent)..."
cd "$PROJECT_DIR/web-crawling"
node crawl.mjs --recent 2>&1 | tee -a "$LOG_FILE"
log "Crawl complete."

# Step 2: Sanitize crawl results to CSV
log "Running sanitize..."
cd "$PROJECT_DIR/article-composition"
python3 sanitize.py 2>&1 | tee -a "$LOG_FILE"
log "Sanitize complete."

# Step 3: Generate email
log "Generating email..."
python3 generate-email.py 2>&1 | tee -a "$LOG_FILE"
log "Email generation complete."

log "=== Daily email pipeline finished ==="
