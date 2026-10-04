// ゲートの入口。同じコードを2つの Worker に置き、秘密の値を持つ口だけを開ける: /webhook は WEBHOOK_SECRET を持つ Worker
// （Cloudflare Access の外）、/answer は FORM_TOKEN を持つ Worker（ホスト全体が Access の内側）。
import config from "../flow.config.json" with { type: "json" };
import { answerForm } from "./form.js";
import { handleEvent } from "./gate.js";
import { BUTTON_SVG } from "./rules.js";

// X-Hub-Signature-256 を HMAC で確かめる（verify は比較を一定時間で行う）。
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
      // GitHub は10秒で待ちを打ち切るので、受付を先に返して処理は後で続ける。失敗は Cloudflare の記録にだけ残る。
      const name = request.headers.get("x-github-event");
      ctx.waitUntil(handleEvent(env, config, name, JSON.parse(body)).catch((e) => console.error(`処理に失敗: ${name}`, e)));
      return new Response("accepted", { status: 202 });
    }
    if (pathname === "/button.svg" && request.method === "GET")
      return new Response(BUTTON_SVG, { headers: { "content-type": "image/svg+xml", "cache-control": "public, max-age=86400" } });
    if (pathname === "/answer" && ["GET", "POST"].includes(request.method) && env.FORM_TOKEN) return answerForm(request, env, config);
    return new Response("not found", { status: 404 });
  },
};
