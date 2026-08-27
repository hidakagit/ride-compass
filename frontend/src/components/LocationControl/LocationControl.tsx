"use client";

import { Button } from "@/components/ui/Button/Button";
import type { Coordinates, LocationSource } from "@/types/route";

const SOURCE_LABEL: Record<LocationSource, string> = {
  geolocation: "現在地[取得済み]",
  // 「デフォルト」は開発用語のため、初見でも意味が取れる表現にする（T30）
  default: "初期地点[東京・王子]",
  // 改善計画T366: 地図タップで手動指定した出発地点。
  manual: "指定地点",
};

export type OriginButtonState = "unset" | "armed" | "manual";

interface LocationControlProps {
  location: Coordinates;
  source: LocationSource;
  /** 改善計画T366: 出発地点を地図タップで手動指定するボタンの状態。目的地ボタン
   * （RouteForm.tsx）と同じ3状態循環（未指定→武装→指定済み、武装中はキャンセル可）。 */
  originState: OriginButtonState;
  onOriginButtonClick: () => void;
}

// 改善計画T368（実機フィードバック「出発・現在地の文字表示は何のために出すのか」
// 「起点位置はピンで視覚的に分かる、GPS取得失敗かどうかはピンの色で区別すればよい」を
// 受けた再設計）: 「出発地点: …」の常時表示テキスト＋緯度経度は撤去した。出発地点が
// GPS取得済みか・取得失敗時のフォールバック（初期地点）かはMapView.tsxの現在地マーカーの
// 色（赤/グレー）で伝える。このコンポーネントは出発地点を手動指定するアイコンボタン
// （改善計画T366）1つだけを持ち、状態の説明はaria-label/titleに退避する
// （ボタン自体は常時表示だが、文言は明示的に読みにいったときだけ見える）。
export default function LocationControl({ location, source, originState, onOriginButtonClick }: LocationControlProps) {
  const coords = `${location.latitude.toFixed(5)}, ${location.longitude.toFixed(5)}`;
  const originButtonLabel =
    originState === "manual"
      ? `現在地に戻す（現在の出発地点: ${SOURCE_LABEL[source]} ${coords}）`
      : originState === "armed"
        ? "地図をタップして出発地点を指定（タップでキャンセル）"
        : `出発地点を指定（現在: ${SOURCE_LABEL[source]} ${coords}）`;

  return (
    <Button
      type="button"
      variant={originState === "unset" ? "ghost" : "primary"}
      size="sm"
      className={originState === "armed" ? "shrink-0 animate-pulse" : "shrink-0"}
      onClick={onOriginButtonClick}
      aria-label={originButtonLabel}
      title={originButtonLabel}
    >
      📍
    </Button>
  );
}
