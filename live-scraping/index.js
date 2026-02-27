import Pusher from "pusher-js";
import fetch from "node-fetch";
import fs from "fs";
import dotenv from "dotenv";
import { fileURLToPath } from "url";

const ENV_PATH = fileURLToPath(new URL("../.env", import.meta.url));

dotenv.config({ path: ENV_PATH });

// ─── OPENCLAW ─────────────────────────────────────────────────────────────────
const OPENCLAW_URL = "http://127.0.0.1:18789/hooks/agent";
const OPENCLAW_TOKEN = "REDACTED_TOKEN";
const NOTIFY_NUMBER = "REDACTED_PHONE";

async function notifyFizzPost(post) {
  try {
    const res = await fetch(OPENCLAW_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-openclaw-token": OPENCLAW_TOKEN,
      },
      body: JSON.stringify({
        agentId: "fizzbot",
        channel: "whatsapp",
        to: NOTIFY_NUMBER,
        message: `Review the following post and determine if it is related to fizzbuzz. If and ONLY if it is related, send a WhatsApp message to ${NOTIFY_NUMBER} summarizing it. If it is not related, do nothing.\n\n${post.text}`,
      }),
    });
    const result = await res.json();
    console.log(`   AI: ${res.ok ? "sent to agent" : "error"} — ${JSON.stringify(result)}`);
  } catch (err) {
    console.log(`   AI: failed — ${err.message}`);
  }
}
// ─────────────────────────────────────────────────────────────────────────────

// ─── CONFIG ───────────────────────────────────────────────────────────────────
const CONFIG = {
  REFRESH_TOKEN: process.env.REFRESH_TOKEN,
  FIREBASE_API_KEY: process.env.FIREBASE_API_KEY,
  FIZZ_API_BASE: process.env.FIZZ_API_BASE,
  CDN_BASE: process.env.CDN_BASE,
  PUSHER_APP_KEY: process.env.PUSHER_APP_KEY,
  PUSHER_CLUSTER: process.env.PUSHER_CLUSTER,
  COMMUNITY: process.env.COMMUNITY,
  OUTPUT_FILE: process.env.OUTPUT_FILE || "./posts.json",
};
// ─────────────────────────────────────────────────────────────────────────────

const REQUIRED_CONFIG_KEYS = [
  "REFRESH_TOKEN",
  "FIREBASE_API_KEY",
  "FIZZ_API_BASE",
  "CDN_BASE",
  "PUSHER_APP_KEY",
  "PUSHER_CLUSTER",
  "COMMUNITY",
];

const missingConfig = REQUIRED_CONFIG_KEYS.filter((key) => !CONFIG[key]);
if (missingConfig.length > 0) {
  console.error(`❌ Missing required env vars: ${missingConfig.join(", ")}`);
  process.exit(1);
}

let bearerToken = null;
let savedPosts = [];

// Load existing posts if file exists
if (fs.existsSync(CONFIG.OUTPUT_FILE)) {
  savedPosts = JSON.parse(fs.readFileSync(CONFIG.OUTPUT_FILE, "utf8"));
  console.log(`📂 Loaded ${savedPosts.length} existing posts from disk`);
}

// Refresh Firebase JWT using refresh token
async function refreshBearerToken() {
  console.log("🔄 Refreshing Firebase token...");
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
    console.error("❌ Token refresh failed:", data);
    process.exit(1);
  }
  bearerToken = data.id_token;

  // Update refresh token in case it rotated
  CONFIG.REFRESH_TOKEN = data.refresh_token;

  console.log("✅ Token refreshed successfully");
  return bearerToken;
}

// Authenticate with Pusher via Fizz's auth endpoint
async function pusherAuth(channelName, socketId) {
  const res = await fetch(`${CONFIG.FIZZ_API_BASE}/api/v1/users/auth-pusher`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${bearerToken}`,
      accept: "*/*",
      "user-agent": "Fizz/100 CFNetwork/3860.300.31 Darwin/25.2.0",
    },
    body: JSON.stringify({ channelName, socketID: socketId }),
  });

  if (res.status === 401) {
    // Token expired, refresh and retry
    await refreshBearerToken();
    return pusherAuth(channelName, socketId);
  }

  return await res.json();
}

// Save posts to disk
function savePost(post) {
  const alreadyExists = savedPosts.some((p) => p.id === post.id);
  if (alreadyExists) return false;

  savedPosts.push({ ...post, _savedAt: new Date().toISOString() });
  fs.writeFileSync(CONFIG.OUTPUT_FILE, JSON.stringify(savedPosts, null, 2));
  console.log(`💾 Saved post ${post.id} (total: ${savedPosts.length})`);
  return true;
}

function sanitizePost(contentType, d) {
  const post = {
    id: d.postID,
    date: d.date,
    contentType,
    postType: d.postType,
    flair: d.flair,
    text: d.text,
    media: d.media,
  };
  if (d.reFizz) {
    post.reFizz = sanitizePost(d.reFizzContentType, d.reFizz);
  }
  return post;
}

async function main() {
  await refreshBearerToken();

  console.log(`🚀 Connecting to Pusher channel: private-community-${CONFIG.COMMUNITY}`);

  const pusher = new Pusher(CONFIG.PUSHER_APP_KEY, {
    cluster: CONFIG.PUSHER_CLUSTER,
    forceTLS: true,
    authorizer: (channel) => ({
      authorize: async (socketId, callback) => {
        try {
          const auth = await pusherAuth(channel.name, socketId);
          callback(null, auth);
        } catch (err) {
          callback(err, null);
        }
      },
    }),
  });

  pusher.connection.bind("connected", () => {
    console.log("✅ Connected to Pusher!");
  });

  pusher.connection.bind("error", (err) => {
    console.error("❌ Pusher connection error:", err);
  });

  // Subscribe to the community channel
  const channel = pusher.subscribe(`private-community-${CONFIG.COMMUNITY}`);

  channel.bind("pusher:subscription_succeeded", () => {
    console.log(`✅ Subscribed to private-community-${CONFIG.COMMUNITY}`);
    console.log("👂 Listening for new posts...\n");
  });

  channel.bind("pusher:subscription_error", (err) => {
    console.error("❌ Subscription error:", err);
  });

  channel.bind_global((eventName, data) => {
    if (eventName.startsWith("pusher:")) return;

    if (data?.data?.postID) {
      const post = sanitizePost(data.contentType, data.data);
      const isNew = savePost(post);
      if (isNew) {
        console.log(`\n📝 "${post.text || "(no text)"}"`);
        notifyFizzPost(post);
      }
    }
  });

  // Refresh token every 55 minutes (expires every 60)
  setInterval(refreshBearerToken, 55 * 60 * 1000);
}

main().catch(console.error);
