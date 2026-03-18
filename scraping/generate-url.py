#!/usr/bin/env python3
"""Generate a Fizz share URL for a given post ID.

Usage:
    python generate-url.py <postID>
    python generate-url.py <postID1> <postID2> ...
"""

import json
import os
import sys
from pathlib import Path
from urllib import request

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key and key not in os.environ:
            os.environ[key] = val


def refresh_bearer_token():
    api_key = os.environ["FIREBASE_API_KEY"]
    refresh_token = os.environ["REFRESH_TOKEN"]
    url = f"https://securetoken.googleapis.com/v1/token?key={api_key}"
    body = json.dumps({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with request.urlopen(req) as resp:
        data = json.loads(resp.read())
    if "id_token" not in data:
        print("Token refresh failed:", data, file=sys.stderr)
        sys.exit(1)
    return data["id_token"]


def create_share_url(bearer_token, post_id, community="Yale"):
    api_base = os.environ["FIZZ_API_BASE"]
    url = f"{api_base}/api/v1/link/create-dynamic-link"
    body = json.dumps({
        "data": {
            "postID": post_id,
            "communityID": community,
            "clientVersion": "1.25.0",
            "linkType": "post",
            "metadata": {"postID": post_id},
        }
    }).encode()
    req = request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bearer_token}",
    })
    with request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data["result"]["shortLinkURL"]


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <postID> [postID ...]", file=sys.stderr)
        sys.exit(1)

    load_env(ENV_PATH)
    community = os.environ.get("COMMUNITY", "Yale")
    token = refresh_bearer_token()

    for post_id in sys.argv[1:]:
        try:
            url = create_share_url(token, post_id, community)
            print(f"{post_id}\t{url}")
        except Exception as e:
            print(f"{post_id}\tERROR: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
