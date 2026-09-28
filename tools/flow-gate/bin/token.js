// hidakagit-bot のトークン。Windows のユーザー環境変数は、それより前に起動したプロセスの環境には入らないので、
// 無ければ登録簿から読む。
import { execFileSync } from "node:child_process";

export function botToken() {
  if (process.env.FLOW_BOT_TOKEN) return process.env.FLOW_BOT_TOKEN;
  const out = execFileSync("reg", ["query", "HKCU\\Environment", "/v", "FLOW_BOT_TOKEN"], { encoding: "utf8" });
  return /FLOW_BOT_TOKEN\s+REG_SZ\s+(\S+)/.exec(out)[1];
}
