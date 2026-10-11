// 振り出しの窓口（Durable Object）。同じ名前の窓口は1つしかないので、出来事と定時の振り出しをここで1つずつ順に扱い、
// 起こした担当を覚える。実行の一覧に新しい実行が出るまでには遅れがあり、一覧だけを読むと、起こした直後に同じタスクをまたつかむ。
import { DurableObject } from "cloudflare:workers";
import { dispatch, withClaims } from "./dispatch.js";
import { readRuns } from "./facts.js";
import { GitHub } from "./github.js";

export class Dispatcher extends DurableObject {
  // 外への問い合わせを待つ間にも次の頼みが届くので、前の振り出しが終わってから次を始める。
  chain = Promise.resolve();

  // tasks は読み済みのボードの開いたタスク（無ければ dispatch が読む）。
  dispatch(config, tasks) {
    const next = this.chain.then(() => this.#dispatch(config, tasks));
    this.chain = next.catch(() => {});
    return next;
  }

  async #dispatch(config, tasks) {
    const gh = await GitHub.app(this.env, config.installation);
    const now = Date.now();
    // 覚えた担当は、一覧に出るまでと、すぐ終わったときに同じタスクを起こし直さないよう、claimMinutes の間は持たれているとみなす。
    const claims = ((await this.ctx.storage.get("claims")) ?? []).filter((c) => now - c.at < config.claimMinutes * 60e3);
    const sent = await dispatch(gh, config, withClaims(await readRuns(gh, config), claims, config, now), tasks);
    await this.ctx.storage.put("claims", [...claims, ...sent.picked.map((p) => ({ number: Number(p.issue), kind: p.kind, at: now }))]);
    return sent;
  }
}
