// 見回りの置き場（Durable Object。1つだけ）。担当の記録と出来事の受け箱を置き、受け箱をアラームで処理する（アラームは少なくとも1回は動く）。
import { DurableObject } from "cloudflare:workers";
import { config } from "./config.js";
import { handle } from "./flow.js";
import { GitHub } from "./github.js";
import { Inbox } from "./inbox.js";
import { Patrol } from "./patrol.js";

export class Dispatcher extends DurableObject {
  patrol = new Patrol(this.ctx.storage);
  inbox = new Inbox(this.ctx.storage, async (name, payload) => handle(await GitHub.app(this.env, config.installation), this, config, name, payload));

  async enqueue(name, payload) {
    await this.inbox.push(name, payload);
    if (!(await this.ctx.storage.getAlarm())) await this.ctx.storage.setAlarm(Date.now());
  }

  // 処理の間に入った出来事が早いアラームを置いていれば、それより遅いやり直しの時刻で上書きしない。
  async alarm() {
    const next = await this.inbox.drain(config.retries);
    const set = await this.ctx.storage.getAlarm();
    if (next && !(set <= next)) await this.ctx.storage.setAlarm(next);
  }
}
