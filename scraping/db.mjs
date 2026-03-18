/**
 * db.mjs — Shared append-only posts database
 *
 * All scrapers merge their results into a single data/posts-db.json file.
 * Posts are deduplicated by postID. When a post is seen again, its fields
 * are updated (newer scrape wins) and _scrapedAt is refreshed.
 *
 * Usage:
 *   import { mergeIntoDB } from "./db.mjs";
 *   mergeIntoDB(posts, "crawl");     // posts = array of post objects
 *   mergeIntoDB(posts, "top-feed");
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DB_PATH = path.resolve(__dirname, "../data/posts-db.json");

/**
 * Load the existing DB, or return an empty structure.
 */
export function loadDB() {
  if (!fs.existsSync(DB_PATH)) {
    return { lastUpdated: null, posts: [] };
  }
  try {
    return JSON.parse(fs.readFileSync(DB_PATH, "utf8"));
  } catch {
    return { lastUpdated: null, posts: [] };
  }
}

/**
 * Merge an array of posts into the DB.
 *
 * @param {Array} newPosts - Array of post objects (must have .postID)
 * @param {string} source  - Label for where these came from (e.g. "crawl", "top-feed")
 * @returns {{ total: number, added: number, updated: number }}
 */
export function mergeIntoDB(newPosts, source) {
  const db = loadDB();

  // Index existing posts by postID for fast lookup
  const index = new Map();
  for (const p of db.posts) {
    if (p.postID) index.set(p.postID, p);
  }

  let added = 0;
  let updated = 0;
  const now = Date.now() / 1000;

  for (const post of newPosts) {
    if (!post.postID) continue;

    if (index.has(post.postID)) {
      // Update: merge fields, newer scrape wins for non-internal fields
      const existing = index.get(post.postID);
      Object.assign(existing, post);
      existing._scrapedAt = now;
      existing._source = source;
      updated++;
    } else {
      // New post
      const entry = { ...post, _scrapedAt: now, _source: source };
      index.set(post.postID, entry);
      added++;
    }
  }

  // Write back sorted by likes descending
  const allPosts = Array.from(index.values()).sort(
    (a, b) => (b.likesMinusDislikes || 0) - (a.likesMinusDislikes || 0)
  );

  const output = {
    lastUpdated: new Date().toISOString(),
    totalPosts: allPosts.length,
    posts: allPosts,
  };

  fs.writeFileSync(DB_PATH, JSON.stringify(output, null, 2));

  console.log(
    `── DB: ${added} added, ${updated} updated → ${allPosts.length} total posts in ${DB_PATH}`
  );

  return { total: allPosts.length, added, updated };
}
