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
  /** モバイル上部の操作バー向け（改善計画T250）。座標を省いた1行表示にし、
   * 詳細はtitle属性（長押し/ホバー）へ退避する。狭い幅でも距離入力・生成ボタンと
   * 同じ行に収まる必要があるため。 */
  compact?: boolean;
  /** 改善計画T366: 出発地点を地図タップで手動指定するボタンの状態。目的地ボタン
   * （RouteForm.tsx）と同じ3状態循環（未指定→武装→指定済み、武装中はキャンセル可）。 */
  originState: OriginButtonState;
  onOriginButtonClick: () => void;
}

// 出発地点の表示＋改善計画T366の手動指定ボタンを持つ（緯度経度のテキスト入力欄自体は
// 改善計画T35で撤去済みのまま。現在地の再取得は地図上の「現在地に移動」ボタン、
// page.tsxのhandleLocateMeが担う）。
export default function LocationControl({
  location,
  source,
  compact = false,
  originState,
  onOriginButtonClick,
}: LocationControlProps) {
  const coords = `${location.latitude.toFixed(5)}, ${location.longitude.toFixed(5)}`;
  const originButtonLabel =
    originState === "manual"
      ? "現在地に戻す"
      : originState === "armed"
        ? "地図をタップして出発地点を指定（タップでキャンセル）"
        : "出発地点を指定（地図をタップ）";

  if (compact) {
    return (
      <span className="flex min-w-0 flex-1 items-center gap-1">
        <span
          className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-xs"
          title={`出発地点: ${SOURCE_LABEL[source]} (${coords})`}
        >
          出発: {SOURCE_LABEL[source]}
        </span>
        <Button
          type="button"
          variant={originState === "unset" ? "ghost" : "primary"}
          size="sm"
          className={`shrink-0 px-1.5 py-0.5 text-xs${originState === "armed" ? " animate-pulse" : ""}`}
          onClick={onOriginButtonClick}
          aria-label={originButtonLabel}
          title={originButtonLabel}
        >
          📍
        </Button>
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-2 text-[length:var(--font-size-md)]">
      {/* ルート生成の入力（周回の起点）であることが伝わるよう「位置情報」から言い換える（T30） */}
      <span>
        出発地点: {SOURCE_LABEL[source]}
        <br />
        {coords}
      </span>
      <Button
        type="button"
        variant={originState === "unset" ? "secondary" : "primary"}
        size="sm"
        className={`self-start${originState === "armed" ? " animate-pulse" : ""}`}
        onClick={onOriginButtonClick}
        aria-label={originButtonLabel}
      >
        📍 {originButtonLabel}
      </Button>
    </div>
  );
}
