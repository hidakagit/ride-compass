import base from "../flow.config.json" with { type: "json" };
import questionTemplate from "../question_template.md"; // wrangler.toml の rules で文字列として読む

export const config = { ...base, questionTemplate };
