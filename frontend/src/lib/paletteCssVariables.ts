import palette from "@/types/generated/palette.json";

/** 地図に塗る色と同じものをUIにも出す箇所へ、配信された値をCSS変数として流す。
 *
 * **CSSが値を持つのは、ライト/ダークで2つの値を持つものだけ**（切り替えるのは媒体側で、
 * 配信された1つの値では表せない）。地図のキャンバスはテーマに追従しないので、そこへ塗る
 * 色は配信された値そのものになる——同じ色をCSSにも書くと、片方だけ動いたときに地図と
 * パネルで違う色が同じものを指す。
 */
const CSS_VARIABLES: Readonly<Record<string, string>> = {
  "--color-route-splice": palette.semantic.route_splice,
};

/** `<style>`へ入れる`:root`宣言。サーバー側で描くので、切り替わりが画面に出ない。 */
export function paletteCssText(): string {
  const body = Object.entries(CSS_VARIABLES)
    .map(([name, value]) => `${name}:${value};`)
    .join("");
  return `:root{${body}}`;
}
