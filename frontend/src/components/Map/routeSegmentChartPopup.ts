// ルート線専用のクリック内訳ポップアップ（改善計画T403、T400.md「3. ルートクリック内訳の
// 拡張」からの分割）。一般道路網向けのaxisInspectorPopup.ts（クリックの都度
// POST /api/region/axis-inspectorをサーバーへ投げ、ルート文脈が無いため勾配・風が
// 「算出不可」になる）とは完全に独立した別経路。ルート線のfeature.properties
// （RouteSegmentDetail、MapView.tsx: segmentsToFeatureCollectionが焼き込み済み）は
// ルート生成時点で実進行方向・推定到達時刻を使って既に計算済みのため、この
// モジュールはサーバーへ一切問い合わせず、渡された値をそのままHTML文字列へ組み立てるだけの
// 純粋関数だけで構成する（axisInspectorPopup.tsのようなfetch・ボタンの後付けハンドラは不要）。
//
// 表示形式はテキストの箇条書きではなく小型のレーダーチャート（ユーザー指定、T400.md）。
// 軸数（現状8、車の圧迫感・停止密度・事故密度・夜間・舗装質・自転車インフラ・勾配・風）が
// 独立した0-100の難易度スコアを持つ構造は、合計が100%になる構成比ではなく「多軸の
// 相対的な高低パターンを一目で見る」ことに向いているため、ドーナツ（構成比表現）ではなく
// レーダー（多軸プロット）を選んだ。ライブラリはpackage.jsonを確認した上で採用を見送った
// （既存のチャート専用ライブラリは無く、既存のMap関連コード自体がicons.tsx・
// windArrowIcon.ts・axisInspectorPopup.ts等、すべて手書きSVG/DOM文字列で完結しており、
// 8頂点程度の単純な多角形描画のために新規依存を増やすメリットが薄いと判断した）。
//
// 色は軸ラベル（useAxisCatalog経由のaxisLabels、軸スタジオの公開軸増減に自動追従）・
// 統一パレット（axisLayers.ts: rampColorForValue、地図のramp軸と同じ緑→黄→橙→赤の
// 連続スケール）を使い、地図上の色分けと同じ「低=緑・高=赤」という読み方をここでも
// 維持する。

import type { RouteSegmentDetail } from "@/types/route";
import { rampColorForValue } from "./axisLayers";

/** feature.propertiesの実体（MapView.tsx: RouteSegmentPropertiesと同じ形）。
 * MapView.tsxから型をimportすると、MapView.tsx側は逆にこのモジュールの関数を呼ぶため
 * 循環importになる。どちらも同じ`Omit<RouteSegmentDetail, "geometry">`という単純な形の
 * ため、生成元の型（@/types/route）から直接同じ形を導出することで循環を避ける。 */
export type RouteSegmentChartSegment = Omit<RouteSegmentDetail, "geometry">;

interface RadarEntry {
  axisId: string;
  label: string;
  value: number;
}

function formatTimeLabel(iso: string | null): string {
  if (!iso) return "不明";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "不明";
  return date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

function formatGradientLabel(percent: number | null): string {
  return percent != null ? `${percent.toFixed(1)}%` : "不明";
}

function formatWindLabel(penalty: number | null): string {
  if (penalty == null) return "データなし";
  const label = penalty >= 0 ? "向かい風" : "追い風";
  return `${label} ${Math.abs(penalty).toFixed(1)} m/s`;
}

function formatRoadLabel(good: boolean | null): string {
  if (good == null) return "不明";
  return good ? "舗装路" : "未舗装路";
}

function formatDifficultyValue(value: number): string {
  return `${value.toFixed(1)}/100`;
}

// レーダーチャートの寸法。ポップアップの標準幅（MapLibre Popupの既定maxWidth=240px）に
// 収まる「小型チャート」（T400.md指定）として設計している。
// ユーザー指摘（2026-09-03、「情報量の割に大きすぎる、スマホだと見切れて使いにくい」）:
// 以前は176px四方＋凡例8行（公開軸数ぶん）を縦一列で並べており、合計の縦幅がモバイルの
// 画面高さを超えて見切れていた。チャート自体を132px四方へ縮小し、凡例を2列グリッド化
// （buildLegendRows参照）して縦幅をさらに圧縮する。
const RADAR_SIZE = 132;
const RADAR_CENTER = RADAR_SIZE / 2;
const RADAR_MAX_RADIUS = 49;
// 背景の同心グリッド（25/50/75/100%の目盛り）。値そのものの目盛り数値は出さず
// （小型チャートに数値を詰め込むと読みにくくなるため）、下の凡例リストで正確な値を確認する
// 二段構成にしている。
const RADAR_RING_RATIOS = [0.25, 0.5, 0.75, 1];

function radarPoint(angle: number, radius: number): [number, number] {
  return [RADAR_CENTER + radius * Math.cos(angle), RADAR_CENTER + radius * Math.sin(angle)];
}

function polygonPoints(points: readonly (readonly [number, number])[]): string {
  return points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
}

/** entries（軸id・ラベル・0-100難易度）からレーダーチャートのSVG文字列を組み立てる。
 * 3軸未満は多角形として意味を持たない（線・点に潰れる）ため、呼び出し側
 * （buildRouteSegmentChartPopupHtml）でその場合はこの関数を使わず凡例リストのみへ
 * フォールバックする。改善計画T466: exportされた公開関数のため、呼び出し側の判定漏れ・
 * 直接呼び出しでも同じ不変条件（3軸以上）を自前で守るガードをここにも持つ
 * （n=0だとangleStep=2π/0=Infinityになり得点が全て原点へ潰れる、n<3だと多角形として
 * 破綻する）。 */
export function buildAxisDifficultyRadarSvg(entries: readonly RadarEntry[]): string {
  if (entries.length < 3) return "";
  const n = entries.length;
  const angleStep = (2 * Math.PI) / n;
  const angleAt = (i: number) => -Math.PI / 2 + i * angleStep;

  const rings = RADAR_RING_RATIOS.map((ratio) => {
    const points = entries.map((_, i) => radarPoint(angleAt(i), RADAR_MAX_RADIUS * ratio));
    return `<polygon points="${polygonPoints(points)}" fill="none" stroke="var(--color-border)" stroke-width="1"/>`;
  }).join("");

  const spokes = entries
    .map((_, i) => {
      const [x, y] = radarPoint(angleAt(i), RADAR_MAX_RADIUS);
      return `<line x1="${RADAR_CENTER}" y1="${RADAR_CENTER}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(--color-border)" stroke-width="1"/>`;
    })
    .join("");

  const dataPoints = entries.map((entry, i) =>
    radarPoint(angleAt(i), (Math.min(100, Math.max(0, entry.value)) / 100) * RADAR_MAX_RADIUS)
  );
  const dataPolygon = `<polygon points="${polygonPoints(dataPoints)}" fill="rgba(37,99,235,0.25)" stroke="#2563eb" stroke-width="2"/>`;

  // 頂点の色だけは軸ごとの難易度（rampColorForValue、統一パレット）で塗り分ける。
  // 多角形本体（dataPolygon）は単色にしているのは、頂点間の辺をグラデーションにすると
  // 「隣同士の軸の間に何か意味のある傾き」があるように誤読されうるため（軸の並び順に
  // 連続的な意味は無い）、値の高低は頂点の色と半径の両方で示すに留める。
  const dots = entries
    .map((entry, i) => {
      const [x, y] = dataPoints[i];
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="${rampColorForValue(entry.value)}" stroke="#fff" stroke-width="1"/>`;
    })
    .join("");

  return `<svg viewBox="0 0 ${RADAR_SIZE} ${RADAR_SIZE}" width="${RADAR_SIZE}" height="${RADAR_SIZE}" role="img" aria-label="軸別難易度のレーダーチャート">${rings}${spokes}${dataPolygon}${dots}</svg>`;
}

function buildLegendRows(entries: readonly RadarEntry[]): string {
  return entries
    .map(
      (entry) => `<div style="display:flex; align-items:center; gap:4px; font-size:var(--font-size-sm); min-width:0;">
        <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${rampColorForValue(entry.value)}; flex:none;"></span>
        <span style="flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${entry.label}</span>
        <span style="color:var(--color-muted); flex:none;">${formatDifficultyValue(entry.value)}</span>
      </div>`
    )
    .join("");
}

const POPUP_BODY_STYLE = "font-size:var(--font-size-md); line-height:1.4;";

/** ルート線クリック時のポップアップ本体（改善計画T403）。segmentは既にフェッチ済みの
 * RouteSegmentDetail（geometryを除いたfeature.properties）で、サーバーへの新規リクエストは
 * 一切発生しない。axisLabelsは呼び出し側（MapView.tsx）がuseAxisCatalog経由で渡す実行時の
 * axis_id→表示名辞書（axisInspectorPopup.tsと同じ理由で、軸スタジオの公開軸増減に
 * 再デプロイなしで追従するため）。 */
export function buildRouteSegmentChartPopupHtml(
  segment: RouteSegmentChartSegment,
  axisLabels: Record<string, string>
): string {
  // ユーザー指摘（2026-09-03）: 以前はaxisLabelsに無いaxis_idも生のaxis_idのまま表示していた
  // （改善計画T320の「ラベル未取得でも隠さず出す」規約）が、RouteAxisProfile側の「地図の
  // 色分け」チップ列・内訳は現在の公開軸カタログ（axisLabels、GET /api/axis-catalog由来、
  // 公開軸のみ）に無い軸を表示しない設計のため、こちらだけ軸が多く見える不整合になっていた。
  // ルート結果の他UIと同じ基準（axisLabelsにある＝現在の公開軸）へ揃え、無い軸は除外する。
  const entries: RadarEntry[] = Object.entries(segment.axis_difficulties ?? {})
    .filter(([axisId]) => axisId in axisLabels)
    .map(([axisId, value]) => ({
      axisId,
      label: axisLabels[axisId],
      value,
    }));

  // ユーザー指摘（2026-09-03）: 縦一列（公開軸数ぶんの行数）だと軸が増えるほど縦に伸び続ける。
  // 2列グリッド化して同じ情報量でも縦幅を概ね半分にする。
  const legendHtml =
    entries.length > 0
      ? `<div style="display:grid; grid-template-columns:1fr 1fr; gap:2px 8px; margin-top:var(--space-1);">${buildLegendRows(entries)}</div>`
      : "";

  const chartSection =
    entries.length >= 3
      ? `<div style="margin-top:var(--space-1); text-align:center;">${buildAxisDifficultyRadarSvg(entries)}</div>${legendHtml}`
      : entries.length > 0
        ? legendHtml
        : `<div style="font-size:var(--font-size-sm); color:var(--color-muted); margin-top:var(--space-1);">軸別の内訳を算出できませんでした。</div>`;

  // ユーザー指摘（2026-09-03、「スマホだと見切れて使いにくい」）: チャート縮小・凡例の
  // 2列化だけでは、将来公開軸数が増えた場合に再び縦幅が伸びうる。MapLibre Popupは既定で
  // 内部スクロールを持たないため、画面高さに対する上限（60vh）とoverflow-y:autoを
  // 常に持たせ、どれだけ軸数が増えてもポップアップ自体が画面からはみ出さないようにする
  // （軸数に依存しない一般的な対策）。
  return `<div style="${POPUP_BODY_STYLE} max-height:60vh; overflow-y:auto;">
    <strong>${segment.cumulative_distance_km.toFixed(1)} km地点</strong>[到達予想 ${formatTimeLabel(segment.estimated_arrival_time)}]<br/>
    勾配: ${formatGradientLabel(segment.gradient_percent)}｜風: ${formatWindLabel(segment.wind_penalty)}｜路面: ${formatRoadLabel(segment.road_surface_good)}
    <div style="border-top:1px solid var(--color-border); margin-top:var(--space-1); padding-top:var(--space-1);">
      <strong style="font-size:var(--font-size-sm);">軸別の内訳</strong>
      ${chartSection}
    </div>
  </div>`;
}
