// トークンは環境変数から読む（GitHub Actions ではリポジトリの秘密の値から渡る）。Windows のユーザー環境変数は、
// それより前に起動したプロセスの環境には入らないので、無ければ登録簿から読む。
import { execFileSync } from "node:child_process";

function userEnv(name) {
  if (process.env[name]) return process.env[name];
  if (process.platform !== "win32") throw new Error(`環境変数 ${name} が無い`);
  const out = execFileSync("reg", ["query", "HKCU\\Environment", "/v", name], { encoding: "utf8" });
  return new RegExp(`${name}\\s+REG_SZ\\s+(\\S+)`).exec(out)[1];
}

// hidakagit-bot のトークン。タスクの置き場へ書くのはこれだけ。
export const botToken = () => userEnv("FLOW_BOT_TOKEN");

// hidakagit のトークン。コードのリポジトリ（hidakagit のもの）の Pull Request を読むのに使う。
export const codeToken = () => userEnv("GH_TOKEN");
