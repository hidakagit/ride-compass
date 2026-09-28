// トークンはユーザー環境変数から読む。Windows のユーザー環境変数は、それより前に起動したプロセスの環境には入らないので、
// 無ければ登録簿から読む。
import { execFileSync } from "node:child_process";

export function userEnv(name) {
  if (process.env[name]) return process.env[name];
  const out = execFileSync("reg", ["query", "HKCU\\Environment", "/v", name], { encoding: "utf8" });
  return new RegExp(`${name}\\s+REG_SZ\\s+(\\S+)`).exec(out)[1];
}

// hidakagit-bot のトークン。タスクの置き場へ書くのはこれだけ。
export const botToken = () => userEnv("FLOW_BOT_TOKEN");
