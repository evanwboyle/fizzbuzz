# Fizz Top Feed Research

## Goal
Access the "Top" feed from the Fizz app programmatically for the FizzBuzz newsletter pipeline.

## TL;DR
**The feed is served by `/api/v1/users/feed`**, a REST endpoint on `<FIZZ_API_HOST>` that supports cursor-based pagination. It accepts a `feedType` parameter (e.g. `home_top`, `home_new`, `home_fizzin`) and returns 20 posts per page, paginated via `lastPostID`. The previous hypothesis that the feed was served by Firebase RTDB was **wrong** — RTDB is not used at all (zero `firebaseio.com` traffic observed).

### How we found it
1. MITM interception of `api510` was blocked by **certificate pinning** on both iOS and macOS (TCP and QUIC/HTTP3)
2. We discovered the app uses **QUIC (UDP port 443)** for api510 connections via `lsof`, which is why earlier MITM attempts saw "zero HTTP calls on scroll" — the traffic was UDP, invisible to mitmproxy
3. The breakthrough came from reading the **macOS app's local HTTP cache** (`NSURLCache` SQLite database) at `~/Library/Containers/<APP_CONTAINER_UUID>/Data/Library/Caches/com.ashtoncofer.Buzz/Cache.db`
4. The `cfurl_cache_response` table revealed cached URLs including `/api/v1/users/feed` — an endpoint not found in the Ghidra binary analysis
5. The error response from `/users/feed` with wrong params helpfully listed all required fields and valid `feedType` enum values

### What we tried before finding the answer
- **MITM on iOS** (mitmweb with `--allow-hosts`): Successfully intercepted `firebaseappcheck.googleapis.com` (captured App Check token), but `api510` and `<FIZZ_CDN_HOST>` rejected the proxy cert (cert pinning)
- **MITM on macOS** (system proxy + mitmweb): Same cert pinning on the Mac Catalyst app
- **Blocking QUIC** (`sudo pfctl` to drop UDP 443, forcing TCP fallback): App fell back to TCP but cert pinning still blocked interception
- **Frida injection**: Blocked by the app's anti-instrumentation protections
- **lldb debugging**: Also blocked
- **App Check token + RTDB REST API**: Captured a valid App Check token via MITM, but RTDB REST API still returned "Permission denied" with both `?auth=` and `Authorization: Bearer` + `X-Firebase-AppCheck` header — the RTDB REST API does not honor App Check tokens the way the SDK does
- **Firebase RTDB traffic analysis**: Filtered mitmweb for `firebaseio.com` — **zero connections observed**, disproving the RTDB hypothesis entirely
- **QUIC discovery via `lsof`**: Revealed that api510 connections were UDP (QUIC/HTTP3), explaining why mitmproxy never saw them

---

## The Feed Endpoint: `/api/v1/users/feed`

### Request
```
POST https://<FIZZ_API_HOST>/api/v1/users/feed
Authorization: Bearer {idToken}
Content-Type: application/json

{
  "data": {
    "communityID": "Yale",
    "clientVersion": "1.25.0",
    "feedType": "home_top",
    "firstRequest": true
  }
}
```

For subsequent pages:
```json
{
  "data": {
    "communityID": "Yale",
    "clientVersion": "1.25.0",
    "feedType": "home_top",
    "firstRequest": false,
    "lastPostID": "{postID from last item of previous page}"
  }
}
```

### Response
```json
{
  "result": {
    "items": [
      {
        "item": { /* full post object */ },
        "type": "post"
      }
    ]
  }
}
```

### Pagination
- **20 posts per page**, cursor-based via `lastPostID`
- `home_top` is sorted by `likesMinusDislikes` descending
- Pages have **zero overlap** — confirmed by comparing post IDs across pages
- Page 1 (likes 3006→2572), Page 2 (likes 2568→2529), etc.

### Available Feed Types
```
home_top, home_new, home_fizzin, home_top_week, home_top_all, home_top_day,
global_fizzin, global_new,
nearby_fizzin, nearby_new,
trending_post_candidates,
friends_and_mutuals,
interest_relationships, interest_greek_life, interest_sex,
interest_motivation_advice, interest_mental_health, interest_lgbt,
interest_fashion, interest_politics, interest_social_justice,
interest_beauty_skincare, interest_music, interest_sports,
interest_religion_spirituality, interest_career, interest_pop_culture,
interest_comics_anime, interest_food_cooking, interest_tea
```

### Also discovered: `/api/v1/feeds/posts/id`
Fetches a single post by ID. Found in the cache alongside `/users/feed`. Used by the app to hydrate individual posts (e.g. from push notifications or deep links).

---

## Infrastructure

| Key | Value |
|---|---|
| Firebase Project | `<FIREBASE_PROJECT_ID>` |
| API Base | `<FIZZ_API_BASE>/api/v1` |
| Test API | `<FIZZ_API_BASE_TEST>` (returns 401) |
| CDN | `<CDN_BASE>` |
| Backend | Express on Google Frontend (Cloud Functions/Cloud Run) |
| RTDB | `https://<FIREBASE_PROJECT_ID>.firebaseio.com` (exists, but **not used for feed**) |
| Firestore | **Does not exist** (`(default)` database returns 404) |
| Pusher App Key | `<PUSHER_APP_KEY>` |
| Pusher Cluster | `<PUSHER_CLUSTER>` |
| Pusher Channels | `private-community-{id}` (posts), `cache-community-{id}` (caching layer) |
| Auth | Firebase JWT (`phone` sign-in provider), uid=`<FIREBASE_UID>` |
| App Check | App Attest provider, header: `X-Firebase-AppCheck` |
| SSL Pinning | **ON** (despite `config.flags.sslPinning: false` — app pins certs for api510 and cdn) |
| Transport | **QUIC/HTTP3** (UDP 443) with TCP fallback (also cert-pinned) |
| Mac App Container | `~/Library/Containers/<APP_CONTAINER_UUID>/` |
| Min App Version | `1.17.0` |

---

## Feed Architecture (confirmed)
```
App launch:
  1. App calls /users/feed with feedType=home_top, firstRequest=true (20 posts)
  2. On scroll, app calls /users/feed with firstRequest=false, lastPostID=cursor
  3. ~100 rapid API calls on launch to populate multiple feed tabs
  4. All traffic over QUIC/HTTP3 (UDP 443), with TCP+TLS fallback
  5. discover-tab-data is a separate Discover tab preview (84 posts, not paginated)

Real-time updates:
  6. App subscribes to Pusher private-community-{id} for new posts
  7. FeedDataManager merges API data + Pusher events client-side
```

---

## `/app/session-state` Response

Returns community config, user profile, and feature flags. Key feed-related fields:
```
community.topFeedTabEnabled: true
community.discoverTabEnabled: true
config.features.feed.maxVideoDuration: 60
config.features.feed.toastBackgroundFetchIntervalSeconds: 30
config.features.feed.fullRefreshIntervalSeconds: 21600  (6 hours)
config.features.topicFeeds.enabled: true
config.flags.sslPinning: false
config.flags.clusterEmbeddingsTest: true
user.globalFeedEnabled: false
feedGroups: []
trendingTopics: []
```
No feed data in session-state. Full response saved to `data/session-state-response.json`.

---

## Post Schema (from `/users/feed` — includes `numShares`)

```
commentCount, communityID, date, defaultPseudonym, directMessagingEnabled,
flair, identity, isDisliked, isLiked, isOwnPost, isReadOnly, isSaved,
likesMinusDislikes, media, numShares, postID, postType, primaryIdentity,
refizzCount, text, visibility
```

Posts with `postType: "refizzPost"` also include a nested `reFizz` object with the original post.

---

## All Fizz API Endpoints (from binary memory dump + cache discovery)

### Feed/Post Endpoints
| Endpoint | Status | Notes |
|---|---|---|
| **`/users/feed`** | **200** | **The main feed endpoint. Paginated, supports all feed types.** |
| `/feeds/posts/discover-tab-data` | 200 | Fixed 84 posts. Ignores ALL params. |
| `/feeds/posts/id` | 200 | Fetch single post by ID |
| `/feeds/posts/eligible-for-bank` | 403 | Forbidden |
| `/feeds/posts/top-week/flair` | 404 | Dead |
| `/feeds/posts/date/flair` | 404 | Dead |
| `/feeds/posts/top-all-time/display-name` | 404 | Dead |
| `/feeds/posts/date/display-name` | 404 | Dead |
| `/feeds/posts/date/identity` | 400 | Per-user, requires identity param |
| `/feeds/posts/top-all-time/identity` | 400 | Per-user, requires identity param |
| `/users/posts/top` | 200 | YOUR top posts only |
| `/users/posts/bookmarks` | Untested | |
| `/posts/get-similar-posts` | 200 | Used by crawl.mjs for graph expansion |

### Binary-confirmed: these are ALL feed endpoints
Full memory dump at `0x10188f0f0` (2048 bytes) shows the complete endpoint list. `/users/feed` was not in the binary string table — it was discovered via the macOS app's HTTP cache.

---

## Pusher Channels

| Channel | Auth | Result |
|---|---|---|
| `private-community-{id}` | Required (auth-pusher) | ✅ Receives new post events in real-time |
| `cache-community-{id}` | Not required | ✅ Subscribes, returns `cache_miss` |
| `presence-community-{id}` | N/A | ❌ "Invalid channel name" |
| `private-cache-community-{id}` | N/A | ❌ "Invalid channel name" |
| `private-encrypted-community-{id}` | N/A | ❌ "Invalid channel name" |

`live-scrape.js` now logs ALL event types (including `pusher:` internals) to `data/pusher-events.jsonl`.

---

## RTDB Access Attempts (now known to be irrelevant)

RTDB is not used for the feed. The app makes zero connections to `firebaseio.com`. The RTDB may be used for other features or may be a legacy artifact.

| Method | Result |
|---|---|
| `?auth={idToken}` | 401 "Permission denied" |
| `Authorization: Bearer {idToken}` | 401 "Unauthorized request" |
| App Check token + ID token | 401 "Permission denied" |
| User-specific paths (`users/{uid}/feed`, etc.) | 401 "Permission denied" |
| Alternative RTDB URLs (`-feeds`, `-posts`, `-prod`) | 404 |
| Root shallow read | 401 "Permission denied" |

---

## Exhaustive Parameter Tests on discover-tab-data

All return the same 84 posts with 100% overlap:
```
feedType: top, relevance, newest
sortBy: top, newest
endpointFeedType: home_top, home_fizzin, home_new
selectedTimeRange: pastDay, pastWeek, allTime
refreshSource: cold_start, pagination, prefetch, manual
hotScoreOrderingField: hotScore, hotScoreRecent, hotScoreLocalized
updatePagination: true/false
simulateFeedSettings: true/false
lastPostID: {real post ID}
lastFeedPostID: {real post ID}
feedSessionCount: 1, 5, 50
feedSessionCountGlobal: 1, 10
page: 2
offset: 84
limit: 200
clusterEmbeddingsTest: true
symkShowOnlyNudges: false
symkMinGapBetweenPosts: 0
taxonomyInterestTags: []
```

---

## Ruled Out

- RTDB as feed source (zero firebaseio.com traffic observed)
- REST API pagination on discover-tab-data (all params ignored, always 84 posts)
- MITM interception of api510 (cert pinning on TCP and QUIC)
- Frida/lldb for SSL bypass (anti-instrumentation protections)
- App Check token for RTDB REST access (still denied)
- Alternative API versions (v2, v3)
- Different API hosts
- Firebase callable functions by name
- Cloud Run direct access
- Session-state as feed enabler
- GET/PUT/PATCH/DELETE methods
- SSE/WebSocket upgrades
- Different Content-Types
- Cross-community differences
- Pusher as historical feed delivery (push-only for new posts)
- Pusher cache channels (cache_miss, no data)
- Firestore (database does not exist for this project)
- Firebase Debug Provider (requires Console access to register token)

## Tools Used
- **Ghidra** with GhidraMCP for binary analysis
- **mitmproxy** for live traffic interception (iOS and macOS)
- **Firebase JS SDK** for Firestore/RTDB queries
- **macOS `lsof`** for identifying QUIC/UDP connections
- **macOS `sqlite3`** for reading the app's NSURLCache database
- **`pfctl`** for blocking QUIC to force TCP fallback
- **Node.js** test scripts with Firebase auth
- Test scripts: `test-feeds.mjs`, `test-pagination.mjs`, `test-top-feed.mjs`, `probe-shared-post.mjs`, `test-session-feed.mjs`, `test-session-detail.mjs`, `test-firebase-direct.mjs`, `test-cloud-funcs.mjs`, `test-appcheck.mjs`, `test-appcheck2.mjs`, `test-session-count.mjs`, `test-firestore.mjs`, `test-rtdb.mjs`, `test-rtdb2.mjs`, `test-cache-channel.mjs`, `test-rtdb-appcheck.mjs`
