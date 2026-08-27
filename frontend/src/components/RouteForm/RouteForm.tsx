"use client";

import { useState } from "react";
import ErrorText from "@/components/ErrorText/ErrorText";
import { Button } from "@/components/ui/Button/Button";
import { Input } from "@/components/ui/Input/Input";
import styles from "./RouteForm.module.css";

export type RouteMode = "loop" | "destination";
export type DestinationButtonState = "unset" | "armed" | "set";

interface RouteFormProps {
  /** 距離入力の現在値（文字列のまま）。生成条件のdirty判定（page.tsx）に使うため親が持つ */
  distance: string;
  onDistanceChange: (value: string) => void;
  onGenerate: (distanceKm: number) => void;
  loading: boolean;
  /** 改善計画T265: 生成中(loading)のボタン文言を差し替える（例:「生成中...(12秒経過)」
   * 「順番待ち...」）。未指定時は従来どおり「生成中...」/「…」（compact時）を使う。 */
  progressLabel?: string;
  /** モバイル上部の操作バー向け（改善計画T250）。出発地点・生成ボタンと同じ行に収める
   * ため、ラベル文言を削って幅を詰める（アクセシブルネームはaria-labelで維持）。 */
  compact?: boolean;
  /** 改善計画T365-2: 周回（距離指定）/目的地（経由地・目的地を地図で指定）モードの切り替え。
   * 実機フィードバック「経由地・目的地の操作パネルが地図上で邪魔」を受け、地図上の浮動
   * パネルを廃止しこのフォーム内（距離入力・生成ボタンと同じ場所）へ統合した。 */
  routeMode: RouteMode;
  onRouteModeChange: (mode: RouteMode) => void;
  waypointCount: number;
  onWaypointsClear: () => void;
  destinationState: DestinationButtonState;
  onDestinationButtonClick: () => void;
}

// backend/app/api/routes.pyのRouteGenerateRequest.distance_km（Field(gt=0, le=100)）と一致させる。
const MAX_DISTANCE_KM = 100;

export default function RouteForm({
  distance,
  onDistanceChange,
  onGenerate,
  loading,
  progressLabel,
  compact = false,
  routeMode,
  onRouteModeChange,
  waypointCount,
  onWaypointsClear,
  destinationState,
  onDestinationButtonClick,
}: RouteFormProps) {
  const [error, setError] = useState<string | null>(null);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (routeMode === "destination") {
      // 目的地モードは距離を入力させない（page.tsx側が地図上の指定点から自動算出する、
      // handleGenerate参照）。代わりに経由地・目的地のいずれも未指定のサイレント失敗を防ぐ。
      if (waypointCount === 0 && destinationState !== "set") {
        setError("地図をタップして目的地か経由地を指定してください。");
        return;
      }
      setError(null);
      onGenerate(0);
      return;
    }
    const value = Number(distance);
    // 以前はvalue<=0のとき何も表示せずreturnするだけで、ユーザーには何も起きていないように
    // 見えるサイレント失敗になっていた。
    if (distance.trim() === "" || Number.isNaN(value)) {
      setError("距離は数値で入力してください。");
      return;
    }
    if (value <= 0) {
      setError("距離は0より大きい値を入力してください。");
      return;
    }
    if (value > MAX_DISTANCE_KM) {
      setError(`距離は${MAX_DISTANCE_KM}km以下で入力してください。`);
      return;
    }
    setError(null);
    onGenerate(value);
  }

  const destinationButtonLabel =
    destinationState === "set"
      ? "目的地を解除"
      : destinationState === "armed"
        ? "地図をタップして目的地を指定（タップでキャンセル）"
        : "目的地を設定（地図をタップ）";
  const destinationButtonClassName =
    destinationState === "set"
      ? styles.destinationChipSet
      : destinationState === "armed"
        ? styles.destinationChipArmed
        : styles.destinationChip;

  return (
    // ブラウザ既定のnumber input制約検証(既定ロケールの英語ツールチップ)が、下の独自の
    // 日本語エラー表示より先にフォーム送信をブロックしてしまい、アプリ内の他のエラー表示と
    // 一貫しないUXになるのを避けるためnoValidateにし、検証は下のJSロジックに一本化する。
    <form onSubmit={handleSubmit} className={compact ? styles.formCompact : styles.form} noValidate>
      <div className={styles.modeToggle} role="group" aria-label="ルート生成モード">
        <button
          type="button"
          onClick={() => onRouteModeChange("loop")}
          aria-pressed={routeMode === "loop"}
          className={routeMode === "loop" ? styles.modeButtonActive : styles.modeButton}
        >
          周回
        </button>
        <button
          type="button"
          onClick={() => onRouteModeChange("destination")}
          aria-pressed={routeMode === "destination"}
          className={routeMode === "destination" ? styles.modeButtonActive : styles.modeButton}
        >
          目的地
        </button>
      </div>

      {routeMode === "loop" ? (
        <label className={compact ? styles.labelCompact : undefined}>
          {!compact && "距離"}
          <Input
            type="number"
            min="1"
            max={MAX_DISTANCE_KM}
            step="1"
            value={distance}
            onChange={(e) => onDistanceChange(e.target.value)}
            className={compact ? "w-14" : "ml-2 w-20"}
            aria-label={compact ? "距離(km)" : undefined}
          />
          km
        </label>
      ) : (
        <div className={styles.destinationSummary}>
          {waypointCount > 0 && (
            <span className={styles.summaryChip}>
              📍{waypointCount}
              <button type="button" onClick={onWaypointsClear} aria-label="経由地をクリア">
                ✕
              </button>
            </span>
          )}
          <button
            type="button"
            onClick={onDestinationButtonClick}
            aria-label={destinationButtonLabel}
            title={destinationButtonLabel}
            className={destinationButtonClassName}
          >
            🏁
          </button>
        </div>
      )}

      <Button variant="primary" type="submit" disabled={loading}>
        {loading ? (compact ? "…" : (progressLabel ?? "生成中...")) : compact ? "生成" : "ルート生成"}
      </Button>
      {error && <ErrorText>{error}</ErrorText>}
    </form>
  );
}
