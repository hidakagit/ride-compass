"use client";

import { useState } from "react";
import ErrorText from "@/components/ErrorText/ErrorText";
import styles from "./RouteForm.module.css";

interface RouteFormProps {
  /** 距離入力の現在値（文字列のまま）。生成条件のdirty判定（page.tsx）に使うため親が持つ */
  distance: string;
  onDistanceChange: (value: string) => void;
  onGenerate: (distanceKm: number) => void;
  loading: boolean;
}

// backend/app/api/routes.pyのRouteGenerateRequest.distance_km（Field(gt=0, le=100)）と一致させる。
const MAX_DISTANCE_KM = 100;

export default function RouteForm({ distance, onDistanceChange, onGenerate, loading }: RouteFormProps) {
  const [error, setError] = useState<string | null>(null);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
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

  return (
    // ブラウザ既定のnumber input制約検証(既定ロケールの英語ツールチップ)が、下の独自の
    // 日本語エラー表示より先にフォーム送信をブロックしてしまい、アプリ内の他のエラー表示と
    // 一貫しないUXになるのを避けるためnoValidateにし、検証は下のJSロジックに一本化する。
    <form onSubmit={handleSubmit} className={styles.form} noValidate>
      <label>
        距離
        <input
          type="number"
          min="1"
          max={MAX_DISTANCE_KM}
          step="1"
          value={distance}
          onChange={(e) => onDistanceChange(e.target.value)}
          className={styles.distanceInput}
        />
        km
      </label>
      <button type="submit" disabled={loading}>
        {loading ? "生成中..." : "ルート生成"}
      </button>
      {error && <ErrorText>{error}</ErrorText>}
    </form>
  );
}
