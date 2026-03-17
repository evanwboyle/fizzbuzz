import fetch from "node-fetch";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
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
  OUTPUT_FILE: path.resolve(__dirname, process.env.CRAWL_OUTPUT_FILE),
  MAX_QUERIES: Number(process.env.CRAWL_MAX_QUERIES || 2000),
  CONCURRENCY: Number(process.env.CRAWL_CONCURRENCY),
  TOKEN_REFRESH_MS: Number(process.env.CRAWL_TOKEN_REFRESH_MS),
  SEED_FILE: path.resolve(__dirname, process.env.SEED_FILE || "../data/posts.json"),
};

const REQUIRED_CONFIG_KEYS = [
  "REFRESH_TOKEN",
  "FIREBASE_API_KEY",
  "FIZZ_API_BASE",
  "COMMUNITY",
  "OUTPUT_FILE",
  "CONCURRENCY",
  "TOKEN_REFRESH_MS",
];

const missingConfig = REQUIRED_CONFIG_KEYS.filter((key) => {
  const value = CONFIG[key];
  if (typeof value === "number") return Number.isNaN(value);
  return !value;
});

if (missingConfig.length > 0) {
  console.error(`Missing required env vars for crawl: ${missingConfig.join(", ")}`);
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
  if (!data.id_token) { console.error("Token refresh failed:", data); process.exit(1); }
  bearerToken = data.id_token;
  CONFIG.REFRESH_TOKEN = data.refresh_token;
  lastRefresh = Date.now();
  console.log("Token refreshed");
}

let _refreshPromise = null;

async function ensureFreshToken() {
  if (Date.now() - lastRefresh > CONFIG.TOKEN_REFRESH_MS) {
    // Prevent concurrent workers from all refreshing at once
    if (!_refreshPromise) {
      _refreshPromise = refreshBearerToken().finally(() => { _refreshPromise = null; });
    }
    await _refreshPromise;
  }
}

function headers() {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${bearerToken}`,
    Accept: "*/*",
    "user-agent": "Fizz/100 CFNetwork/3860.300.31 Darwin/25.2.0",
  };
}

const delay = (ms) => new Promise(r => setTimeout(r, ms));

async function apiPost(path, body) {
  for (let attempt = 0; attempt < 3; attempt++) {
    await ensureFreshToken();
    const res = await fetch(`${CONFIG.FIZZ_API_BASE}/api/v1${path}`, {
      method: "POST", headers: headers(), body: JSON.stringify(body)
    });
    if (res.status === 403 || res.status === 429) {
      // Could be rate limit (API returns 403 instead of 429) or token expiry
      if (attempt === 0 && Date.now() - lastRefresh > 5 * 60 * 1000) {
        lastRefresh = 0; // force token refresh on next attempt
      }
      await delay(1000 * (attempt + 1)); // backoff: 1s, 2s
      continue;
    }
    const text = await res.text();
    try { return { status: res.status, body: JSON.parse(text) }; }
    catch { return { status: res.status, body: text }; }
  }
  // All retries exhausted
  return { status: 403, body: "rate limited after 3 attempts" };
}

const c = CONFIG.COMMUNITY;

// ── Stats tracking ──────────────────────────────────────────────────────
let stats = { sent: 0, done: 0, errors: 0, skipped: 0, newPosts: 0 };

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function getSimilar(postID) {
  const r = await apiPost("/posts/get-similar-posts", { data: { communityID: c, postID } });
  const ok = r.status === 200 && Array.isArray(r.body?.result);
  if (!ok) {
    stats.errors++;
    // 403 = deleted/removed post, 404 = not found — don't spam logs for these
    if (r.status !== 403 && r.status !== 404) {
      const msg = typeof r.body === "string" ? r.body.slice(0, 120) : JSON.stringify(r.body).slice(0, 120);
      console.error(`\n   ERR [${r.status}] postID=${postID}: ${msg}`);
    }
  }
  return ok ? r.body.result : [];
}

function printProgress(budget, recentCount, lastResult) {
  const preview = lastResult
    ? lastResult.slice(0, 2).map(p => `${p.postID?.slice(0, 8)}(${p.likesMinusDislikes ?? "?"})`).join(", ")
    : "...";
  process.stdout.write(
    `\r   [${stats.done}/${budget}] +${stats.newPosts} new | ` +
    `recent=${recentCount} | errs=${stats.errors} skip=${stats.skipped} | ${preview}`.padEnd(110)
  );
}

function loadExisting() {
  if (!fs.existsSync(CONFIG.OUTPUT_FILE)) return null;
  try {
    const data = JSON.parse(fs.readFileSync(CONFIG.OUTPUT_FILE, "utf8"));
    if (data.posts && data.edges) return data;
  } catch {}
  return null;
}

function save(allPosts, edges, queriedCount, recentCount) {
  const sortedPosts = Array.from(allPosts.values())
    .sort((a, b) => (b.likesMinusDislikes || 0) - (a.likesMinusDislikes || 0));
  fs.writeFileSync(CONFIG.OUTPUT_FILE, JSON.stringify({
    crawledAt: new Date().toISOString(),
    totalUnique: sortedPosts.length,
    totalEdges: edges.length,
    queriesUsed: queriedCount,
    recentPosts: recentCount,
    posts: sortedPosts,
    edges,
  }, null, 2));
}

// ── Priority queue (max-heap by score) ──────────────────────────────────
function createPriorityQueue() {
  const heap = [];

  function parent(i) { return (i - 1) >> 1; }
  function left(i) { return 2 * i + 1; }
  function right(i) { return 2 * i + 2; }

  function swap(i, j) { [heap[i], heap[j]] = [heap[j], heap[i]]; }

  function siftUp(i) {
    while (i > 0 && heap[i].score > heap[parent(i)].score) {
      swap(i, parent(i));
      i = parent(i);
    }
  }

  function siftDown(i) {
    const n = heap.length;
    while (true) {
      let max = i;
      const l = left(i), r = right(i);
      if (l < n && heap[l].score > heap[max].score) max = l;
      if (r < n && heap[r].score > heap[max].score) max = r;
      if (max === i) break;
      swap(i, max);
      i = max;
    }
  }

  return {
    push(id, score) { heap.push({ id, score }); siftUp(heap.length - 1); },
    pop() {
      if (heap.length === 0) return null;
      const top = heap[0];
      const last = heap.pop();
      if (heap.length > 0) { heap[0] = last; siftDown(0); }
      return top;
    },
    get size() { return heap.length; },
  };
}

// ── Scoring: prioritize recent + high-engagement posts ──────────────────
function scorePost(post, recencyCutoff) {
  let score = 0;
  // Recent posts get a large boost
  if (post.date && post.date >= recencyCutoff) {
    score += 1000;
  }
  // Engagement boost (capped to avoid extreme outliers dominating)
  const likes = Math.min(Math.max(post.likesMinusDislikes || 0, -50), 200);
  score += likes;
  return score;
}

// ── CLI arg parsing ─────────────────────────────────────────────────────
function parseArgs(argv) {
  const args = argv.slice(2);
  const opts = {
    restart: args.includes("--restart"),
    stats: args.includes("--stats"),
    maxQueries: CONFIG.MAX_QUERIES,
    recentTarget: 0,   // 0 = no target, crawl until budget exhausted
    recencyDays: 7,
  };

  const mqIdx = args.indexOf("--max-queries");
  if (mqIdx !== -1) opts.maxQueries = parseInt(args[mqIdx + 1]) || opts.maxQueries;

  const rtIdx = args.indexOf("--recent-target");
  if (rtIdx !== -1) opts.recentTarget = parseInt(args[rtIdx + 1]) || 500;

  const rdIdx = args.indexOf("--recency");
  if (rdIdx !== -1) {
    const val = args[rdIdx + 1] || "7d";
    opts.recencyDays = parseInt(val) || 7;
  }

  return opts;
}

async function main() {
  const opts = parseArgs(process.argv);
  // Anchor cutoff to start of today (midnight local) so it's stable across runs
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const recencyCutoff = startOfToday.getTime() / 1000 - (opts.recencyDays - 1) * 86400;

  // ── --stats: show diagnostics and exit ────────────────────────────────
  if (opts.stats) {
    const data = loadExisting();
    if (!data) { console.log("No crawl data found at", CONFIG.OUTPUT_FILE); process.exit(0); }

    const posts = data.posts || [];
    const edges = data.edges || [];
    const now = Date.now() / 1000;
    const day = 86400;

    const buckets = { "<1d": 0, "1-3d": 0, "3-7d": 0, "7-14d": 0, "14-30d": 0, "30-90d": 0, ">90d": 0, "no_date": 0 };
    for (const p of posts) {
      const age = p.date > 0 ? now - p.date : -1;
      if (age < 0) buckets["no_date"]++;
      else if (age < day) buckets["<1d"]++;
      else if (age < 3 * day) buckets["1-3d"]++;
      else if (age < 7 * day) buckets["3-7d"]++;
      else if (age < 14 * day) buckets["7-14d"]++;
      else if (age < 30 * day) buckets["14-30d"]++;
      else if (age < 90 * day) buckets["30-90d"]++;
      else buckets[">90d"]++;
    }

    const recent = posts.filter(p => p.date >= recencyCutoff);
    const queried = new Set(edges.map(e => e.from));
    const unqueried = posts.filter(p => !queried.has(p.postID));

    console.log(`── Crawl Stats (${CONFIG.OUTPUT_FILE})`);
    console.log(`   Crawled at:   ${data.crawledAt}`);
    console.log(`   Total posts:  ${posts.length}`);
    console.log(`   Total edges:  ${edges.length}`);
    console.log(`   Queries used: ${data.queriesUsed || queried.size}`);
    console.log(`   Unqueried:    ${unqueried.length}`);
    console.log(`   Recent (${opts.recencyDays}d): ${recent.length}`);
    console.log(`\n── Age distribution:`);
    const maxBar = 40;
    const maxCount = Math.max(...Object.values(buckets));
    for (const [label, count] of Object.entries(buckets)) {
      const bar = maxCount > 0 ? "#".repeat(Math.round((count / maxCount) * maxBar)) : "";
      console.log(`   ${label.padStart(7)}: ${String(count).padStart(5)}  ${bar}`);
    }

    const topRecent = recent.sort((a, b) => (b.likesMinusDislikes || 0) - (a.likesMinusDislikes || 0)).slice(0, 5);
    if (topRecent.length > 0) {
      console.log(`\n── Top recent posts:`);
      for (const p of topRecent) {
        const age = ((now - p.date) / day).toFixed(1);
        const text = (p.text || "").slice(0, 60).replace(/\n/g, " ");
        console.log(`   ${p.postID.slice(0, 8)}  ${String(p.likesMinusDislikes ?? 0).padStart(4)} likes  ${age}d ago  ${text}`);
      }
    }

    process.exit(0);
  }

  console.log(`── Config: max-queries=${opts.maxQueries}, recent-target=${opts.recentTarget || "none"}, recency=${opts.recencyDays}d`);

  await refreshBearerToken();

  const allPosts = new Map();
  const seenIDs = new Set();
  const queriedIDs = new Set();
  const edges = [];
  const queue = createPriorityQueue();

  // ── Load existing data (unless --restart) ─────────────────────────────
  const existing = !opts.restart && loadExisting();
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
    console.log(`   Loaded. ${seenIDs.size - queriedIDs.size} posts not yet expanded.`);
  } else {
    if (opts.restart) console.log("\n── --restart flag set, ignoring existing data.");
    console.log("\n── Fetching seed posts from discover...");
    const discoverRes = await apiPost("/feeds/posts/discover-tab-data",
      { data: { communityID: c, clientVersion: "1.23.2", lastPostID: null, feedType: "top" } });
    const seedPosts = discoverRes.body?.result?.postFilterPreviews?.flatMap(f => f.posts) || [];
    console.log(`   ${seedPosts.length} seed posts from discover`);
    for (const p of seedPosts) {
      seenIDs.add(p.postID);
      allPosts.set(p.postID, p);
    }
  }

  // ── Inject IDs from seed file ─────────────────────────────────────────
  if (fs.existsSync(CONFIG.SEED_FILE)) {
    const seedData = JSON.parse(fs.readFileSync(CONFIG.SEED_FILE, "utf8"));
    const seedArray = Array.isArray(seedData) ? seedData : [];
    let added = 0;
    for (const entry of seedArray) {
      const id = entry.id || entry.postID;
      if (id && !seenIDs.has(id)) {
        seenIDs.add(id);
        allPosts.set(id, { postID: id, text: entry.text || "", date: entry.date || 0, _seedFile: true });
        added++;
      }
    }
    if (added > 0) console.log(`── Seed file: loaded ${added} new post IDs from ${CONFIG.SEED_FILE}`);
  }

  // ── Populate priority queue with un-queried posts ─────────────────────
  function countRecent() {
    let n = 0;
    for (const [, post] of allPosts) {
      if (post.date >= recencyCutoff) n++;
    }
    return n;
  }

  for (const [id, post] of allPosts) {
    if (!queriedIDs.has(id)) {
      queue.push(id, scorePost(post, recencyCutoff));
    }
  }

  console.log(`\n── ${queue.size} posts in queue (${countRecent()} recent), budget=${opts.maxQueries} queries`);
  console.log(`── Crawling with ${CONFIG.CONCURRENCY} concurrent workers...\n`);

  // ── Continuous worker pool ────────────────────────────────────────────
  let stopping = false;
  let lastSave = Date.now();

  function getNextPostID() {
    while (queue.size > 0) {
      const item = queue.pop();
      if (!item) return null;
      if (queriedIDs.has(item.id)) continue;
      if (!UUID_RE.test(item.id)) { stats.skipped++; queriedIDs.add(item.id); continue; }
      return item.id;
    }
    return null;
  }

  async function worker() {
    while (!stopping) {
      // Check budget
      if (stats.done >= opts.maxQueries) { stopping = true; break; }
      // Check recent target
      if (opts.recentTarget > 0 && countRecent() >= opts.recentTarget) { stopping = true; break; }

      const postID = getNextPostID();
      if (!postID) break;

      queriedIDs.add(postID);
      stats.sent++;

      const similar = await getSimilar(postID);
      stats.done++;

      for (const p of similar) {
        edges.push({ from: postID, to: p.postID });
        if (!seenIDs.has(p.postID)) {
          seenIDs.add(p.postID);
          allPosts.set(p.postID, p);
          stats.newPosts++;
          queue.push(p.postID, scorePost(p, recencyCutoff));
        } else if (p.date && allPosts.has(p.postID)) {
          const existing = allPosts.get(p.postID);
          if (!existing.date && p.date) allPosts.set(p.postID, { ...existing, ...p });
        }
      }

      printProgress(opts.maxQueries, countRecent(), similar);

      // Auto-save every 30s
      if (Date.now() - lastSave > 30000) {
        save(allPosts, edges, stats.done, countRecent());
        lastSave = Date.now();
      }
    }
  }

  await Promise.all(Array.from({ length: CONFIG.CONCURRENCY }, worker));
  process.stdout.write("\n");

  // ── Final save & summary ──────────────────────────────────────────────
  save(allPosts, edges, stats.done, countRecent());
  const finalPosts = Array.from(allPosts.values()).sort((a, b) => (b.likesMinusDislikes || 0) - (a.likesMinusDislikes || 0));
  const finalRecent = finalPosts.filter(p => p.date >= recencyCutoff);

  console.log(`\n── Done!`);
  console.log(`   ${finalPosts.length} unique posts (${finalRecent.length} from last ${opts.recencyDays}d)`);
  console.log(`   ${edges.length} edges, ${stats.done} queries used, ${stats.errors} errors`);
  console.log(`   Saved to ${CONFIG.OUTPUT_FILE}`);
  if (finalPosts[0]) console.log(`   Top post: ${finalPosts[0].postID} (${finalPosts[0].likesMinusDislikes} likes)`);
}

main().catch(console.error);
