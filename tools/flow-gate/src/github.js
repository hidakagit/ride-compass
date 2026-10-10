// GitHub の REST と GraphQL。ゲートと回答フォームは App（env.APP_ID と PKCS#8 の env.APP_KEY）のインストールの名義で、
// 道具はトークンの名義で打つ。一時の失敗（5xx・つながらない・GraphQL の上限）だけを、間をあけて打ち直す。書く要求は打ち直さない
// （失敗の応答でも書けていることがあり、二重に書く）。
const API = "https://api.github.com";
const AGAIN = [1, 4, 9];
const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const cache = new Map();

async function again(call, retry) {
  for (let i = 0; ; i++) {
    try {
      return await call();
    } catch (e) {
      if (!retry || !e.transient || i === AGAIN.length) throw e;
      await new Promise((r) => setTimeout(r, AGAIN[i] * 1e3));
    }
  }
}
const fail = (message, transient) => Object.assign(new Error(message), { transient });

export class GitHub {
  constructor(token) {
    this.token = token;
  }

  // インストールのトークンは1時間有効なので、切れる5分前まで使い回す（公式の文書「Authenticating as a GitHub App installation」）。
  static async app(env, installation) {
    const hit = cache.get(installation);
    if (hit?.expires - Date.now() > 300e3) return new GitHub(hit.token);
    const der = Uint8Array.from(atob(env.APP_KEY.replace(/-----[^-]+-----|\s+/g, "")), (c) => c.charCodeAt(0));
    const key = await crypto.subtle.importKey("pkcs8", der, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
    const now = Math.floor(Date.now() / 1000);
    const part = (o) => b64url(new TextEncoder().encode(JSON.stringify(o)));
    const data = `${part({ alg: "RS256", typ: "JWT" })}.${part({ iat: now - 60, exp: now + 540, iss: String(env.APP_ID) })}`;
    const jwt = `${data}.${b64url(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(data)))}`;
    const t = await new GitHub(jwt).rest("POST", `/app/installations/${installation}/access_tokens`);
    cache.set(installation, { token: t.token, expires: Date.parse(t.expires_at) });
    return new GitHub(t.token);
  }

  // path は API の中の道か、応答が返した URL（リリースの upload_url 等）。type を渡すと body をそのまま送る（JSON にしない）。
  rest(method, path, body, type = null) {
    return again(async () => {
      const res = await fetch(path.startsWith("https://") ? path : API + path, {
        method,
        headers: { authorization: `Bearer ${this.token}`, accept: "application/vnd.github+json", "x-github-api-version": "2022-11-28", "user-agent": "ridecompass-flow",
          ...(type ? { "content-type": type } : {}) },
        body: body === undefined || type ? body : JSON.stringify(body),
      }).catch((e) => { throw fail(e.message, true); });
      if (!res.ok) throw fail(`GitHub ${method} ${path}: ${res.status} ${(await res.text()).slice(0, 200)}`, res.status >= 500);
      // 本文の無い応答は null、JSON でない応答（Markdown の描画の HTML 等）は文字列。
      return res.status === 204 ? null : res.headers.get("content-type")?.includes("json") ? res.json() : res.text();
    }, method === "GET");
  }

  // 読む問い合わせは、一時の失敗と GraphQL の上限なら打ち直す。書く問い合わせ（mutation）は打ち直さない。
  gql(query, variables = {}) {
    return again(async () => {
      const r = await this.rest("POST", "/graphql", { query, variables });
      if (r.errors) throw fail(`GraphQL: ${r.errors.map((e) => e.message).join(" / ")}`, r.errors.some((e) => e.type === "RATE_LIMITED"));
      return r.data;
    }, !/^\s*mutation/.test(query));
  }
}
