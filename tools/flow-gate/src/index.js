// ゲートの入口。同じコードを2つの Worker に置き、秘密の値を持つ口だけを開ける: /webhook は WEBHOOK_SECRET を持つ Worker
// （Cloudflare Access の外）、/answer は FORM_TOKEN を持つ Worker（ホスト全体が Access の内側）。
import { config } from "./config.js";
import { answerForm } from "./form.js";

export { Dispatcher } from "./dispatcher.js";

// 出来事は、見回りの置き場（src/dispatcher.js: Dispatcher。1つだけ）の受け箱へ入れる。
const enqueue = (env, name, payload) => env.DISPATCHER.get(env.DISPATCHER.idFromName("one")).enqueue(name, payload);
// 回答フォームへのボタン（GitHub の本文にボタンは置けないので、本文の頭にリンク付きの画像として置く）。
const BUTTON = `<svg xmlns="http://www.w3.org/2000/svg" width="152" height="44"><rect width="152" height="44" rx="8" fill="#1f6feb"/><text x="76" y="28" text-anchor="middle"
 font-size="17" font-weight="700" fill="#fff" font-family="system-ui,'Hiragino Sans','Noto Sans JP',sans-serif">回答する</text></svg>`;

// X-Hub-Signature-256 を HMAC で確かめる（verify は一定時間で比べる）。
async function signed(secret, body, header) {
  const hex = /^sha256=([0-9a-f]{64})$/.exec(header ?? "")?.[1];
  if (!hex) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  return crypto.subtle.verify("HMAC", key, Uint8Array.from(hex.match(/../g), (h) => parseInt(h, 16)), new TextEncoder().encode(body));
}

export default {
  async fetch(request, env, ctx) {
    const { pathname } = new URL(request.url);
    if (pathname === "/webhook" && request.method === "POST" && env.WEBHOOK_SECRET) {
      const body = await request.text();
      if (!(await signed(env.WEBHOOK_SECRET, body, request.headers.get("x-hub-signature-256")))) return new Response("bad signature", { status: 401 });
      // 受け箱へ書けてから受け取ったと返す。書けなければ失敗を返し、GitHub の配達の記録に残る。
      await enqueue(env, request.headers.get("x-github-event"), JSON.parse(body));
      return new Response("accepted", { status: 202 });
    }
    if (pathname === "/button.svg") return new Response(BUTTON, { headers: { "content-type": "image/svg+xml", "cache-control": "public, max-age=86400" } });
    if (pathname === "/answer" && env.FORM_TOKEN) return answerForm(request, env, config);
    return new Response("not found", { status: 404 });
  },
  // 定時（wrangler.toml の triggers）。
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(enqueue(env, "schedule", {}));
  },
};
