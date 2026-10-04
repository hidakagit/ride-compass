// 道具（bin/*.js）の共通部分: 設定・トークン・引数。
import { execFileSync } from "node:child_process";
import config from "../flow.config.json" with { type: "json" };
import { GitHub } from "../src/github.js";

export { config };

// トークンは環境変数から読む（Actions では秘密の値から渡る）。Windows のユーザー環境変数は、それより前に起動したプロセスに
// 入らないので、無ければ登録簿から読む。
function userEnv(name) {
  if (process.env[name]) return process.env[name];
  if (process.platform !== "win32") throw new Error(`環境変数 ${name} が無い`);
  return new RegExp(`${name}\\s+REG_SZ\\s+(\\S+)`).exec(execFileSync("reg", ["query", "HKCU\\Environment", "/v", name], { encoding: "utf8" }))[1];
}
export const bot = () => new GitHub(userEnv("FLOW_BOT_TOKEN")); // 置き場へ書くのは hidakagit-bot だけ
export const code = () => new GitHub(userEnv("GH_TOKEN")); // コードのリポジトリ（hidakagit のもの）を読み、担当を起こす

// 引数を読む。usage は使い方の1行、ok は引数（--dry-run を除いたもの）が正しいか。正しくなければ使い方を出して終える。
export function args(usage, ok) {
  const all = process.argv.slice(2);
  const rest = all.filter((a) => a !== "--dry-run");
  if (!ok(rest)) {
    console.error(`使い方: ${usage}`);
    process.exit(2);
  }
  return { dry: all.includes("--dry-run"), rest };
}
export const isNumber = (s) => /^\d+$/.test(s ?? "");
