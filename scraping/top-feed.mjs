/**
 * top-feed.mjs — Scrape the Fizz "Top" feed via /api/v1/users/feed
 *
 * Discovery: This endpoint was found by reading the macOS Fizz app's
 * NSURLCache SQLite database after MITM interception failed due to
 * certificate pinning (TCP + QUIC/HTTP3). The endpoint supports
 * cursor-based pagination (20 posts/page) via lastPostID.
 *
 * Usage:
 *   node top-feed.mjs                        # default: home_top, 1000 posts
 *   node top-feed.mjs --feed home_top_week        # different feed type
 *   node top-feed.mjs --max 2000             # more posts
 *   node top-feed.mjs --feed home_top --max 1000 --output ../data/top-feed.json
 *   node top-feed.mjs --all-feeds            # scrape all feed types
 */

import fetch from "node-fetch";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { mergeIntoDB } from "./db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ENV_PATH = fileURLToPath(new URL("../.env", import.meta.url));

function loadEnv(p) {
  if (!fs.existsSync(p)) return;
  for (const line of fs.readFileSync(p, "utf8").split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const i = t.indexOf("=");
    if (i === -1) continue;
    const k = t.slice(0, i).trim(), v = t.slice(i + 1).trim();
    if (k && !process.env[k]) process.env[k] = v;
  }
}
loadEnv(ENV_PATH);

const CONFIG = {
  REFRESH_TOKEN: process.env.REFRESH_TOKEN,
  FIREBASE_API_KEY: process.env.FIREBASE_API_KEY,
  FIZZ_API_BASE: process.env.FIZZ_API_BASE,
  COMMUNITY: process.env.COMMUNITY || "Yale",
  CLIENT_VERSION: "1.25.0",
};

let bearerToken = null;
let lastRefresh = 0;

async function refreshBearerToken() {
  const res = await fetch(
    `https://securetoken.googleapis.com/v1/token?key=${CONFIG.FIREBASE_API_KEY}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        grant_type: "refresh_token",
        refresh_token: CONFIG.REFRESH_TOKEN,
      }),
    }
  );
  const data = await res.json();
  if (!data.id_token) {
    console.error("Token refresh failed:", data);
    process.exit(1);
  }
  bearerToken = data.id_token;
  CONFIG.REFRESH_TOKEN = data.refresh_token;
  lastRefresh = Date.now();
}

async function ensureFreshToken() {
  if (Date.now() - lastRefresh > 50 * 60 * 1000) {
    await refreshBearerToken();
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

const delay = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchFeedPage(feedType, firstRequest, lastPostID) {
  await ensureFreshToken();

  const body = {
    data: {
      communityID: CONFIG.COMMUNITY,
      clientVersion: CONFIG.CLIENT_VERSION,
      feedType,
      firstRequest,
    },
  };
  if (lastPostID) body.data.lastPostID = lastPostID;

  for (let attempt = 0; attempt < 3; attempt++) {
    const res = await fetch(`${CONFIG.FIZZ_API_BASE}/api/v1/users/feed`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify(body),
    });

    if (res.status === 429 || res.status === 403) {
      const wait = 2000 * (attempt + 1);
      console.warn(`  Rate limited (${res.status}), waiting ${wait}ms...`);
      await delay(wait);
      if (attempt === 0) lastRefresh = 0; // force token refresh
      continue;
    }

    if (!res.ok) {
      const text = await res.text();
      console.error(`  HTTP ${res.status}: ${text.slice(0, 200)}`);
      return null;
    }

    const data = await res.json();
    return data.result?.items || [];
  }

  return null;
}

async function scrapeFeed(feedType, maxPosts) {
  console.log(`\n── Scraping ${feedType} (max ${maxPosts} posts)...`);

  const allPosts = [];
  const seenIDs = new Set();
  let lastPostID = null;
  let page = 0;
  let emptyPages = 0;

  while (allPosts.length < maxPosts) {
    page++;
    const firstRequest = page === 1;
    const items = await fetchFeedPage(feedType, firstRequest, lastPostID);

    if (items === null) {
      console.error(`  Failed on page ${page}, stopping.`);
      break;
    }

    if (items.length === 0) {
      emptyPages++;
      if (emptyPages >= 2) {
        console.log(`  End of feed (${emptyPages} empty pages).`);
        break;
      }
      continue;
    }

    emptyPages = 0;
    let newCount = 0;
    for (const entry of items) {
      const post = entry.item;
      if (!post?.postID || seenIDs.has(post.postID)) continue;
      seenIDs.add(post.postID);
      allPosts.push(post);
      newCount++;
    }

    lastPostID = items[items.length - 1]?.item?.postID;

    const lastLikes = items[items.length - 1]?.item?.likesMinusDislikes ?? "?";
    process.stdout.write(
      `\r  Page ${page}: ${allPosts.length} posts (+${newCount}), last likes=${lastLikes}`.padEnd(
        80
      )
    );

    // Small delay to be respectful
    await delay(200);
  }

  process.stdout.write("\n");
  console.log(`  Done: ${allPosts.length} unique posts from ${page} pages.`);
  return allPosts;
}

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = {
    feedType: "home_top_week",
    maxPosts: 1000,
    output: null,
    allFeeds: false,
  };

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--feed" && args[i + 1]) opts.feedType = args[++i];
    if (args[i] === "--max" && args[i + 1]) opts.maxPosts = parseInt(args[++i]);
    if (args[i] === "--output" && args[i + 1])
      opts.output = path.resolve(__dirname, args[++i]);
    if (args[i] === "--all-feeds") opts.allFeeds = true;
  }

  if (!opts.output) {
    opts.output = path.resolve(__dirname, `../data/${opts.feedType}.json`);
  }

  return opts;
}

const MAIN_FEEDS = [
  "home_top",
  "home_new",
  "home_fizzin",
  "home_top_day",
  "home_top_week",
  "home_top_all",
];

async function main() {
  const opts = parseArgs();

  await refreshBearerToken();
  console.log(`── Fizz Feed Scraper`);
  console.log(`   Community: ${CONFIG.COMMUNITY}`);

  if (opts.allFeeds) {
    console.log(`   Mode: all main feeds (${MAIN_FEEDS.join(", ")})`);
    const results = {};
    const allUnique = new Map();

    for (const feedType of MAIN_FEEDS) {
      const posts = await scrapeFeed(feedType, opts.maxPosts);
      results[feedType] = posts.length;
      for (const p of posts) {
        if (!allUnique.has(p.postID)) allUnique.set(p.postID, p);
      }
    }

    const output = {
      scrapedAt: new Date().toISOString(),
      community: CONFIG.COMMUNITY,
      feedCounts: results,
      totalUnique: allUnique.size,
      posts: Array.from(allUnique.values()).sort(
        (a, b) => (b.likesMinusDislikes || 0) - (a.likesMinusDislikes || 0)
      ),
    };

    const outPath = path.resolve(__dirname, "../data/all-feeds.json");
    fs.writeFileSync(outPath, JSON.stringify(output, null, 2));

    // Merge into shared posts DB
    mergeIntoDB(output.posts, "top-feed");

    console.log(`\n── Summary:`);
    for (const [feed, count] of Object.entries(results)) {
      console.log(`   ${feed}: ${count}`);
    }
    console.log(`   Total unique: ${allUnique.size}`);
    console.log(`   Saved to ${outPath}`);
  } else {
    console.log(`   Feed: ${opts.feedType}`);
    console.log(`   Max posts: ${opts.maxPosts}`);

    const posts = await scrapeFeed(opts.feedType, opts.maxPosts);

    const output = {
      scrapedAt: new Date().toISOString(),
      community: CONFIG.COMMUNITY,
      feedType: opts.feedType,
      totalPosts: posts.length,
      posts,
    };

    fs.writeFileSync(opts.output, JSON.stringify(output, null, 2));

    // Merge into shared posts DB
    mergeIntoDB(posts, "top-feed");

    console.log(`   Saved to ${opts.output}`);

    if (posts.length > 0) {
      const top = posts[0];
      const bottom = posts[posts.length - 1];
      console.log(
        `   Top: "${top.text?.slice(0, 50)}..." (${top.likesMinusDislikes} likes)`
      );
      console.log(
        `   Bottom: "${bottom.text?.slice(0, 50)}..." (${bottom.likesMinusDislikes} likes)`
      );
    }
  }
}

main().catch(console.error);
