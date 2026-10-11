import { GuideText } from "@/components/ui/GuideText/GuideText";
import { textVariants } from "@/components/ui/Text/Text";
import ErrorText from "@/features/route/ErrorText/ErrorText";
import type { GenerationNotice as Notice } from "@/features/route/useRouteGeneration";

// 押した「生成」が候補を出せなかった理由（入力の誤りか失敗・候補0件の理由）。「ルート結果」の中身とモバイルの「ルート設定」
// シートの見出しの下が同じ形で出す——別々に持つと、片方だけ文言の出し方や role が変わる。
export default function GenerationNotice({ notice }: { notice: Notice }) {
  if (notice.kind === "failed") {
    return (
      <ErrorText>
        <GuideText text={notice.message} />
      </ErrorText>
    );
  }
  return (
    <p role="status" className={textVariants({ variant: "hint" })}>
      {notice.message}
    </p>
  );
}
