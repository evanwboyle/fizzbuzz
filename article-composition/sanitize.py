import json, csv, io, time, argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--most-liked", type=int, default=None, help="Keep only the N most-liked posts")
parser.add_argument("--days", type=int, default=7, help="Only include posts from the last N days (default: 7)")
args = parser.parse_args()

ROOT_DIR = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT_DIR / "web-crawling" / "crawl-results.json"
OUTPUT_PATH = ROOT_DIR / "article-composition" / "crawl-results-new.csv"

with open(INPUT_PATH) as f:
    data = json.load(f)

cutoff = time.time() - 86400 * args.days

rows = []
for p in data["posts"]:
    if p["date"] < cutoff:
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

    # Find reply text from edges
    post_id = p["postID"]
    reply_ids = [e["to"] for e in data["edges"] if e["from"] == post_id]
    reply_lookup = {rp["postID"]: rp["text"] for rp in data["posts"] if rp["postID"] in reply_ids}
    replies = " | ".join(reply_lookup.values()) if reply_lookup else ""

    # Only include identity when someone de-anonymized (named + verified)
    identity_str = ""
    if name and name != "Anonymous":
        identity_str = f"{name} ({community})" + (" [verified]" if verified else "")

    rows.append({
        "identity": identity_str,
        "likes": p.get("likesMinusDislikes", 0),
        "comments": p.get("commentCount", 0),
        "text": p.get("text", "").replace("\n", " "),
        "media": " ; ".join(media_urls),
        "replies": replies.replace("\n", " "),
    })

rows.sort(key=lambda r: r["likes"], reverse=True)

if args.most_liked is not None:
    rows = rows[:args.most_liked]

with open(OUTPUT_PATH, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["identity", "likes", "comments", "text", "media", "replies"])
    w.writeheader()
    w.writerows(rows)

print(f"Wrote {len(rows)} posts from last {args.days} days to {OUTPUT_PATH}")
