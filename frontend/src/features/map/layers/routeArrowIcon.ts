import { drawSdfIcon } from "@/features/map/layers/sdfIcon";

/** 地図へ登録する名前。**登録側と参照側が同じ1つを使う**（綴りがずれると矢印が出ない）。 */
export const ROUTE_ARROW_ICON_ID = "route-arrow-icon";

// 周回ルートの採用向き（順回り/逆回り）を示す矢印アイコン。道路網に重ねる進行方向の印なので、
// 単純な三角形の矢じり（シェブロン）にして地図上のオブジェクトとしての硬さ・視認性を優先する。
//
// symbol-placement: "line"時は、icon-rotateを指定しなくてもicon-rotation-alignment: "map"が
// 線分の向きへ自動的に回転させる（features/map/scene/groups/routes.tsの役割`arrow`）。
// この自動回転の基準（未回転のアイコンがどちらを向いていれば線の進行方向と一致するか）は
// 東（画像の右方向）なので、このアイコンは右（東）を向くシェブロンとして描く。
const ROUTE_ARROW_SIZE_PX = 20;

/** 右（東）を向くシンプルな矢じり（シェブロン、"❯"のような形）。中心の水平線に対して
 * 上下対称。sdf:true登録前提の単色シルエットのため、塗り色自体に意味はない。 */
export function createRouteArrowIcon(): ImageData {
  const cx = ROUTE_ARROW_SIZE_PX / 2;
  const cy = ROUTE_ARROW_SIZE_PX / 2;
  const tipX = cx + 7;
  const tailX = cx - 7;
  return drawSdfIcon(ROUTE_ARROW_SIZE_PX, (ctx) => {
    ctx.beginPath();
    ctx.moveTo(tipX, cy);
    ctx.lineTo(tailX, cy - 6);
    ctx.lineTo(tailX + 3.5, cy);
    ctx.lineTo(tailX, cy + 6);
    ctx.closePath();
    ctx.fill();
  });
}
