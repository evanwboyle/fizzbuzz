import json, csv, io, time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT_DIR / "web-crawling" / "crawl-results.json"
OUTPUT_PATH = ROOT_DIR / "article-composition" / "crawl-results-new.csv"

with open(INPUT_PATH) as f:
    data = json.load(f)

cutoff = time.time() - 86400

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

    rows.append({
        "postID": post_id,
        "identity": f"{name} ({community})" + (" [verified]" if verified else ""),
        "likes": p.get("likesMinusDislikes", 0),
        "shares": p.get("numShares", 0),
        "comments": p.get("commentCount", 0),
        "text": p.get("text", "").replace("\n", " "),
        "media": " ; ".join(media_urls),
        "replies": replies.replace("\n", " "),
    })

rows.sort(key=lambda r: r["likes"], reverse=True)

with open(OUTPUT_PATH, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["postID", "identity", "likes", "shares", "comments", "text", "media", "replies"])
    w.writeheader()
    w.writerows(rows)

print(f"Wrote {len(rows)} posts from last 24h to {OUTPUT_PATH}")
