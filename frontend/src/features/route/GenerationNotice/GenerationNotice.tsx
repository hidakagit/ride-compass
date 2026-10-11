import { Callout } from "@/components/ui/Callout/Callout";
import { GuideText } from "@/components/ui/GuideText/GuideText";
import type { GenerationNotice as Notice } from "@/features/route/useRouteGeneration";

// 押した「生成」が候補を出せなかった理由（入力の誤りか失敗・候補0件の理由）。「ルート結果」の中身とモバイルの「ルート設定」
// シートの見出しの下が同じ形で出す——別々に持つと、片方だけ文言の出し方や role が変わる。候補0件の理由も、どれも利用者に
// 地点や条件を変えさせる文なので、補足の文でなく枠で目に留める（失敗と見分けるため色を変える）。
export default function GenerationNotice({ notice }: { notice: Notice }) {
  const failed = notice.kind === "failed";
  return (
    <Callout role={failed ? "alert" : "status"} tone={failed ? "danger" : "warning"}>
      <GuideText text={notice.message} />
    </Callout>
  );
}
