"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactElement } from "react";
import { createPortal } from "react-dom";
import useEmblaCarousel from "embla-carousel-react";
import { WheelGesturesPlugin } from "embla-carousel-wheel-gestures";
import { useStoredState } from "@/hooks/useStoredState";
import {
  isAxisStudioLayer,
  LAYER_DATA_STATUS_LABELS,
  MAP_LAYER_CATEGORY_ORDER,
  MAP_OVERLAY_GROUP_LABELS,
  MAP_OVERLAY_GROUP_ORDER,
  MAP_OVERLAY_MAX_EXPANDED_GROUPS,
  mapOverlayGroupFor,
  type LayerDataStatus,
  type MapLayerCategory,
  type MapLayerDataNature,
  type MapLayerId,
  type MapOverlayGroup,
} from "@/features/map/layers/mapLayers";
import type { LegendEntry } from "@/lib/mapDisplay/legendFilter";
import LegendCheckboxList from "@/features/map/LegendCheckboxList/LegendCheckboxList";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import {
  EnvironmentDataIcon,
  InfoIcon,
  RoadIcon,
  SpotDataIcon,
  type MapIconComponent,
} from "@/components/ui/icons/icons";
import palette from "@/types/generated/palette.json";
import { Button } from "@/components/ui/Button/Button";
import { cn } from "@/lib/cn";
import { Dot } from "@/components/ui/Dot/Dot";
import { cardVariants } from "@/components/ui/Card/Card";
import { badgeVariants } from "@/components/ui/Badge/Badge";

/** 内訳パネルの色見本を載せる台（地図の地色）。CSSは源泉の値を持てないのでここで渡す。 */
const SWATCH_GROUND_STYLE = { "--swatch-ground": palette.semantic.basemap_ground } as CSSProperties;

/** 地図上のチップ1つ分の表示状態。page.tsxがbuildMapLayers（レイヤーカタログ）から組み立てる。 */
export interface LegendFilterSummaryAxis {
  /** 軸の名前（例:「路面の種類」）。カテゴリ名だけでは短く言えない場合のフォールバック文言に使う */
  label: string;
  legend: readonly LegendEntry[];
  hiddenKeys: readonly string[];
  /** 非表示キーの保存先を識別するID（`page.tsx: hiddenLegendKeysByMode`のキー）。
   * **これを持つ軸だけがユーザー操作で絞り込める**——地図上チップの▶パネル
   * （`MapOverlayControls`）のどこから操作しても
   * 同じIDの同じ状態を書き換える。ラスタタイルのように配信元が色を焼き込み済みで
   * カテゴリ単位の絞り込みができない軸（降水ナウキャスト・風・災害の危険度凡例等）は
   * 持たず、その軸は読み取り専用の凡例として描画される。 */
  axisId?: string;
}

export interface OverlayLayerChip {
  id: MapLayerId;
  label: string;
  /** チップ・設定パネルの行頭に出すアイコン。mapLayers.ts:
   * MapLayerDescriptor.iconをそのまま渡す。 */
  icon: MapIconComponent;
  /** アイコンチップ下に出す短縮表記（未指定ならlabelを使う） */
  chipLabel?: string;
  on: boolean;
  disabled?: boolean;
  /** チップのtitle（ONにすると何が出るか、disabledなら使えない理由） */
  title?: string;
  /** ▶を開いたとき、**凡例の代わりに**出す案内文（例:「ズームインすると表示されます」）。
   *
   * **これがあるときは凡例を出さない**——案内が出るのは「ONにしても何も出ない」
   * 状態だけで、そのときの凡例は地図に存在しない色見本の表になる。呼ぶ側が凡例を空へ
   * 揃える形にはしないこと（揃え忘れたレイヤーで案内が黙って落ちる）。 */
  notice?: string | null;
  /** ▶を開いたときに出す、軸ごとの全カテゴリ内訳（表示中/非表示のいずれも含む）。
   * 絞り込み中かどうかに関わらず、レイヤーがONで凡例を持つならこれだけで開閉できる。 */
  legendDetails?: readonly LegendFilterSummaryAxis[];
  /** グループ内の小見出し分け用。mapLayers.ts: MapLayerDescriptor.categoryをそのまま
   * 渡す。未指定＝route等はどのグループにも属さず単独チップのまま。 */
  category?: MapLayerCategory;
  /** mapOverlayGroupFor()がcategoryと合わせて最上位グループ（道路/環境/スポット）を
   * 判定するために使う。mapLayers.ts: MapLayerDescriptor.dataNatureをそのまま渡す。 */
  dataNature?: MapLayerDataNature;
  /** 軸スタジオ由来のレイヤーか（isAxisStudioLayer）。mapLayers.ts:
   * MapLayerDescriptor.axisStudioLayerをそのまま渡す——渡し漏れると専用way値配信軸が
   * 単独チップとして地図上へ現れてしまう。 */
  axisStudioLayer?: boolean;
  /** 「表示する項目を選ぶ」設定パネル（renderVisibilitySettings）で、この項目の行に
   * 個別の情報アイコンを出し、押すと表示する説明文。mapLayers.ts:
   * MapLayerDescriptor.panelHintをそのまま渡す。未設定なら情報アイコン自体を出さない。
   * ▶パネル本体（renderRawMemberTile等）へ常時表示する用途には使わない（設定パネル
   * 内の任意開閉表示専用）。 */
  panelHint?: string;
  /** レイヤーのデータ取得状態。ChipButtonがLayerChip（サイドバー）と同じ
   * 「on && dataStatus != null」の間だけ小さな状態ドットを添える。 */
  dataStatus?: LayerDataStatus;
}

interface MapOverlayControlsProps {
  layers: readonly OverlayLayerChip[];
  onToggle: (id: MapLayerId, on: boolean) => void;
  /** ▶パネル内の1行（凡例カテゴリ・災害の要素等）の表示/非表示を切り替える。
   * `axisId`を持つ軸（`LegendFilterSummaryAxis.axisId`）だけがチェックボックス付きで
   * 描画され、この関数を呼ぶ。保存先はチップ本体と同じ
   * `page.tsx: hiddenLegendKeysByMode`のため、どちらから操作しても状態は1つに揃う。 */
  onLegendEntryToggle: (axisId: string, key: string) => void;
  /** ▶パネル内の1軸をまとめて表示/非表示にする（見出し行のチェックボックス）。
   * 保存先は`onLegendEntryToggle`と同じ`page.tsx: hiddenLegendKeysByMode`。 */
  onLegendAxisSetHidden: (axisId: string, hiddenKeys: string[]) => void;
}

// 最上位グループ（道路/環境/スポット）単位でグルーピングされたチップの中身。どの
// グループにも属さないレイヤー（route等）は単独チップ（members.length === 1）として
// まとめて表現し、単独/グループの分岐をレンダリング側で1本化する。
interface ChipGroup {
  key: string;
  members: readonly OverlayLayerChip[];
}

// レイヤーをmapOverlayGroupFor()（mapLayers.ts）で最上位グループ（道路/環境/スポット）へ
// 束ね、どのグループにも属さないレイヤー（route等）は元の並び順のまま末尾へ単独チップ
// として追加する。ただし軸スタジオ由来のレイヤー（isAxisStudioLayer、ramp軸・専用way値配信軸）は
// mapOverlayGroupForがundefinedを返す点ではroute等と同じだが、ルート設定パネルへ移設し
// 地図UIには一切出さないため、単独チップとしても出さないよう明示的に除外する
// （undefinedだけだとroute等と区別できず単独チップとして復活してしまう）。表示順は
// MAP_OVERLAY_GROUP_ORDER（道路→環境→スポット）に従う。MapLayerDataNature（生/合成/
// 動的）とは独立した分類軸のため、この関数はdataNatureそのものではなく
// mapOverlayGroupForの判定結果だけを見る。
function buildChipGroups(layers: readonly OverlayLayerChip[]): ChipGroup[] {
  const groups: ChipGroup[] = [];
  for (const group of MAP_OVERLAY_GROUP_ORDER) {
    const members = layers.filter((layer) => mapOverlayGroupFor(layer) === group);
    if (members.length > 0) {
      groups.push({ key: groupExpandKey(group), members });
    }
  }
  for (const layer of layers) {
    if (!mapOverlayGroupFor(layer) && !isAxisStudioLayer(layer)) groups.push({ key: layer.id, members: [layer] });
  }
  return groups;
}

// 最上位グループチップ（道路/環境/スポット）を代表するアイコン。
// 道路=RoadIcon（個別メンバーhighwayと共用、群のテーマそのもの）・
// 環境=EnvironmentDataIcon（雲、terrain+weatherを併せて表す新規アイコン）・
// スポット=SpotDataIcon（地図ピン、新規アイコン）。
const MAP_OVERLAY_GROUP_ICONS: Record<MapOverlayGroup, (props: { size?: number }) => ReactElement> = {
  road: RoadIcon,
  environment: EnvironmentDataIcon,
  spot: SpotDataIcon,
};

// アイコン行と▶トグルの間の間隔（CSS変数--space-2と一致させる。内訳パネルの位置を
// JSで計算する際、CSS側の見た目の間隔と揃えるために数値でも持つ必要がある）。
const PANEL_GAP_PX = 8;
// 内訳パネルの既定の最大高さ（パネルのクラスの`max-h-[min(45vh,16rem)]`のうちrem側の値と一致させる。PANEL_GAP_PXと同じ理由で、
// 画面下端からのはみ出し対策（下記toggleExpanded参照）をJS側で計算するために数値でも
// 持つ必要がある）。
const DETAIL_PANEL_MAX_HEIGHT_PX = 256; // 16rem（ブラウザ既定のroot font-size 16pxベース）
// 内訳パネルの最小幅。画面右端に近いタイル（グループ末尾のメンバー等）の▼/▶を押すと、
// rect.right基準のleftが既にビューポート右端に近く、この最小幅すら確保できないまま
// panelRect.leftを
// 使ってしまい、パネルがビューポート外へはみ出して読めなくなっていた。leftをこの分
// だけビューポート内へ押し戻すことで、パネル自身が必ずこの最小幅ぶんは画面内に収まる
// ようにする（下記toggleExpanded参照）。
const MIN_PANEL_WIDTH_PX = 160;
// グループ本体の開閉キーとその逆引き。正本は`MAP_OVERLAY_GROUP_ORDER`で、キー文字列を
// 手で並べない——4つ目のグループを足したとき、ここと逆引きの両方が自動で追従する
// （追従しないと、そのグループの見出しが「グループ本体」と認識されず2件目以降が
// 地図チップ列から黙って消える）。
function groupExpandKey(group: MapOverlayGroup): string {
  return `group:${group}`;
}

/** 開閉キー（`group:road`等）からグループを引く。グループ本体でないキーはundefined。 */
function groupFromExpandKey(key: string): MapOverlayGroup | undefined {
  return MAP_OVERLAY_GROUP_ORDER.find((group) => groupExpandKey(group) === key);
}

// グループ本体の開閉キー（下記toggleExpandedのコメント参照）。floatingパネルを持たない
// ため、floatingパネル系とは別の規則（同時に開ける数の上限）で畳む。
const GROUP_VISIBILITY_KEYS = new Set(MAP_OVERLAY_GROUP_ORDER.map(groupExpandKey));

/** 開いたままにできるグループ数の上限（`MAP_OVERLAY_MAX_EXPANDED_GROUPS`）を超えたぶんを、
 * 古く開いたものから畳む。保存済みの状態にも同じ上限を効かせる——上限を下げる前に保存された
 * 値が残っていると、次に開いたときだけ上限を超えた状態で復元される。 */
function withinExpandedGroupLimit(keys: ReadonlySet<string>): Set<string> {
  const next = new Set(keys);
  const open = [...next].filter((key) => GROUP_VISIBILITY_KEYS.has(key));
  for (const stale of open.slice(0, Math.max(0, open.length - MAP_OVERLAY_MAX_EXPANDED_GROUPS))) {
    next.delete(stale);
  }
  return next;
}

/** 展開中のグループの「表示項目を選ぶ」パネルのキーを落とす。
 *
 * このパネルは折りたたみ中にだけ描かれるため、展開の間は開いたままのキーが画面に出ない。
 * 残しておくと、**次にそのグループを畳んだ瞬間、ⓘを押していないのにパネルが開いた状態で
 * 戻ってくる**。グループを畳む経路ごとに片割れの後始末を置くのではなく、開いた側を正規化
 * することで、畳む経路が増えても揃う（上限を超えて自動で畳まれる経路がこれに当たる）。 */
function withoutExpandedGroupPanels(keys: ReadonlySet<string>): Set<string> {
  const next = new Set(keys);
  for (const key of keys) {
    if (GROUP_VISIBILITY_KEYS.has(key)) next.delete(groupPanelKey(key));
  }
  return next;
}

/** グループの「表示項目を選ぶ」パネルのキー。`expandedIds`等の既存Setへそのまま同居する。 */
function groupPanelKey(groupKey: string): string {
  return `${groupKey}:legend`;
}

// グループの開閉・表示項目の設定をlocalStorageへ永続化する（時間経過で変動する要素以外は
// 次回訪問時も同じ状態を保つ）。page.tsxのlayerVisibility（各レイヤーのON/OFF自体）は
// 既にuseStoredStateで永続化済みのため、ここではMapOverlayControls固有の「見せ方」の
// 設定（グループ本体の開閉・非表示に選んだメンバー/軸）だけを対象にする。
const MAP_OVERLAY_EXPANDED_GROUPS_STORAGE_KEY = "ridecompass:map-overlay-expanded-groups";
const MAP_OVERLAY_HIDDEN_IDS_STORAGE_KEY = "ridecompass:map-overlay-hidden-ids";

// 文字列の配列としてSetを保存・復元する共通ヘルパー。keyFilterで「保存・復元してよい値か」を
// 絞り込む（expandedIdsはGROUP_VISIBILITY_KEYSのみ、hiddenIdsは無条件で文字列なら許可）。
// 個々の凡例展開（member:/axis:/単独チップ/${groupKey}:legend）は「今ちょっと確認のために
// 開いている」一時的な状態であり、次回訪問時に勝手にポップアップが開いた状態で再現される
// のは望ましくないため、expandedIdsはグループ本体の開閉（GROUP_VISIBILITY_KEYS）だけを
// 保存対象にする（フィルタはserialize/deserializeの両方に必要。serializeだけで絞ると
// 過去に保存された壊れた値・旧仕様の値がdeserialize経由でそのまま復元されてしまうため）。
function serializeStringSet(v: ReadonlySet<string>, keyFilter: (key: string) => boolean): string {
  return JSON.stringify([...v].filter(keyFilter));
}
function deserializeStringSet(raw: string, keyFilter: (key: string) => boolean): Set<string> | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    return new Set(parsed.filter((key): key is string => typeof key === "string" && keyFilter(key)));
  } catch {
    return null;
  }
}

interface PanelRect {
  top: number;
  left: number;
  maxHeight: number;
  maxWidth: number;
}

// 凡例1カテゴリぶんのスウォッチ。線レイヤーは太さ・線種で意味を運ばないため、どのカテゴリも
// 色ドットだけで示す。
function renderLegendSwatch(entry: LegendEntry) {
  return (
    <span
      className="box-content size-[7px] flex-shrink-0 rounded-full border-2 border-[var(--swatch-ground,transparent)] shadow-[0_0_0_1px_var(--color-border-strong)]"
      style={{ background: entry.color }}
    />
  );
}

// ▶を開いたときの内訳パネル。軸に属する全カテゴリを表示中/非表示の別なく並べる
// （「これだけで何が起きているか分かる」ことを優先する）。
// `axisId`を持つ軸はチェックボックス付き（サイドバーと同じ`LegendCheckboxList`）で描き、
// その場で表示/非表示を切り替えられる。持たない軸——配信元が色を焼き込み済みで
// カテゴリ単位の絞り込みができないラスタ系——は読み取り専用の一覧のまま、非表示分を
// 薄く見せる。
function renderLegendDetails(
  axes: readonly LegendFilterSummaryAxis[],
  onEntryToggle: (axisId: string, key: string) => void,
  onAxisSetHidden: (axisId: string, hiddenKeys: string[]) => void,
) {
  return (
    <div className="flex flex-col gap-2">
      {axes.map((axis, axisIndex) => (
        <div key={axis.axisId ?? axis.label ?? axisIndex} className="flex flex-col gap-1">
          {axis.axisId ? (
            // 一括ON/OFF。1つ残らず表示中のときだけチェックが入り、押すと全部隠す。
            // 1つでも隠れていれば未チェックで、押すと全部表示に戻る——狭い▶パネルに
            // 「すべて表示」「すべて隠す」の2ボタン（サイドバー側の形）を置く余地が
            // 無いため、1つのチェックボックスで両方向を兼ねる。
            <label className="flex cursor-pointer items-center gap-1.5">
              <Checkbox
                checked={axis.hiddenKeys.length === 0}
                onCheckedChange={() =>
                  onAxisSetHidden(
                    axis.axisId!,
                    axis.hiddenKeys.length === 0 ? axis.legend.map((entry) => entry.key) : [],
                  )
                }
                aria-label={`${axis.label || "すべての項目"}をまとめて表示/非表示`}
              />
              <span className="text-[length:var(--font-size-xs)] font-bold text-[var(--color-neutral)]">
                {axis.label || "すべて"}
              </span>
            </label>
          ) : (
            axis.label && (
              <div className="text-[length:var(--font-size-xs)] font-bold text-[var(--color-neutral)]">
                {axis.label}
              </div>
            )
          )}
          {axis.axisId ? (
            <LegendCheckboxList
              legend={axis.legend}
              hiddenKeys={axis.hiddenKeys}
              onToggle={(key) => onEntryToggle(axis.axisId!, key)}
              listClassName={"m-0 flex list-none flex-col gap-0.5 p-0"}
              rowClassName={"flex items-center gap-1.5 text-[length:var(--font-size-sm)]"}
              rowFallbackClassName={"mt-1 border-t border-dashed border-[var(--color-border)] pt-1"}
              swatchClassName={
                "box-content size-[7px] flex-shrink-0 rounded-full border-2 border-[var(--swatch-ground,transparent)] shadow-[0_0_0_1px_var(--color-border-strong)]"
              }
            />
          ) : (
            <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
              {axis.legend.map((entry) => {
                const hidden = axis.hiddenKeys.includes(entry.key);
                // 「不明・他」等の受け皿カテゴリは他の項目と同列の判定値ではないため、区切り線で
                // 分離する。
                const rowClasses = cn(
                  "flex items-center gap-1.5 text-[length:var(--font-size-sm)]",
                  hidden && "opacity-50",
                  entry.isFallback && "mt-1 border-t border-dashed border-[var(--color-border)] pt-1",
                );
                return (
                  <li key={entry.key} className={rowClasses}>
                    {renderLegendSwatch(entry)}
                    <span className="min-w-0 flex-1">{entry.label}</span>
                    {hidden && <span className={badgeVariants({ variant: "outline" })}>非表示</span>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

// チップ本体の共通コンポーネント。単独チップ（グループ化されないレイヤー）とグループ
// チップ（複数レイヤーを1つのカテゴリへ束ねたもの）の両方で同じ「本体ボタン+隣の
// ▶/▼ボタン」の2ボタン構成を使う。単独チップは本体タップ=ON/OFF・▶/▼=凡例展開の
// 別アクションだが、グループチップは束ねた個々のレイヤーのON/OFFが一意に決まらず
// 一括ON/OFFは設けない（誤操作リスク）ため、本体タップも展開トグルと同じ展開/収納に
// する（呼び出し側でonTapにonExpandToggleと同じ関数を渡す）。
// MapOverlayControlsの内側に定義するとレンダーのたびに新しい関数（＝別のコンポーネント型）
// になり、Reactが毎回アンマウント/再マウントしてDOMノードの同一性が失われる（展開直後に
// 別要素へ差し替わり、テストや実機のフォーカス・aria状態が壊れる）ため、モジュール直下の
// 安定した関数として定義する。panelRects/rowRefsは親の状態のためprops経由で受け取る。
// グループ（道路/環境/スポット）の色。見出しとメンバーが同じ色を持ち、縦に並んだチップがどのグループの
// 一員か一目で分かる。OFF＝枠線だけグループ色、ON＝グループ色で塗りつぶし。ONの文字色は
// --color-group-on-text（ダークモードでは-onの色が明るいため白文字だとコントラストが足りない）。
const GROUP_TINTS: Record<MapOverlayGroup, CSSProperties> = {
  road: {
    "--tint": "var(--color-group-road)",
    "--tint-on": "var(--color-group-road-on)",
    "--tint-bg": "var(--color-group-road-bg)",
  },
  environment: {
    "--tint": "var(--color-group-environment)",
    "--tint-on": "var(--color-group-environment-on)",
    "--tint-bg": "var(--color-group-environment-bg)",
  },
  spot: {
    "--tint": "var(--color-group-spot)",
    "--tint-on": "var(--color-group-spot-on)",
    "--tint-bg": "var(--color-group-spot-bg)",
  },
} as Record<MapOverlayGroup, CSSProperties>;

/** 地図上のチップ（アイコン＋短いラベルを縦に積む）。枠線の太さが、グループ・ON/展開の状態を読む手がかり。 */
function chipClass({ tinted, header, on }: { tinted: boolean; header: boolean; on: boolean }): string {
  return cn(
    "relative min-w-13 w-max flex-col gap-0.5 rounded-md border-2 p-1 text-center leading-[1.15] disabled:text-[var(--color-neutral)] disabled:opacity-100",
    tinted && "border-[var(--tint)] hover:enabled:border-[var(--tint)]",
    // 見出しはメンバーのON/OFFを表さないため青を使わない（「グループの内容が地図に出ている」と読まれる）。
    // 折りたたみ＝灰色、展開＝グループの薄色。
    header &&
      !on &&
      "border-[var(--color-neutral)] bg-[var(--color-surface-2)] hover:enabled:border-[var(--color-neutral)]",
    header && on && "bg-[var(--tint-bg)] text-[var(--tint)]",
    !header && on && !tinted && "border-[var(--color-accent)] bg-[var(--color-accent)] text-white",
    !header &&
      on &&
      tinted &&
      "border-[var(--tint-on)] bg-[var(--tint-on)] text-[var(--color-group-on-text)] hover:enabled:border-[var(--tint-on)]",
  );
}

/** チップ横の丸い開閉ボタン。開いている間は枠をアクセント色にする。 */
const ROUND_TOGGLE =
  "text-[var(--color-neutral)] shadow-none aria-expanded:border-[var(--color-accent)] aria-expanded:text-[var(--foreground)]";

const FILTERED_LABEL = "絞り込み中";

/** ▶・ⓘで開く内訳パネル（地図の上に浮かせ、開いた瞬間の行の位置へ置く）。 */
const DETAIL_PANEL_CLASS = cn(
  cardVariants({ variant: "glass" }),
  "fixed z-[var(--z-map-detail)] max-h-[min(45vh,16rem)] w-72 max-w-[calc(100vw-2*var(--space-3))] overflow-y-auto px-3 py-2",
);

/** チップの行はそれぞれ高さが違うため、吸着させずに離した位置で止める（dragFree）。先頭を上端に揃え、
 * 末尾より先へは送らない。 */
const CHIP_ROW_OPTIONS = { axis: "y", align: "start", dragFree: true, containScroll: "trimSnaps" } as const;

/** ONのレイヤーが凡例の絞り込みで一部を隠しているか。OFFの間は地図に何も出さないため数えない。 */
function isLegendFiltered(layer: OverlayLayerChip): boolean {
  return layer.on && !layer.disabled && (layer.legendDetails ?? []).some((axis) => axis.hiddenKeys.length > 0);
}

function ChipButton({
  Icon,
  label,
  chipLabel,
  active,
  disabled,
  title,
  onTap,
  canExpand,
  isExpanded,
  onExpandToggle,
  panelContent,
  panelRect,
  registerRow,
  expandDirection = "right",
  expandViaSelf,
  groupTint,
  dataStatus,
  filtered = false,
}: {
  Icon: (props: { size?: number }) => ReactElement;
  label: string;
  chipLabel: string;
  active: boolean;
  disabled?: boolean;
  title?: string;
  onTap: () => void;
  canExpand: boolean;
  isExpanded: boolean;
  onExpandToggle: () => void;
  panelContent: ReactElement;
  panelRect: PanelRect | undefined;
  registerRow: (el: HTMLDivElement | null) => void;
  /** 展開方向。
   * "down"（▼→▲、行の直下へ通常のドキュメントフローで展開）と"right"（▶→▽回転、
   * document.bodyへポータルしてposition: fixedで行の右に浮かせる。個々のメンバータイル・
   * 単独チップ（ルート等）の凡例展開はこちら）は自身がpanelContentを描画する。
   * "flat"（グループ見出しチップ本体、▼→▲）は、独立カード（サブフレーム）に閉じ込めず、地図の
   * チップ列と地続きに展開する。矢印の見た目は"down"と同じだが、自身は内訳を描画しない。
   * 呼び出し元（MapOverlayControls本体）がこのボタンの直後にメンバーをchipRowの直接の
   * 子として差し込む。 */
  expandDirection?: "right" | "down" | "flat";
  /** グループ見出しチップ本体だけに立てる印。true のときは隣接する▶/▼の丸トグルボタン自体を
   * 描画せず、本体ボタンのactive見た目とaria-expandedで開閉状態を表す。本体タップは
   * 元々onTapにtoggleExpandedと同じ関数を渡しているため、押下対象は変わらない
   * （挙動はそのまま、見た目と意味づけだけを変える）。単独チップ（ON/OFFと凡例展開が
   * 別アクション）はこの対象外で、独立した丸トグルを持つ。見出しの見た目は`chipClass`の`header`。 */
  expandViaSelf?: boolean;
  /** 最上位グループ（道路/環境/スポット）の色分け。未指定＝どのグループにも属さない
   * 単独チップ（ルート等）は無色のまま。 */
  groupTint?: MapOverlayGroup;
  /** レイヤーのデータ取得状態。LayerChip（サイドバー）と同じ
   * 「active && dataStatus != null」の間だけアイコン右上へ小さな状態ドットを添える。 */
  dataStatus?: LayerDataStatus;
  /** 凡例の絞り込みで一部を隠しているか。立っている間だけアイコン左上へ小さな印を添える
   * （絞り込みは保存されるため、次に開いたとき欠けた地図を「データが無い」と読ませない）。 */
  filtered?: boolean;
}) {
  const arrowGlyph = expandDirection === "right" ? "▶" : "▼";
  const arrowOpenClass = expandDirection === "right" ? "rotate-90" : "rotate-180";
  const isActiveVisual = expandViaSelf ? isExpanded : active;
  // レイヤーのデータ取得状態。LayerChip.tsxと同じ「ONの間だけ」判定（OFF中はチップ自体の
  // 見た目でON/OFFが分かるため出さない）。
  const showStatusDot = active && dataStatus != null;
  const statusLabel = dataStatus ? LAYER_DATA_STATUS_LABELS[dataStatus] : undefined;
  const titleNotes = [showStatusDot ? statusLabel : undefined, filtered ? FILTERED_LABEL : undefined].filter(Boolean);
  const chipTitle =
    titleNotes.length > 0 ? (title ? `${title}（${titleNotes.join("・")}）` : titleNotes.join("・")) : title;
  return (
    <div ref={registerRow} data-slot="chip-row-item" className="flex flex-shrink-0 flex-col gap-1 self-start">
      <div className="flex items-center gap-1">
        <Button
          variant="float"
          size="bare"
          aria-pressed={expandViaSelf ? undefined : active}
          aria-expanded={expandViaSelf ? isExpanded : undefined}
          disabled={disabled}
          title={chipTitle}
          onClick={onTap}
          style={groupTint ? GROUP_TINTS[groupTint] : undefined}
          className={chipClass({ tinted: groupTint !== undefined, header: expandViaSelf === true, on: isActiveVisual })}
        >
          <Icon />
          {showStatusDot && dataStatus && (
            <Dot aria-hidden="true" tone={dataStatus} className="absolute top-0.5 right-0.5" />
          )}
          {filtered && (
            <span
              aria-hidden="true"
              className="absolute top-1 left-1 h-2 w-2.5 bg-current [clip-path:polygon(0_0,100%_0,62%_50%,62%_100%,38%_100%,38%_50%)]"
            />
          )}
          <span className="whitespace-nowrap text-[0.58rem]">{chipLabel}</span>
        </Button>
        {canExpand && !expandViaSelf && (
          <Button
            variant="float"
            size="iconRound"
            className={ROUND_TOGGLE}
            onClick={onExpandToggle}
            aria-expanded={isExpanded}
            aria-label={`${label}の凡例を${isExpanded ? "隠す" : "表示"}`}
            title={isExpanded ? "凡例を隠す" : "凡例を表示"}
          >
            <span
              aria-hidden="true"
              className={cn(
                "inline-block text-[0.6rem] leading-none transition-transform duration-150",
                isExpanded && arrowOpenClass,
              )}
            >
              {arrowGlyph}
            </span>
          </Button>
        )}
      </div>
      {isExpanded &&
        (expandDirection === "right" || expandDirection === "down") &&
        panelRect &&
        createPortal(
          <div
            role="region"
            aria-label={`${label}の内訳`}
            className={DETAIL_PANEL_CLASS}
            style={{
              ...SWATCH_GROUND_STYLE,
              top: panelRect.top,
              left: panelRect.left,
              maxWidth: panelRect.maxWidth,
              maxHeight: panelRect.maxHeight,
            }}
          >
            {panelContent}
          </div>,
          document.body,
        )}
    </div>
  );
}

// 地図の上に重ねるのは「地図を見ながら頻繁に切り替える」ON/OFFチップと、▶で開く凡例。
// ▶パネルの中では凡例カテゴリの絞り込みまで操作でき、保存先はサイドバー側と同じ
// （page.tsx: hiddenLegendKeysByMode）。このコンポーネントはレイヤー
// 固有の知識を持たない汎用の描画係で、レイヤーが増えてもここは変更不要（mapLayers.tsの
// コメント参照）。
export default function MapOverlayControls({
  layers,
  onToggle,
  onLegendEntryToggle,
  onLegendAxisSetHidden,
}: MapOverlayControlsProps) {
  // 凡例は既定で非表示にし、チップ横の▶を押したレイヤーのぶんだけ薄いポップオーバーで
  // 出す（常時表示すると地図の視界を圧迫するため）。開閉はキーのSetで個別管理する。
  // キーはレイヤーID（単独チップ）・`member:${id}`（道路/環境/スポットグループの
  // メンバー）・グループキー`group:road`/`group:environment`/`group:spot`（グループ本体の
  // 開閉）・`${groupKey}:legend`（アイコンの意味凡例）のいずれか。
  // グループ本体の開閉はfloatingパネルを持たない（memberの一覧をchipRowへインラインで
  // 差し込むだけ）ため複数グループを同時に開いても重ならないが、それ以外
  // （member:/単独チップ/${groupKey}:legend）はdocument.bodyへポータルするfloatingパネルの
  // ため、複数同時に開くと近接する行同士でパネルが重なり両方とも判読不能になる
  // （降水ナウキャストと風の凡例を続けて開いた場合等）。
  // toggleExpanded側でfloatingパネル系のキーは排他（新しく開いたら他を閉じる）にする。
  // グループ本体の開閉（GROUP_VISIBILITY_KEYS）だけをlocalStorageへ永続化する（上記
  // MAP_OVERLAY_EXPANDED_GROUPS_STORAGE_KEYのコメント参照。floatingパネル系のキーは
  // 保存対象に含めない一時的な状態のまま）。
  const [expandedIds, setExpandedIds] = useStoredState<ReadonlySet<string>>(
    MAP_OVERLAY_EXPANDED_GROUPS_STORAGE_KEY,
    new Set(),
    {
      serialize: (v) => serializeStringSet(v, (key) => GROUP_VISIBILITY_KEYS.has(key)),
      deserialize: (raw) => {
        const restored = deserializeStringSet(raw, (key) => GROUP_VISIBILITY_KEYS.has(key));
        return restored === null ? null : withinExpandedGroupLimit(restored);
      },
    },
  );
  // 内訳パネルの表示位置（viewport基準のpx）。アイコン列（chipRow）は縦スクロール可能
  // （レイヤー数が多い画面向け）だが、CSSの仕様上overflow-yを指定するとoverflow-xも
  // 暗黙にauto扱いになり、パネルをposition: absoluteでこの行の右へはみ出させる方式だと
  // chipRowにクリップされて何も見えなくなる。document.bodyへポータルし、押した瞬間の
  // 行の実際の画面位置をJSで測ってposition: fixedで配置することでクリップを回避する。
  const [panelRects, setPanelRects] = useState<Partial<Record<string, PanelRect>>>({});
  const rowRefs = useRef<Partial<Record<string, HTMLDivElement | null>>>({});
  // チップ列が縦にはみ出したら、列をなぞって（PCはホイールでも）送る。▲▼は、まだ隠れている側がある間だけ出し、
  // 押すと1段送る。送り・はみ出しの測り直し（チップの増減・展開）はEmblaが持つ。
  const [chipRowRef, chipRowApi] = useEmblaCarousel(CHIP_ROW_OPTIONS, [WheelGesturesPlugin({ forceWheelAxis: "y" })]);
  const [chipRowHasLess, setChipRowHasLess] = useState(false);
  const [chipRowHasMore, setChipRowHasMore] = useState(false);

  // 道路/環境/スポットグループで「表示する項目を選ぶ」設定。グループ見出しのⓘボタンから、
  // 配下メンバーの表示・非表示を選べる設定パネルを開く。グループ本体を開くと、ここで
  // 非表示に選んだもの以外だけが並ぶ（絞り込みは各グループ内で完結し、既定＝何も非表示に
  // 選んでいない状態では全件表示）。キーは`${scope}:${memberId}`（scope="road"|
  // "environment"|"spot"、グループ間でIDが衝突しても名前空間で区別できるようにする）。
  // localStorageへ永続化する（レイヤー構成が変わり存在しないIDが残っても、
  // renderVisibilitySettings側は現在渡された項目とのマッチングでしか使わないため実害はない）。
  const [hiddenIds, setHiddenIds] = useStoredState<ReadonlySet<string>>(MAP_OVERLAY_HIDDEN_IDS_STORAGE_KEY, new Set(), {
    serialize: (v) => serializeStringSet(v, () => true),
    deserialize: (raw) => deserializeStringSet(raw, () => true),
  });

  // 非表示に選んだ項目に表示中のレイヤーが紐づいている場合、その場でレイヤー自体も
  // OFFにする。設定パネルからチップが消えた後もレイヤーが地図に描画され続け、かつ
  // チップが無いのでOFFにする手段も無くなる、という状態を防ぐ。逆方向（非表示解除＝
  // 再表示）はチップを選べるようにするだけで、レイヤーを自動でONにはしない
  // （「隠す/出す」はチップの見た目の設定であり、ON/OFFの意思決定はユーザーが個別に行う
  // という既存方針、member.onはこの関数の外＝呼び出し元のonTapが唯一の変更経路のまま）。
  function toggleHidden(hiddenKey: string, layerId: MapLayerId, isOn: boolean | undefined) {
    const isCurrentlyHidden = hiddenIds.has(hiddenKey);
    setHiddenIds((prev) => {
      const next = new Set(prev);
      if (isCurrentlyHidden) {
        next.delete(hiddenKey);
      } else {
        next.add(hiddenKey);
      }
      return next;
    });
    if (!isCurrentlyHidden && isOn) {
      onToggle(layerId, false);
    }
  }

  // 「表示する項目を選ぶ」設定パネル内、各項目の情報アイコンで説明文(panelHint)を
  // 開閉する状態。個々の凡例展開（member:/axis:等）と同じく「今ちょっと確認のために
  // 開いている」一時的な状態のため、localStorageへは永続化しない
  // （serializeStringSet/deserializeStringSetの対象に含めない）。キーは
  // `${scope}:${item.key}`でhiddenIdsと同じ名前空間の作り方に揃える。
  const [openInfoKeys, setOpenInfoKeys] = useState<ReadonlySet<string>>(new Set());
  function toggleInfo(key: string) {
    setOpenInfoKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  // anchor="right"（行の右へ）/"down"（行の直下へ）。いずれもdocument.bodyへポータルして
  // position: fixedで浮かせる（下記ChipButton参照）。chipRowのoverflow-y: auto
  // （＝暗黙にoverflow-xもauto）の内側でposition: absolute配置すると、パネルが
  // chipRowのスクロール可能領域に算入されてしまい、パネル1個ぶん右にはみ出ただけで
  // chipRowに横スクロールバーが出てしまうため、ポータルで完全にchipRowの外へ出す。
  const toggleExpanded = (id: string, anchor: "right" | "down" = "right") => {
    const isOpening = !expandedIds.has(id);
    if (isOpening) {
      const row = rowRefs.current[id];
      if (row) {
        const rect = row.getBoundingClientRect();
        const top = anchor === "down" ? rect.bottom + PANEL_GAP_PX : rect.top;
        const rawLeft = anchor === "down" ? rect.left : rect.right + PANEL_GAP_PX;
        // 画面右端からのはみ出し対策。画面右端に近いタイル（グループ末尾のメンバー等）だと
        // rawLeftが既にビューポート
        // 右端に近く、下のmaxWidth計算のMath.max(160, ...)フロアにより最小幅160pxが
        // 強制されてもleft自体を動かさないままだとパネルがビューポート外へはみ出して
        // しまう。leftをこの分だけ画面内へ押し戻し、パネルが必ずMIN_PANEL_WIDTH_PXぶん
        // 画面内に収まるようにする（画面幅自体がそれより狭い極端なケースはPANEL_GAP_PX
        // まで詰める）。
        const left = Math.min(rawLeft, Math.max(PANEL_GAP_PX, window.innerWidth - MIN_PANEL_WIDTH_PX - PANEL_GAP_PX));
        // 画面下端からのはみ出し対策。position: fixedのためtopが画面下端に近いと、
        // CSS既定の最大高さ（16rem）ぶんが
        // ビューポート外へはみ出してしまい、パネル自身のoverflow-y: autoでスクロールしても
        // ビューポート外の部分には原理的に到達できない（fixed要素はドキュメントのスクロール
        // 領域に算入されないため）。横方向のmaxWidthを画面幅から逆算するのと同じ考え方で、
        // 利用可能な高さがCSS既定の上限より狭ければmaxHeightを縮め、パネル自体をその場の
        // 残りスペースに収める（縮めた分はパネル自身のoverflow-y: autoで内部スクロール）。
        const availableHeight = window.innerHeight - top - PANEL_GAP_PX;
        const maxHeight = Math.max(120, Math.min(DETAIL_PANEL_MAX_HEIGHT_PX, availableHeight));
        setPanelRects((prev) => ({
          ...prev,
          [id]: {
            top,
            left,
            maxWidth: Math.max(MIN_PANEL_WIDTH_PX, window.innerWidth - left - PANEL_GAP_PX),
            maxHeight,
          },
        }));
      }
    }
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        // floatingパネル系のキー（member:/axis:/単独チップ/${groupKey}:legend）は排他:
        // 新しく開くキーがグループ本体の開閉（GROUP_VISIBILITY_KEYS）でなければ、他の
        // floatingパネル系キーをすべて閉じてから開く。グループ本体同士はfloatingパネルを
        // 持たないため対象外のまま複数同時に開ける。
        if (!GROUP_VISIBILITY_KEYS.has(id)) {
          for (const existing of next) {
            if (!GROUP_VISIBILITY_KEYS.has(existing)) next.delete(existing);
          }
        }
        next.add(id);
        if (GROUP_VISIBILITY_KEYS.has(id)) return withoutExpandedGroupPanels(withinExpandedGroupLimit(next));
      }
      return withoutExpandedGroupPanels(next);
    });
  };

  // ページ送り（▲▼/◀▶）を押すと、position: fixedの凡例パネルは行に追従できず表示が
  // ずれたままになるため閉じる。ページ送り自体はグループを開いたまま行いたい操作のため、
  // グループ自体の展開状態（GROUP_VISIBILITY_KEYS）は対象にせず、フローティングパネル系の
  // キー（member:/axis:/単独チップ/${groupKey}:legend）だけを閉じる。
  const closeFloatingPanels = () => {
    setExpandedIds((prev) => {
      const next = new Set([...prev].filter((key) => GROUP_VISIBILITY_KEYS.has(key)));
      return next.size === prev.size ? prev : next;
    });
  };

  // 内訳パネルは開いた瞬間の行の位置へ浮かせているため、列が動いたら閉じる（何も開いていなければ
  // setExpandedIdsが同じ参照を返すので、送りのたびに呼んでも描き直さない）。
  const closeFloatingPanelsRef = useRef(closeFloatingPanels);
  useEffect(() => {
    closeFloatingPanelsRef.current = closeFloatingPanels;
  });
  useEffect(() => {
    if (!chipRowApi) return;
    const sync = () => {
      setChipRowHasLess(chipRowApi.canScrollPrev());
      setChipRowHasMore(chipRowApi.canScrollNext());
    };
    // 閉じるのは、なぞって列を動かしたときだけ。押しただけ（チップ・▶を押す）で閉じると、押した▶の開閉と打ち消し合う。
    let dragging = false;
    const down = () => {
      dragging = true;
    };
    const up = () => {
      dragging = false;
    };
    const scroll = () => {
      sync();
      if (dragging) closeFloatingPanelsRef.current();
    };
    sync();
    chipRowApi.on("select", sync).on("reInit", sync).on("scroll", scroll).on("pointerDown", down).on("pointerUp", up);
    return () => {
      chipRowApi
        .off("select", sync)
        .off("reInit", sync)
        .off("scroll", scroll)
        .off("pointerDown", down)
        .off("pointerUp", up);
    };
  }, [chipRowApi]);
  const pageChipRow = (direction: "prev" | "next") => {
    closeFloatingPanels();
    if (direction === "prev") chipRowApi?.scrollPrev();
    else chipRowApi?.scrollNext();
  };

  // グループの1メンバー。「アイコン+略名の四角タイル+
  // 隣に付随する凡例展開ボタン」をChipButtonの再利用で表す（見た目を全要素で統一する）。
  // グループ見出し自体は▼縦積み（ChipButtonのexpandDirection="flat"）のため、メンバー
  // 個々の凡例は▶で右へ展開する（縦に並んだ他のメンバーと重ならないよう、グループ本体と
  // 直交する向きにする）。凡例を持つメンバーはON/OFFに関わらず常に▶が付く（単独チップの
  // 軸タイルがON/OFFに関わらず▼を出すのと揃える。legendDetailsはレイヤー定義由来の固定
  // 内容でありON/OFFで内容が変わらないため、OFF中に「オンにすると何が出るか」を先に
  // 確認できる利点もある）。
  /** ▶を開いたときの中身。**案内文があるときは凡例を出さない**——案内が出るのは
   * 「ONにしても何も出ない」状態だけで、そのときの凡例は地図に存在しない色見本の表になる。
   * グループのメンバーと単独チップで同じ判断をするため、ここ1箇所に置く。 */
  function panelContentFor(layer: OverlayLayerChip) {
    if (layer.notice)
      return <p className="m-0 text-[length:var(--font-size-sm)] text-[var(--foreground)]">{layer.notice}</p>;
    const status = dataStatusNoticeFor(layer);
    return (
      <>
        {status && (
          <p className="mb-2 text-[length:var(--font-size-sm)] text-[var(--foreground)]" role="status">
            {status}
          </p>
        )}
        {renderLegendDetails(layer.legendDetails ?? [], onLegendEntryToggle, onLegendAxisSetHidden)}
      </>
    );
  }

  /** 状態ドットの意味を文で読ませる置き場は▶の中。`title`はスマホでは出ないため、
   * ドットを出している間（ONかつ状態あり）は凡例の上へ同じ文言を出す。 */
  function dataStatusNoticeFor(layer: OverlayLayerChip): string | null {
    if (!layer.on || layer.disabled || !layer.dataStatus) return null;
    return LAYER_DATA_STATUS_LABELS[layer.dataStatus];
  }

  /** ▶自体を出すか。案内文も状態も凡例も無ければ開いても空になる。 */
  function canExpandPanel(layer: OverlayLayerChip) {
    return (
      Boolean(layer.notice) ||
      dataStatusNoticeFor(layer) !== null ||
      Boolean(layer.legendDetails && layer.legendDetails.length > 0)
    );
  }

  function renderRawMemberTile(member: OverlayLayerChip, groupTint: MapOverlayGroup) {
    const key = `member:${member.id}`;
    const Icon = member.icon;
    const canExpand = !member.disabled && canExpandPanel(member);
    return (
      <ChipButton
        key={key}
        Icon={Icon}
        label={member.label}
        chipLabel={member.chipLabel ?? member.label}
        active={Boolean(member.on && !member.disabled)}
        disabled={member.disabled}
        title={member.title}
        onTap={() => onToggle(member.id, !member.on)}
        canExpand={canExpand}
        isExpanded={canExpand && expandedIds.has(key)}
        onExpandToggle={() => toggleExpanded(key)}
        expandDirection="right"
        groupTint={groupTint}
        dataStatus={member.dataStatus}
        filtered={isLegendFiltered(member)}
        panelContent={canExpand ? panelContentFor(member) : <></>}
        panelRect={panelRects[key]}
        registerRow={(el) => {
          rowRefs.current[key] = el;
        }}
      />
    );
  }

  // 「観測データ」グループの▼内容: 独立したカード（サブフレーム）に閉じ込めず、
  // chipRowの直接の子として観測チップの直後に地続きで差し込む。category小見出し
  // （道路状態・交通・安全）は表示せず、MAP_LAYER_CATEGORY_ORDER順のフラットな一覧に
  // する（順序自体はcategory順を保つが、見出しテキストは出さない）。メンバー本体
  // （renderRawMemberTile）はChipButtonが自前でchipRowItemを返すため、ここでは
  // 追加のラッパーを挟まずそのままchipRowの子として返す。
  function orderObservedMembers(members: readonly OverlayLayerChip[]): readonly OverlayLayerChip[] {
    return MAP_LAYER_CATEGORY_ORDER.flatMap((category) => members.filter((m) => m.category === category));
  }

  // メンバー増加で展開直後に画面下端を超えて見切れることを避けるため、Ⓘの設定パネル
  // （renderVisibilitySettings）で非表示に選んだメンバーはここで除外する。groupTint/scopeは
  // 常に同じグループ値（`MapOverlayGroup`）を渡すため1引数に統合してある。
  function renderObservedMemberRows(members: readonly OverlayLayerChip[], group: MapOverlayGroup): ReactElement[] {
    return orderObservedMembers(members)
      .filter((member) => !hiddenIds.has(`${group}:${member.id}`))
      .map((member) => renderRawMemberTile(member, group));
  }

  // 道路/環境/スポットグループ見出しの「表示する項目を選ぶ」設定パネル。各項目に表示/
  // 非表示のチェックボックスを持たせ、ここで選んだ項目だけがグループ展開時に並ぶ。
  // 折りたたみ時だけ見出しの脇に出す独立した入口にする（展開後は絞り込み済みの項目自体の
  // アイコンが並ぶため、その場に同じ一覧をもう一度出すと二重表示になってかえって読み
  // にくい）。呼び出し側（chipGroups.flatMapの中）が `!isExpanded` のときだけこの関数を
  // 呼ぶことで担保する。ChipButtonは使わず、同じ「小さい丸ボタン+document.bodyへ
  // ポータルする内訳パネル」の仕組み（toggleExpanded/panelRects/rowRefs）を直接流用する
  // 軽量な専用実装にする。キーは`${groupKey}:legend`でexpandedIds等の既存Setにそのまま
  // 同居できる。
  function renderVisibilitySettings(
    groupKey: string,
    groupLabel: string,
    scope: MapOverlayGroup,
    items: readonly {
      key: string;
      Icon: (props: { size?: number }) => ReactElement;
      label: string;
      /** 対応するレイヤーID。非表示に選んだ瞬間そのレイヤーがONならOFFにするために使う
       * （toggleHidden参照）。この設定パネルへ並ぶのは地図チップを持つレイヤーだけなので
       * 必ず値がある。 */
      layerId: MapLayerId;
      on?: boolean;
      /** 行の右側に個別の情報アイコンを出し、押すと表示する説明文。未設定なら情報
       * アイコン自体を出さない。 */
      description?: string;
    }[],
  ) {
    const legendKey = groupPanelKey(groupKey);
    const isOpen = expandedIds.has(legendKey);
    const rect = panelRects[legendKey];
    return (
      <div
        key={legendKey}
        ref={(el) => {
          rowRefs.current[legendKey] = el;
        }}
        data-slot="chip-row-item"
        className="flex flex-shrink-0 flex-col gap-1 self-start"
      >
        <div className="flex items-center gap-1">
          <Button
            variant="float"
            size="iconRound"
            className={ROUND_TOGGLE}
            onClick={() => toggleExpanded(legendKey, "down")}
            aria-expanded={isOpen}
            aria-label={`${groupLabel}の表示項目を${isOpen ? "隠す" : "設定"}`}
            title="表示する項目を選ぶ"
          >
            <InfoIcon size={12} />
          </Button>
        </div>
        {isOpen &&
          rect &&
          createPortal(
            <div
              role="region"
              aria-label={`${groupLabel}の表示項目`}
              className={DETAIL_PANEL_CLASS}
              style={{ top: rect.top, left: rect.left, maxWidth: rect.maxWidth, maxHeight: rect.maxHeight }}
            >
              <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                {items.flatMap((item) => {
                  const hiddenKey = `${scope}:${item.key}`;
                  const isHidden = hiddenIds.has(hiddenKey);
                  // infoKeyはhiddenKeyと同じ`${scope}:${item.key}`名前空間だが別のSet
                  // （openInfoKeys）で管理するため、非表示設定と情報アイコンの開閉は
                  // 互いに影響しない。
                  const infoKey = hiddenKey;
                  const isInfoOpen = openInfoKeys.has(infoKey);
                  const row = (
                    <li key={item.key} className="flex items-center gap-1.5 text-[length:var(--font-size-sm)]">
                      <Checkbox
                        checked={!isHidden}
                        onCheckedChange={() => toggleHidden(hiddenKey, item.layerId, item.on)}
                        aria-label={`${item.label}を${isHidden ? "表示する" : "表示しない"}`}
                      />
                      <item.Icon size={16} />
                      <span className="min-w-0 flex-1">{item.label}</span>
                      {item.description && (
                        <Button
                          size="iconRound"
                          className={cn("size-5", ROUND_TOGGLE)}
                          onClick={() => toggleInfo(infoKey)}
                          aria-expanded={isInfoOpen}
                          aria-label={`${item.label}の説明を${isInfoOpen ? "隠す" : "表示"}`}
                          title={isInfoOpen ? "説明を隠す" : "説明を表示"}
                        >
                          <InfoIcon size={12} />
                        </Button>
                      )}
                    </li>
                  );
                  if (!item.description || !isInfoOpen) return [row];
                  return [
                    row,
                    <li key={`${item.key}:info`} className="pl-8">
                      <p className="m-0 text-[length:var(--font-size-sm)] text-[var(--foreground)]">
                        {item.description}
                      </p>
                    </li>,
                  ];
                })}
              </ul>
            </div>,
            document.body,
          )}
      </div>
    );
  }

  const chipGroups = buildChipGroups(layers);

  return (
    <div className="pointer-events-none absolute top-3 left-3 z-[var(--z-map-control)] flex w-max max-w-[calc(100%-2*var(--space-3)-3rem)] flex-col items-start gap-2 max-mobile:bottom-[calc(var(--space-3)+var(--mobile-tabbar-height)+var(--bottom-control-row-height,0px))]">
      {chipRowHasLess && (
        <Button
          variant="float"
          size="bare"
          className="h-6.5 self-stretch rounded-md px-1 text-[1.1rem] shadow-none"
          onClick={() => pageChipRow("prev")}
          aria-label="上を表示"
          title="上を表示"
        >
          ▲
        </Button>
      )}
      <div className="w-max max-w-full max-h-[min(80vh,42rem)] overflow-hidden" ref={chipRowRef}>
        <div className="flex w-max max-w-full flex-col gap-2">
          {chipGroups.flatMap((group) => {
            // 道路/環境/スポットグループは「▼縦積み・地続き展開」の構成を共有する。▼を
            // 開くと、独立したカードに閉じ込めず、メンバーをchipRowの直接の子として
            // グループチップの直後に地続きで差し込む。ChipButton自身はexpandDirection="flat"で
            // ▼矢印の見た目だけを持ち、内訳は描画しない（renderObservedMemberRowsを別途
            // sibling要素として返す）。3グループとも見た目・挙動が完全に同一のため、
            // 1つの分岐にまとめる。
            const flatGroup = groupFromExpandKey(group.key);
            if (flatGroup) {
              const RepresentativeIcon = MAP_OVERLAY_GROUP_ICONS[flatGroup];
              const isExpanded = expandedIds.has(group.key);
              const label = MAP_OVERLAY_GROUP_LABELS[flatGroup];
              const chipLabel = MAP_OVERLAY_GROUP_LABELS[flatGroup];
              const header = (
                <ChipButton
                  key={group.key}
                  Icon={RepresentativeIcon}
                  label={label}
                  chipLabel={chipLabel}
                  // 見出しチップは地図への反映を持たない（メンバーのON/OFFはそれぞれのタイルが
                  // 決める）ため、activeは常にfalse。見た目のactiveは展開状態(isExpanded)が決める。
                  active={false}
                  title={`${label}[${group.members.length}件をタップで一覧]`}
                  onTap={() => toggleExpanded(group.key)}
                  canExpand
                  isExpanded={isExpanded}
                  onExpandToggle={() => toggleExpanded(group.key)}
                  expandDirection="flat"
                  expandViaSelf
                  groupTint={flatGroup}
                  filtered={!isExpanded && group.members.some(isLegendFiltered)}
                  panelContent={<></>}
                  panelRect={panelRects[group.key]}
                  registerRow={(el) => {
                    rowRefs.current[group.key] = el;
                  }}
                />
              );
              // 折りたたみ中だけ見出しの脇に「表示する項目を選ぶ」の入口を出し、展開後は消す
              // （展開すればメンバーが見えるため、同じ内容の入口を二重に置かない）。ラッパーdivの
              // keyは折りたたみ/展開のどちらでも同じ値に固定し、headerのDOMノードを保つ——
              // keyが変わるとChipButtonが作り直され、開閉のたびにフォーカスが外れる。
              // 展開時はメンバーを縦積みするため.observedExpandedColumn
              // （chipRowと同じcolumn flex）、折りたたみ時は見出し+凡例トグルの横並びのため
              // .headerLegendRowを使う。
              return [
                <div
                  key={`${group.key}:row`}
                  className={
                    isExpanded
                      ? "flex flex-col gap-2 self-start"
                      : "flex min-w-0 max-w-full items-start gap-1 self-start"
                  }
                >
                  {header}
                  {isExpanded
                    ? renderObservedMemberRows(group.members, flatGroup)
                    : renderVisibilitySettings(
                        group.key,
                        label,
                        flatGroup,
                        orderObservedMembers(group.members).map((member) => ({
                          key: member.id,
                          Icon: member.icon,
                          label: member.chipLabel ?? member.label,
                          layerId: member.id,
                          on: member.on,
                          description: member.panelHint,
                        })),
                      )}
                </div>,
              ];
            }

            // どのグループにも属さない単独チップ（route等）。
            const layer = group.members[0];
            const Icon = layer.icon;
            const canExpand = layer.on && !layer.disabled && canExpandPanel(layer);
            const isExpanded = canExpand && expandedIds.has(layer.id);
            const panelContent = panelContentFor(layer);
            return (
              <ChipButton
                key={layer.id}
                Icon={Icon}
                label={layer.label}
                chipLabel={layer.chipLabel ?? layer.label}
                active={layer.on && !layer.disabled}
                disabled={layer.disabled}
                title={layer.title}
                onTap={() => onToggle(layer.id, !layer.on)}
                canExpand={canExpand}
                isExpanded={isExpanded}
                onExpandToggle={() => toggleExpanded(layer.id)}
                dataStatus={layer.dataStatus}
                filtered={isLegendFiltered(layer)}
                panelContent={panelContent}
                panelRect={panelRects[layer.id]}
                registerRow={(el) => {
                  rowRefs.current[layer.id] = el;
                }}
              />
            );
          })}
        </div>
      </div>
      {chipRowHasMore && (
        <Button
          variant="float"
          size="bare"
          className="h-6.5 self-stretch rounded-md px-1 text-[1.1rem] shadow-none"
          onClick={() => pageChipRow("next")}
          aria-label="下を表示"
          title="下を表示"
        >
          ▼
        </Button>
      )}
    </div>
  );
}
