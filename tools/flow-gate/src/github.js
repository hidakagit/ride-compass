// GitHub の REST と GraphQL を、App（env.APP_ID と PKCS#8 の env.APP_KEY）のインストールの名義で打つ。失敗には、やり直せば直りうるか
// （5xx・つながらない・GraphQL の上限）を transient で付ける（やり直すのは src/inbox.js: Inbox）。
const API = "https://api.github.com";
const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const fail = (message, transient) => Object.assign(new Error(message), { transient });

export class GitHub {
  constructor(token) {
    this.token = token;
  }

  static async app(env, installation) {
    const der = Uint8Array.from(atob(env.APP_KEY.replace(/-----[^-]+-----|\s+/g, "")), (c) => c.charCodeAt(0));
    const key = await crypto.subtle.importKey("pkcs8", der, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
    const now = Math.floor(Date.now() / 1000);
    const part = (o) => b64url(new TextEncoder().encode(JSON.stringify(o)));
    const data = `${part({ alg: "RS256", typ: "JWT" })}.${part({ iat: now - 60, exp: now + 540, iss: String(env.APP_ID) })}`;
    const jwt = `${data}.${b64url(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(data)))}`;
    return new GitHub((await new GitHub(jwt).rest("POST", `/app/installations/${installation}/access_tokens`)).token);
  }

  async rest(method, path, body) {
    const res = await fetch(API + path, {
      method,
      headers: { authorization: `Bearer ${this.token}`, accept: "application/vnd.github+json", "x-github-api-version": "2022-11-28", "user-agent": "ridecompass-flow" },
      body: body === undefined ? body : JSON.stringify(body),
    }).catch((e) => { throw fail(e.message, true); });
    if (!res.ok) throw fail(`GitHub ${method} ${path}: ${res.status} ${(await res.text()).slice(0, 200)}`, res.status >= 500);
    // 本文の無い応答は null、JSON でない応答（Markdown の描画の HTML 等）は文字列。
    return res.status === 204 ? null : res.headers.get("content-type")?.includes("json") ? res.json() : res.text();
  }

  async gql(query, variables = {}) {
    const r = await this.rest("POST", "/graphql", { query, variables });
    if (r.errors) throw fail(`GraphQL: ${r.errors.map((e) => e.message).join(" / ")}`, r.errors.some((e) => e.type === "RATE_LIMITED"));
    return r.data;
  }
}
