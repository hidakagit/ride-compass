"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button/Button";
import { Card } from "@/components/ui/Card/Card";
import { refreshTileCache } from "@/services/basemapAdminApi";
import styles from "./TileCachePanel.module.css";

// 「鮮度」タブ（/admin）から、サーバー側のタイルファイルキャッシュを全消去するパネル。
// 隣のDerivedDataFreshnessPanelが「古いかどうかを見る」のに対し、こちらは「古いものを
// 捨てる」操作側。全利用者へ影響するためBasic認証の内側（/admin）にだけ置く。
export default function TileCachePanel() {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [running, setRunning] = useState(false);

  const handleClear = () => {
    setRunning(true);
    setError(null);
    setDone(false);
    refreshTileCache()
      .then(() => setDone(true))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setRunning(false));
  };

  return (
    <Card className={styles.panel}>
      <div className={styles.heading}>タイルキャッシュの消去</div>
      <p className={styles.hint}>
        サーバーが持つタイルのファイルキャッシュを全て消す。基礎地図（OpenFreeMap中継）と
        路面・事故・POIのベクタタイルは同じキャッシュを共有するため、まとめて消える。
        影響は押した人だけでなく全利用者に及び、次のタイル要求で作り直されるまでは
        外部サービスへの実問い合わせやタイル生成が走る。押しても管理者自身の画面は変わらない
        （この画面は地図を持たない）。
      </p>
      <p className={styles.hint}>
        各利用者の画面へ反映されるのは、ブラウザが持つ既存タイルのCache-Controlが切れた後
        （基礎地図は最大10分）。取込バッチや軸の変更を本番へ反映した直後など、
        古いタイルを掴ませたくないときに使う。
      </p>
      <div className={styles.controls}>
        <Button onClick={handleClear} disabled={running}>
          {running ? "消去中…" : "タイルキャッシュを消去する"}
        </Button>
      </div>
      {error && <p className={styles.error}>{error}</p>}
      {done && !error && (
        <p className={styles.summary}>
          消去しました。各利用者の表示へは次回のタイル取得時、遅くとも既存タイルの
          Cache-Control（基礎地図は10分）が切れた時点で反映されます。
        </p>
      )}
    </Card>
  );
}
