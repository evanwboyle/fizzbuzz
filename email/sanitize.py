import json, csv, re, time
from datetime import datetime
from pathlib import Path

# Relative time words that become unreliable once a post ages
_RELATIVE_TIME_RE = re.compile(
    r'\b(tonight|tonite|tomorrow|tmrw|tmr|this morning|this afternoon|this evening'
    r'|this weekend|this friday|this saturday|this sunday|this monday|this tuesday'
    r'|this wednesday|this thursday|later today|tn|rn|right now)\b',
    re.IGNORECASE,
)

# ── Config ──────────────────────────────────────────────────────────────────
DAYS = 1.5                    # Only include posts from the last N days
MOST_LIKED = 50            # Keep only the N most-liked posts (None = no limit)
LEAST_LIKED = 5          # Keep only the N least-liked posts (None = no limit)
MOST_LIKED_REFIZZES = 30    # Keep only the N most-liked reFizzes overall (None = no limit)
LEAST_LIKED_REFIZZES = 5    # Also include the N least-liked reFizzes overall (None = skip)
INCLUDE_VERIFIED = True     # Always include posts from verified orgs
# ────────────────────────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT_DIR / "data" / "crawl-results.json"
OUTPUT_PATH = ROOT_DIR / "data" / "crawl-results-new.csv"

with open(INPUT_PATH) as f:
    data = json.load(f)

cutoff = time.time() - 86400 * DAYS

# First pass: collect all posts and build parent-child relationships
# A reFizz post is a child (response) to the original post it quotes.
# We group children under their original parent to avoid duplicate content.
all_posts = {}  # postID -> post dict
children = {}   # parent postID -> list of {likes, text}

for p in data["posts"]:
    if p["date"] < cutoff:
        continue
    all_posts[p["postID"]] = p

# Identify reFizz relationships where the original is also in the dataset
child_ids = set()  # posts that will be folded into their parent's row
for p in all_posts.values():
    rf = p.get("reFizz")
    if rf and p.get("reFizzContentType") == "post":
        parent_id = rf.get("postID", "")
        if parent_id in all_posts:
            child_ids.add(p["postID"])
            children.setdefault(parent_id, []).append({
                "likes": p.get("likesMinusDislikes", 0),
                "text": p.get("text", "").replace("\n", " "),
            })

# Filter reFizzes globally by likes, then distribute back to parents
all_refizzes = []  # (parent_id, {likes, text})
for parent_id, kids in children.items():
    for kid in kids:
        all_refizzes.append((parent_id, kid))

all_refizzes.sort(key=lambda x: x[1]["likes"], reverse=True)

selected_refizzes = set()
if MOST_LIKED_REFIZZES is not None:
    for r in all_refizzes[:MOST_LIKED_REFIZZES]:
        selected_refizzes.add(id(r))
if LEAST_LIKED_REFIZZES is not None:
    for r in all_refizzes[-LEAST_LIKED_REFIZZES:]:
        selected_refizzes.add(id(r))
if MOST_LIKED_REFIZZES is None and LEAST_LIKED_REFIZZES is None:
    selected_refizzes = set(id(r) for r in all_refizzes)

# Rebuild children with only selected reFizzes
filtered_children = {}
for r in all_refizzes:
    if id(r) in selected_refizzes:
        parent_id, kid = r
        filtered_children.setdefault(parent_id, []).append(kid)

# Sort each parent's kept children by likes descending
for kids in filtered_children.values():
    kids.sort(key=lambda c: c["likes"], reverse=True)

total_refizzes_kept = sum(len(v) for v in filtered_children.values())

# Second pass: build rows, skipping children (they're nested under parents)
rows = []
for p in all_posts.values():
    if p["postID"] in child_ids:
        continue

    identity = p.get("identity", {})
    name = identity.get("name", "")
    community = identity.get("communityID", "")
    verified = identity.get("verified", False)

    media_urls = []
    for m in p.get("media", []):
        url = m.get("signedUrl", "")
        if url:
            media_urls.append(url)
        thumb = m.get("thumbnail", {}).get("signedUrl", "")
        if thumb and thumb != url:
            media_urls.append(thumb)

    # Build refizzes string: responses to this post from children
    kids = filtered_children.get(p["postID"], [])
    refizzes_str = "|".join(f"{c['likes']}|{c['text']}" for c in kids) if kids else ""

    # If this post is a reFizz of something NOT in our dataset, show the original
    if not kids:
        rf = p.get("reFizz")
        if rf and p.get("reFizzContentType") in ("post", "comment"):
            rf_text = rf.get("text", "").replace("\n", " ")
            rf_likes = rf.get("likesMinusDislikes", 0)
            refizzes_str = f"(original) {rf_likes}|{rf_text}"

    # Only include identity when someone de-anonymized (named + verified)
    identity_str = ""
    is_verified_org = False
    if name and name != "Anonymous":
        identity_str = f"{name} ({community})" + (" [verified]" if verified else "")
        is_verified_org = verified

    # Annotate relative time references so the model knows they're stale
    text = p.get("text", "").replace("\n", " ")
    post_ts = p.get("date", 0)
    if post_ts:
        posted_str = datetime.fromtimestamp(post_ts).strftime("%b %-d at %-I:%M%p")
        text = _RELATIVE_TIME_RE.sub(rf'[RELATIVE TIME: \1 (relative to {posted_str})]', text)
    else:
        text = _RELATIVE_TIME_RE.sub(r'[RELATIVE TIME: \1 (unknown post time)]', text)

    rows.append({
        "identity": identity_str,
        "likes": p.get("likesMinusDislikes", 0),
        "comments": p.get("commentCount", 0),
        "text": text,
        "media": " ; ".join(media_urls),
        "refizzes": refizzes_str,
        "_verified": is_verified_org,
    })

rows.sort(key=lambda r: r["likes"], reverse=True)

# Apply most-liked / least-liked filters (can combine)
selected = set()
if MOST_LIKED is not None:
    for r in rows[:MOST_LIKED]:
        selected.add(id(r))
if LEAST_LIKED is not None:
    for r in rows[-LEAST_LIKED:]:
        selected.add(id(r))
if INCLUDE_VERIFIED:
    for r in rows:
        if r["_verified"]:
            selected.add(id(r))

if selected:
    rows = [r for r in rows if id(r) in selected]

# Remove internal tracking field
for r in rows:
    del r["_verified"]

fieldnames = ["identity", "likes", "comments", "text", "media", "refizzes"]

with open(OUTPUT_PATH, "w", newline="") as f:
    f.write("# refizzes format: likes|text|likes|text (responses to this post, sorted by likes)\n")
    f.write("# (original) prefix means it shows the post being quote-reposted\n")
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows)

file_size = OUTPUT_PATH.stat().st_size
print(f"Wrote {len(rows)} posts ({total_refizzes_kept} reFizzes kept out of {len(all_refizzes)}) from last {DAYS} days to {OUTPUT_PATH}")
print(f"  File size: {file_size:,} chars")
