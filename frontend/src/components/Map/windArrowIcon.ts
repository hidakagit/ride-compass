// 風の矢印アイコンのCanvas 2D描画。MapLibre/DOM（canvas要素の生成のみ）以外に依存しない
// 純粋な描画コードのため、MapView.tsx（地図の初期化・レイヤー登録・propsに専念する
// ファイル）から切り出した（描画スペック（DYNAMIC_WEATHER_RENDERERS）はMapView.tsxに
// 集約する契約だが、アイコンの中身をCanvas座標で描く幾何計算はその契約の対象外の
// 純粋関数であり、windLayer.ts等と同じ「DOM/MapLibre非依存のデータ/描画層」に属する）。

// 風の矢印は、バックエンドの格子点マップAPI（GET /api/weather/wind-grid、Open-Meteo
// REST地点評価と同じ仕組み）が返す風向・風速をMapLibre標準のGeoJSON source + symbol
// レイヤーで描画する。矢印アイコンは独自定義（createWindArrowIcon、白いシルエットを
// sdf:trueで登録しicon-colorで着色）で、向き（icon-rotate）・長さ+太さ（icon-size、
// アイコン全体を一様スケールするため両方同時に変わる）・色（icon-color、連続
// グラデーション）のすべてを風速から自由に設定できる。
const WIND_ARROW_SIZE_PX = 32;

interface Point2D {
  x: number;
  y: number;
}

function cubicBezierPoint(p0: Point2D, p1: Point2D, p2: Point2D, p3: Point2D, t: number): Point2D {
  const mt = 1 - t;
  return {
    x: mt * mt * mt * p0.x + 3 * mt * mt * t * p1.x + 3 * mt * t * t * p2.x + t * t * t * p3.x,
    y: mt * mt * mt * p0.y + 3 * mt * mt * t * p1.y + 3 * mt * t * t * p2.y + t * t * t * p3.y,
  };
}

/** 3次ベジェ曲線p0→p3ぶんの帯（先端に向けて太さがwidthStart→widthEndへ線形に変わる
 * リボン状の塗り）を描く。曲線の接線に垂直な方向へオフセットした左右の縁を辿って
 * 1つの閉じたパスにする（オフセット曲線の厳密解ではなく、区間を細かく刻んだ近似）。
 * 気流のストリームライン（下記createWindArrowIcon参照、風であることを地図上の
 * オブジェクトと区別して表現する意図）を描くための汎用ヘルパー。 */
function fillTaperedRibbon(
  ctx: CanvasRenderingContext2D,
  p0: Point2D,
  p1: Point2D,
  p2: Point2D,
  p3: Point2D,
  widthStart: number,
  widthEnd: number,
  steps = 12
) {
  const center = Array.from({ length: steps + 1 }, (_, i) => cubicBezierPoint(p0, p1, p2, p3, i / steps));
  const left: Point2D[] = [];
  const right: Point2D[] = [];
  for (let i = 0; i < center.length; i++) {
    const prev = center[Math.max(0, i - 1)];
    const next = center[Math.min(center.length - 1, i + 1)];
    const dx = next.x - prev.x;
    const dy = next.y - prev.y;
    const len = Math.hypot(dx, dy) || 1;
    // 接線に垂直な単位ベクトル（法線）。
    const nx = -dy / len;
    const ny = dx / len;
    const halfWidth = ((widthStart + (widthEnd - widthStart) * (i / steps)) / 2) || 0.001;
    left.push({ x: center[i].x + nx * halfWidth, y: center[i].y + ny * halfWidth });
    right.push({ x: center[i].x - nx * halfWidth, y: center[i].y - ny * halfWidth });
  }
  ctx.beginPath();
  ctx.moveTo(left[0].x, left[0].y);
  for (const p of left.slice(1)) ctx.lineTo(p.x, p.y);
  for (const p of right.slice().reverse()) ctx.lineTo(p.x, p.y);
  ctx.closePath();
  ctx.fill();
}

// 風チップボタン（icons.tsx: WindIcon、渦を巻く3本の曲線）と同じ「曲線=風」という
// 視覚言語を地図上でも踏襲する（旧デザインは直方体の軸+三角の矢じりという直線的な形で、
// 道路標識のような「硬い」印象だった）。道路・POI等の地図上オブジェクトのアイコン
// （icons.tsx）は直線・単純な多角形が主体のため、曲線を基調にするだけでも見分けがつきやすい。
export function createWindArrowIcon(): ImageData {
  const canvas = document.createElement("canvas");
  canvas.width = WIND_ARROW_SIZE_PX;
  canvas.height = WIND_ARROW_SIZE_PX;
  const ctx = canvas.getContext("2d");
  if (!ctx) return new ImageData(WIND_ARROW_SIZE_PX, WIND_ARROW_SIZE_PX);
  ctx.fillStyle = "#ffffff";

  // 北（画像上方向）を向くアイコンとして描き、実際の向きはicon-rotate（風向から計算した
  // bearing、windLayer.ts参照）で回転させる。

  // 主流線: 緩やかなS字を描きながら下（尾）から上（矢じりの根元）へ伸びる帯。
  // 尾は太く、矢じりに近づくほど細くなる（風上から風下へ流れていく感覚を出す）。
  fillTaperedRibbon(ctx, { x: 16, y: 29 }, { x: 12, y: 21 }, { x: 19, y: 15 }, { x: 16, y: 11 }, 5, 2, 14);

  // 左右の副流線（風チップのWindIconと同じ「複数の曲線が寄り添う」構図）。主流線より
  // 細く短く、主流線に沿うように少しずれた位置を並走させ、単なる矢印ではなく
  // 「複数の気流が束になって流れている」印象を加える。
  fillTaperedRibbon(ctx, { x: 9, y: 27 }, { x: 7, y: 22 }, { x: 9, y: 18 }, { x: 11.5, y: 15 }, 1.6, 0.2, 10);
  fillTaperedRibbon(ctx, { x: 23, y: 27 }, { x: 25, y: 22 }, { x: 23, y: 18 }, { x: 20.5, y: 15 }, 1.6, 0.2, 10);

  // 矢じり（先端が尖った細身の三角形。旧デザインより幅を絞り、流線の延長として
  // 自然に繋がるようにしている）。
  ctx.beginPath();
  ctx.moveTo(16, 2);
  ctx.lineTo(21, 12.5);
  ctx.lineTo(16, 10);
  ctx.lineTo(11, 12.5);
  ctx.closePath();
  ctx.fill();

  return ctx.getImageData(0, 0, WIND_ARROW_SIZE_PX, WIND_ARROW_SIZE_PX);
}
