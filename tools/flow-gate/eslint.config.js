// 道具と部品の静的な誤り（構文・存在しない import・無い名前の import）を動かさずに落とす。
// 規則はプラグインの errors（実行すれば必ず落ちるものだけを集めた既定の組）をそのまま使う。
import importPlugin from "eslint-plugin-import";

// cloudflare: で始まる import は Workers の実行環境が持つ組み込みで、手元のファイルには無い。
export default [importPlugin.flatConfigs.errors, { rules: { "import/no-unresolved": ["error", { ignore: ["^cloudflare:"] }] } }];
