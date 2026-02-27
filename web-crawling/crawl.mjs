import fetch from "node-fetch";
import fs from "fs";
import { fileURLToPath } from "url";

const ENV_PATH = fileURLToPath(new URL("../.env", import.meta.url));

function loadEnvFile(path) {
  if (!fs.existsSync(path)) return;
  const lines = fs.readFileSync(path, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const separator = trimmed.indexOf("=");
    if (separator === -1) continue;
    const key = trimmed.slice(0, separator).trim();
    const value = trimmed.slice(separator + 1).trim();
    if (key && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

loadEnvFile(ENV_PATH);

const CONFIG = {
  REFRESH_TOKEN: process.env.REFRESH_TOKEN,
  FIREBASE_API_KEY: process.env.FIREBASE_API_KEY,
  FIZZ_API_BASE: process.env.FIZZ_API_BASE,
  COMMUNITY: process.env.COMMUNITY,
  OUTPUT_FILE: process.env.CRAWL_OUTPUT_FILE,
  MAX_POSTS: Number(process.env.CRAWL_MAX_POSTS),
  MAX_DEPTH: Number(process.env.CRAWL_MAX_DEPTH),
  CONCURRENCY: Number(process.env.CRAWL_CONCURRENCY),
  TOKEN_REFRESH_MS: Number(process.env.CRAWL_TOKEN_REFRESH_MS),
};

const REQUIRED_CONFIG_KEYS = [
  "REFRESH_TOKEN",
  "FIREBASE_API_KEY",
  "FIZZ_API_BASE",
  "COMMUNITY",
  "OUTPUT_FILE",
  "MAX_POSTS",
  "MAX_DEPTH",
  "CONCURRENCY",
  "TOKEN_REFRESH_MS",
];

const missingConfig = REQUIRED_CONFIG_KEYS.filter((key) => {
  const value = CONFIG[key];
  if (typeof value === "number") return Number.isNaN(value);
  return !value;
});

if (missingConfig.length > 0) {
  console.error(`❌ Missing required env vars for crawl: ${missingConfig.join(", ")}`);
  process.exit(1);
}

let bearerToken = null;
let lastRefresh = 0;

async function refreshBearerToken() {
  const res = await fetch(
    `https://securetoken.googleapis.com/v1/token?key=${CONFIG.FIREBASE_API_KEY}`,
    { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ grant_type: "refresh_token", refresh_token: CONFIG.REFRESH_TOKEN }) }
  );
  const data = await res.json();
  if (!data.id_token) { console.error("❌ Token refresh failed:", data); process.exit(1); }
  bearerToken = data.id_token;
  CONFIG.REFRESH_TOKEN = data.refresh_token;
  lastRefresh = Date.now();
  console.log("✅ Token refreshed");
}

async function ensureFreshToken() {
  if (Date.now() - lastRefresh > CONFIG.TOKEN_REFRESH_MS) await refreshBearerToken();
}

function headers() {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${bearerToken}`,
    Accept: "*/*",
    "user-agent": "Fizz/100 CFNetwork/3860.300.31 Darwin/25.2.0",
  };
}

async function apiPost(path, body) {
  await ensureFreshToken();
  const res = await fetch(`${CONFIG.FIZZ_API_BASE}/api/v1${path}`, {
    method: "POST", headers: headers(), body: JSON.stringify(body)
  });
  const text = await res.text();
  try { return { status: res.status, body: JSON.parse(text) }; }
  catch { return { status: res.status, body: text }; }
}

async function pMap(items, fn, concurrency) {
  const results = [];
  let i = 0;
  async function worker() {
    while (i < items.length) {
      const idx = i++;
      results[idx] = await fn(items[idx], idx);
    }
  }
  await Promise.all(Array.from({ length: concurrency }, worker));
  return results;
}

const c = CONFIG.COMMUNITY;

async function getSimilar(postID) {
  const r = await apiPost("/posts/get-similar-posts", { data: { communityID: c, postID } });
  if (r.status === 200 && Array.isArray(r.body?.result)) return r.body.result;
  return [];
}

function loadExisting() {
  if (!fs.existsSync(CONFIG.OUTPUT_FILE)) return null;
  try {
    const data = JSON.parse(fs.readFileSync(CONFIG.OUTPUT_FILE, "utf8"));
    if (data.posts && data.edges) return data;
  } catch {}
  return null;
}

function save(allPosts, edges, depth) {
  const sortedPosts = Array.from(allPosts.values())
    .sort((a, b) => (b.likesMinusDislikes || 0) - (a.likesMinusDislikes || 0));
  fs.writeFileSync(CONFIG.OUTPUT_FILE, JSON.stringify({
    crawledAt: new Date().toISOString(),
    totalUnique: sortedPosts.length,
    totalEdges: edges.length,
    depthReached: depth,
    posts: sortedPosts,
    edges,
  }, null, 2));
}

async function main() {
  const args = process.argv.slice(2);
  const forceRestart = args.includes("--restart");
  const recentOnly = args.includes("--recent") || args.includes("--recent-hops");
  const recentCutoff = Date.now() / 1000 - 1 * 86400; // 1 day ago in unix seconds

  // --recent-hops N: expand recent posts freely, but also follow N hops into older posts
  const hopsIdx = args.indexOf("--recent-hops");
  const recentHops = hopsIdx !== -1 ? parseInt(args[hopsIdx + 1]) || 1 : 0;

  if (recentOnly && recentHops > 0) console.log(`── --recent-hops ${recentHops}: seeding from last 7 days, following ${recentHops} hop(s) into older posts`);
  else if (recentOnly) console.log("── --recent flag: only expanding posts from the last 7 days");

  await refreshBearerToken();

  const allPosts = new Map();
  const seenIDs = new Set();
  const queriedIDs = new Set();
  const edges = [];

  // ── Load existing data (unless --restart) ─────────────────────────────
  const existing = !forceRestart && loadExisting();
  if (existing) {
    console.log(`\n── Resuming from existing data (${existing.totalUnique} posts, ${existing.totalEdges} edges)...`);
    for (const p of existing.posts) {
      allPosts.set(p.postID, p);
      seenIDs.add(p.postID);
    }
    for (const e of existing.edges) {
      edges.push(e);
      queriedIDs.add(e.from);
    }
    // If --recent: un-mark recent posts as queried so they get re-expanded
    // (they may have new neighbors since last crawl)
    if (recentOnly) {
      let unmarked = 0;
      for (const [id, post] of allPosts) {
        if (post.date >= recentCutoff && queriedIDs.has(id)) {
          queriedIDs.delete(id);
          unmarked++;
        }
      }
      console.log(`   Unmarked ${unmarked} recent posts for re-expansion.`);
    }
    console.log(`   Loaded. ${seenIDs.size - queriedIDs.size} posts not yet expanded.`);
  } else {
    if (forceRestart) console.log("\n── --restart flag set, ignoring existing data.");
    console.log("\n── Fetching seed posts from discover...");
    const discoverRes = await apiPost("/feeds/posts/discover-tab-data",
      { data: { communityID: c, clientVersion: "1.23.2", lastPostID: null, feedType: "top" } });
    const seedPosts = discoverRes.body?.result?.postFilterPreviews?.flatMap(f => f.posts) || [];
    console.log(`   ${seedPosts.length} seed posts`);
    for (const p of seedPosts) {
      seenIDs.add(p.postID);
      allPosts.set(p.postID, p);
    }
  }

  // ── Build frontier ─────────────────────────────────────────────────────
  // hopsFromRecent tracks how many hops away from a recent post each post is.
  // Recent posts = 0, direct neighbors of recent = 1, etc.
  // If --recent-hops N: expand posts with hopsFromRecent <= N
  // If --recent (no hops): only expand posts with hopsFromRecent === 0 (i.e. recent posts)
  const hopsFromRecent = new Map(); // postID -> hop distance from nearest recent seed

  // Initialize: recent posts are hop 0
  for (const [id, post] of allPosts) {
    if (post.date >= recentCutoff) hopsFromRecent.set(id, 0);
  }

  function shouldExpand(id) {
    if (queriedIDs.has(id)) return false;
    if (!recentOnly) return true;
    const hops = hopsFromRecent.get(id);
    if (hops === undefined) return false;
    return hops <= recentHops;
  }

  let frontier = Array.from(seenIDs).filter(shouldExpand);

  let depth = existing?.depthReached || 0;

  if (recentOnly) {
    console.log(`\n── Frontier filtered to ${frontier.length} posts from last 7 days (out of ${seenIDs.size - queriedIDs.size} unexpanded)`);
  } else {
    console.log(`\n── Starting crawl from frontier of ${frontier.length} unexpanded posts...`);
  }

  while (frontier.length > 0 && (recentOnly || allPosts.size < CONFIG.MAX_POSTS) && depth < CONFIG.MAX_DEPTH) {
    depth++;
    console.log(`\n── Depth ${depth}: expanding ${frontier.length} posts (${allPosts.size} unique, ${edges.length} edges)...`);

    const newPostIDs = [];

    await pMap(frontier, async (postID) => {
      queriedIDs.add(postID);
      const similar = await getSimilar(postID);
      const parentHops = hopsFromRecent.get(postID) ?? 0;
      for (const p of similar) {
        edges.push({ from: postID, to: p.postID });
        // Update hop distance: take the minimum seen so far
        const childHops = p.date >= recentCutoff ? 0 : parentHops + 1;
        if (!hopsFromRecent.has(p.postID) || hopsFromRecent.get(p.postID) > childHops) {
          hopsFromRecent.set(p.postID, childHops);
        }
        if (!seenIDs.has(p.postID)) {
          seenIDs.add(p.postID);
          allPosts.set(p.postID, p);
          newPostIDs.push(p.postID);
        }
      }
    }, CONFIG.CONCURRENCY);

    console.log(`   +${newPostIDs.length} new posts (${allPosts.size} total unique, ${edges.length} total edges)`);

    if (newPostIDs.length === 0) {
      console.log("   Graph exhausted, stopping.");
      break;
    }

    // Next frontier: newly found posts that are within hop budget
    frontier = newPostIDs.filter(shouldExpand);

    if (recentOnly && frontier.length < newPostIDs.length) {
      console.log(`   (filtered frontier to ${frontier.length} posts within hop budget, skipping ${newPostIDs.length - frontier.length})`);
    }

    save(allPosts, edges, depth);
  }

  save(allPosts, edges, depth);
  const finalPosts = Array.from(allPosts.values()).sort((a, b) => (b.likesMinusDislikes || 0) - (a.likesMinusDislikes || 0));
  console.log(`\n✅ Done! ${finalPosts.length} unique posts, ${edges.length} edges saved to ${CONFIG.OUTPUT_FILE}`);
  console.log(`   Top post: ${finalPosts[0]?.postID} (${finalPosts[0]?.likesMinusDislikes} likes)`);
}

main().catch(console.error);
