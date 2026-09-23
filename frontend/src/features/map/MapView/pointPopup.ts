// 点データ（事故・POI）のクリックポップアップの本文。
// 値はOSMタグ由来で第三者が編集できるため、HTML文字列を経由せずテキストノードで組む
// （`Popup.setHTML()`はサニタイズしない。docs/modules/frontend/static-map-layers.md参照）。

// line-height 1.4はサイドバーの他カード（components/ui/Card等）に近い密度に合わせている。
const POPUP_BODY_STYLE = "font-size:var(--font-size-md); line-height:1.4;";

// 外部静的データソース（警察庁交通事故統計）のクリックポップアップ用プロパティ。
export interface AccidentPopupProperties {
  fatal?: boolean | null;
  involves_bicycle?: boolean | null;
  occurred_year?: number | null;
}

// 停止要因POI・補給休憩POIのクリックポップアップ用プロパティは同じ形（{kind}）で、
// ラベル辞書とprefix文言が違うだけのため、1つの関数で組む。
export interface PoiPopupProperties {
  kind?: string | null;
}

function popupBody(lines: readonly string[]): HTMLDivElement {
  const body = document.createElement("div");
  body.style.cssText = POPUP_BODY_STYLE;
  lines.forEach((line, i) => {
    if (i > 0) body.appendChild(document.createElement("br"));
    body.appendChild(document.createTextNode(line));
  });
  return body;
}

export function buildAccidentPopupContent(properties: AccidentPopupProperties): HTMLDivElement {
  const rows = [properties.involves_bicycle ? "自転車関連事故" : "事故[自転車以外]"];
  if (properties.fatal) rows.push("死亡事故");
  if (properties.occurred_year != null) rows.push(`発生年: ${properties.occurred_year}`);
  return popupBody(rows);
}

export function buildPoiPopupContent(
  prefix: string,
  labels: Record<string, string>,
  properties: PoiPopupProperties,
): HTMLDivElement {
  // 種別はbackendの分類器が付ける内部名。名前を引けないときに種別で埋めると、それが
  // そのまま画面に出るため、種別が無いときと同じ「不明」にする。
  const label = (properties.kind ? labels[properties.kind] : undefined) ?? "不明";
  return popupBody([`${prefix}: ${label}`]);
}
