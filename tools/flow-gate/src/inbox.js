// 届いた出来事の受け箱。受け取ったと返す前に書くので、処理が落ちても出来事を失わない。1件1キーなので、入れるのと処理するのが重なっても
// 互いを消さない。一時の失敗は間をあけてやり直し（後ろの出来事は先に進む）、直らない失敗と retries 回落ちたものは諦めて failed: に残す。
export class Inbox {
  constructor(storage, process) { Object.assign(this, { storage, process }); }
  push(name, payload) { return this.storage.put(`q:${Date.now()}:${crypto.randomUUID()}`, { name, payload, tries: 0 }); }

  // やり直しを待つ出来事が残れば、次に起こす時刻を返す。
  async drain(retries, now = Date.now()) {
    for (;;) {
      const queue = [...(await this.storage.list({ prefix: "q:" }))];
      const ready = queue.filter(([, e]) => !(e.after > now));
      if (!ready.length) {
        const waits = queue.map(([, e]) => e.after).filter((t) => t > now);
        return waits.length ? Math.min(...waits) : null;
      }
      for (const [key, e] of ready) {
        try {
          await this.process(e.name, e.payload);
        } catch (error) {
          if (error.transient && e.tries + 1 < retries) {
            await this.storage.put(key, { ...e, tries: e.tries + 1, after: now + 2 ** e.tries * 60e3 });
            continue;
          }
          await this.storage.put(`failed:${key}`, { name: e.name, error: String(error.message).split("\n")[0] });
        }
        await this.storage.delete(key);
      }
    }
  }

  async failed() { return [...(await this.storage.list({ prefix: "failed:" })).values()]; }
  async clear() { await this.storage.delete([...(await this.storage.list({ prefix: "failed:" })).keys()]); }
}
