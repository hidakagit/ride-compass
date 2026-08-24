// 周回ルートの採用向き（順回り/逆回り）を示す矢印アイコンのCanvas 2D描画（改善計画T293）。
// windArrowIcon.tsと同じCanvas 2D + sdf:true登録パターンを流用するが、意匠は異なる:
// 風は「曲線=気流」という視覚言語（windArrowIcon.ts参照）だが、ルート矢印は道路網に重ねる
// 進行方向インジケータのため、単純な三角形の矢じり（シェブロン）にして地図上オブジェクトと
// しての硬さ・視認性を優先する。
//
// symbol-placement: "line"時は、icon-rotateを指定しなくてもicon-rotation-alignment: "map"が
// 線分の向きへ自動的に回転させる（MapView.tsx: ensureRouteArrowLayer参照、T293技術検証
// Artifactで確認済み）。この自動回転の基準（rotate=0の未回転時にアイコンがどちらを向いて
// いれば線の進行方向と一致するか）は、風の矢印（北=画像の上方向を基準にicon-rotateへ
// 明示的な角度を渡す、windArrowIcon.ts参照）とは異なり、東（画像の右方向）が基準となる。
// そのため、このアイコンは右（東）を向くシェブロンとして描く。
const ROUTE_ARROW_SIZE_PX = 20;

/** 右（東）を向くシンプルな矢じり（シェブロン、"❯"のような形）。中心の水平線に対して
 * 上下対称。sdf:true登録前提の単色シルエットのため、塗り色自体に意味はない。 */
export function createRouteArrowIcon(): ImageData {
  const canvas = document.createElement("canvas");
  canvas.width = ROUTE_ARROW_SIZE_PX;
  canvas.height = ROUTE_ARROW_SIZE_PX;
  const ctx = canvas.getContext("2d");
  if (!ctx) return new ImageData(ROUTE_ARROW_SIZE_PX, ROUTE_ARROW_SIZE_PX);
  ctx.fillStyle = "#ffffff";

  const cx = ROUTE_ARROW_SIZE_PX / 2;
  const cy = ROUTE_ARROW_SIZE_PX / 2;
  const tipX = cx + 7;
  const tailX = cx - 7;
  ctx.beginPath();
  ctx.moveTo(tipX, cy);
  ctx.lineTo(tailX, cy - 6);
  ctx.lineTo(tailX + 3.5, cy);
  ctx.lineTo(tailX, cy + 6);
  ctx.closePath();
  ctx.fill();

  return ctx.getImageData(0, 0, ROUTE_ARROW_SIZE_PX, ROUTE_ARROW_SIZE_PX);
}
