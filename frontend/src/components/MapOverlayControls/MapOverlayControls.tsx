"use client";

import { useRef, useState, type ReactElement } from "react";
import { createPortal } from "react-dom";
import {
  MAP_LAYER_CATEGORY_LABELS,
  MAP_LAYER_CATEGORY_ORDER,
  MAP_LAYER_DATA_NATURE_CHIP_LABELS,
  MAP_LAYER_DATA_NATURE_LABELS,
  type MapLayerCategory,
  type MapLayerDataNature,
  type MapLayerId,
} from "@/components/Map/mapLayers";
import { SECONDARY_AXES, type SecondaryAxisSummary } from "@/components/Map/secondaryAxes";
import {
  PRIMARY_ATTRIBUTE_CHIP_LABELS,
  PRIMARY_ATTRIBUTE_LAYER_IDS,
  axisMaterials,
} from "@/components/Map/primaryAttributes";
import type { LegendEntry, LegendFilterSummaryAxis } from "@/components/Map/legendFilter";
import {
  AccidentIcon,
  AxisRampIcon,
  DesignationIcon,
  ElevationIcon,
  EstimatedIndexIcon,
  ObservedDataIcon,
  RoadIcon,
  RoadSurfaceIcon,
  CarStressIcon,
  BicycleInfraIcon,
  StopPoiIcon,
  SupplyPoiIcon,
  RouteIcon,
} from "@/components/Map/icons";
import styles from "./MapOverlayControls.module.css";

/** 地図上のチップ1つ分の表示状態。page.tsxがMAP_LAYERS（レイヤーカタログ）から組み立てる。 */
export interface OverlayLayerChip {
  id: MapLayerId;
  label: string;
  /** アイコンチップ下に出す短縮表記（未指定ならlabelを使う） */
  chipLabel?: string;
  on: boolean;
  disabled?: boolean;
  /** チップのtitle（ONにすると何が出るか、disabledなら使えない理由） */
  title?: string;
  /** ▶を開いたときに出す案内文。legendDetailsが無い（描く凡例が無い）ときの
   * 唯一の表示内容として使う（例:「ズームインすると表示されます」）。legendDetailsが
   * あるときは軸ごとの内訳だけで十分なため使わない（レイヤー名や絞り込みの1行要約を
   * 重ねて出すと、▶を押した本人には自明な情報の繰り返しになるという実機フィードバックを
   * 受けて廃止した）。 */
  summary?: string | null;
  /** ▶を開いたときに出す、軸ごとの全カテゴリ内訳（表示中/非表示のいずれも含む）。
   * 絞り込み中かどうかに関わらず、レイヤーがONで凡例を持つならこれだけで開閉できる
   * （以前は絞り込み中のレイヤーしか▶が出なかったが、無条件のレイヤーでも凡例を
   * 確認したいという実機フィードバックを受け、legendDetailsの有無だけで判定するよう変更）。 */
  legendDetails?: readonly LegendFilterSummaryAxis[];
  /** 観測グループ内の小見出し分け（改善計画T86→T166）用。mapLayers.ts:
   * MapLayerDescriptor.categoryをそのまま渡す。未指定＝route等のdynamicレイヤーは
   * 次数グループに属さず単独チップのまま。 */
  category?: MapLayerCategory;
  /** 地図チップ最上位のグルーピング単位（改善計画T166、次数反転）。mapLayers.ts:
   * MapLayerDescriptor.dataNatureをそのまま渡す。categoryを持つチップは必ずこれで
   * 観測/推定のどちらかへ束ねられる（未指定は"raw"扱い）。 */
  dataNature?: MapLayerDataNature;
}

interface MapOverlayControlsProps {
  layers: readonly OverlayLayerChip[];
  onToggle: (id: MapLayerId, on: boolean) => void;
}

// 次数（観測/推定）単位でグルーピングされたチップの中身。categoryを持たないレイヤー
// （route等）は単独チップ（members.length === 1）としてまとめて表現し、単独/グループの
// 分岐をレンダリング側で1本化する（T128から続く設計、実装時の想定どおり「1件だけの
// グループ」として同じコンポーネントで扱う）。"group:raw"/"group:composite"は
// members.length===0でも（推定側はSECONDARY_AXESの薄字項目があるため）チップ自体を出す。
interface ChipGroup {
  key: string;
  members: readonly OverlayLayerChip[];
}

// categoryを持つレイヤーをdataNature（観測/推定、改善計画T166）で2グループへ束ね、
// categoryを持たないレイヤー（route等のdynamic）は元の並び順のまま末尾へ単独チップとして
// 追加する。推定グループは、対応する表示レイヤーを持つチップが1件も無くてもSECONDARY_AXESの
// 薄字項目（勾配・舗装質・夜間）を見せるため常に出す。観測グループはcategoryを持つ
// raw（dataNature省略含む）チップが1件以上あるときだけ出す。
function buildChipGroups(layers: readonly OverlayLayerChip[]): ChipGroup[] {
  const groups: ChipGroup[] = [];
  const observedMembers = layers.filter((layer) => layer.category && (layer.dataNature ?? "raw") === "raw");
  if (observedMembers.length > 0) groups.push({ key: "group:raw", members: observedMembers });
  const estimatedMembers = layers.filter((layer) => layer.category && layer.dataNature === "composite");
  groups.push({ key: "group:composite", members: estimatedMembers });
  for (const layer of layers) {
    if (!layer.category) groups.push({ key: layer.id, members: [layer] });
  }
  return groups;
}

// レイヤーIDごとの自作アイコン（icons.tsx）。地図上は文字だけのチップだとスペースを
// 圧迫するという実機フィードバックを受け、小さいアイコン+短いラベルの縦並びへ変更した。
const LAYER_ICONS: Record<MapLayerId, (props: { size?: number }) => ReactElement> = {
  elevation: ElevationIcon,
  roadType: RoadIcon,
  roadSurface: RoadSurfaceIcon,
  carStress: CarStressIcon,
  bicycleInfra: BicycleInfraIcon,
  designation: DesignationIcon,
  stopPoi: StopPoiIcon,
  supplyPoi: SupplyPoiIcon,
  accidents: AccidentIcon,
  route: RouteIcon,
};

// 次数グループチップ（改善計画T166）を代表するアイコン。観測/推定の2種類のみ。
const DATA_NATURE_ICONS: Record<MapLayerDataNature, (props: { size?: number }) => ReactElement> = {
  raw: ObservedDataIcon,
  composite: EstimatedIndexIcon,
};

// アイコン行と▶トグルの間の間隔（CSS変数--space-2と一致させる。内訳パネルの位置を
// JSで計算する際、CSS側の見た目の間隔と揃えるために数値でも持つ必要がある）。
const PANEL_GAP_PX = 8;

interface PanelRect {
  top: number;
  left: number;
  maxWidth: number;
}

// 凡例1カテゴリぶんのスウォッチ。太さ・線種で地図に反映するカテゴリ（entry.widthを持つ、
// 例:「道路の種類」）は色スウォッチのままだと「この色が地図に出る」という誤った期待を
// 持たせてしまう（WidthSwatch.tsxと同じ理由）ため、太さバーで示す。
function renderLegendSwatch(entry: LegendEntry) {
  return entry.width !== undefined ? (
    <span
      className={entry.dashed ? `${styles.detailSwatchBar} ${styles.detailSwatchBarDashed}` : styles.detailSwatchBar}
      style={{ height: `${Math.max(2, entry.width)}px` }}
    />
  ) : (
    <span className={styles.detailSwatchDot} style={{ background: entry.color }} />
  );
}

// ▶を開いたときの内訳パネル。軸に属する全カテゴリを表示中/非表示の別なく並べ、
// 非表示分だけ薄く見せる（「これだけで何が起きているか分かる」ことを優先する）。
function renderLegendDetails(axes: readonly LegendFilterSummaryAxis[]) {
  return (
    <div className={styles.detailBody}>
      {axes.map((axis, axisIndex) => (
        <div key={axis.label || axisIndex} className={styles.detailAxis}>
          {axis.label && <div className={styles.detailAxisLabel}>{axis.label}</div>}
          <ul className={styles.detailList}>
            {axis.legend.map((entry) => {
              const hidden = axis.hiddenKeys.includes(entry.key);
              // 「不明・他」等の受け皿カテゴリは他の項目と同列の判定値ではないため、区切り線で
              // 分離する（改善計画T89、MapLayersPanel.tsxの同種の区切りと対応）。
              const rowClasses = [styles.detailRow];
              if (hidden) rowClasses.push(styles.detailRowHidden);
              if (entry.isFallback) rowClasses.push(styles.detailRowFallback);
              return (
                <li key={entry.key} className={rowClasses.join(" ")}>
                  {renderLegendSwatch(entry)}
                  <span className={styles.detailRowLabel}>{entry.label}</span>
                  {hidden && <span className={styles.detailHiddenTag}>非表示</span>}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

// チップ本体の共通コンポーネント。単独チップ（グループ化されないレイヤー）とグループ
// チップ（改善計画T128、複数レイヤーを1つのカテゴリへ束ねたもの）の両方で同じ
// 「本体ボタン+隣の▶/▼ボタン」の2ボタン構成を使う。単独チップは本体タップ=ON/OFF・
// ▶/▼=凡例展開の別アクションだが、グループチップは束ねた個々のレイヤーのON/OFFが
// 一意に決まらず一括ON/OFFは設けない（誤操作リスク、改善計画T128の実装メモ参照）ため、
// 本体タップも展開トグルと同じ展開/収納にする（呼び出し側でonTapにonExpandToggleと
// 同じ関数を渡す）。
// MapOverlayControlsの内側に定義するとレンダーのたびに新しい関数（＝別のコンポーネント型）
// になり、Reactが毎回アンマウント/再マウントしてDOMノードの同一性が失われる（展開直後に
// 別要素へ差し替わり、テストや実機のフォーカス・aria状態が壊れる）ため、モジュール直下の
// 安定した関数として定義する。panelRects/rowRefsは親の状態のためprops経由で受け取る。
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
  /** 展開方向（改善計画T169、地図UIのマトリックス化）。中身が縦並びの観測グループは
   * "down"（▼、行の直下へ通常のドキュメントフローで展開し、内容の向きと矢印の向きを揃える）。
   * 中身が横並びの推定グループ・単独チップ（ルート等）は既定の"right"（▶、document.bodyへ
   * ポータルしてposition: fixedで行の右に浮かせる。chipRowのoverflow-y: autoの下でoverflow-xも
   * 暗黙にauto化しクリップされる問題を避けるため。"down"はパネルが行の通常の子要素として
   * chipRowの縦スクロールにそのまま乗るためポータルが不要）。 */
  expandDirection?: "right" | "down";
}) {
  const arrowGlyph = expandDirection === "down" ? "▼" : "▶";
  const arrowOpenClass = expandDirection === "down" ? styles.expandArrowDownOpen : styles.expandArrowOpen;
  return (
    <div ref={registerRow} className={styles.chipRowItem}>
      <div className={styles.iconToggleRow}>
        <button
          type="button"
          aria-pressed={active}
          disabled={disabled}
          title={title}
          onClick={onTap}
          className={active ? `${styles.iconChip} ${styles.iconChipActive}` : styles.iconChip}
        >
          <Icon />
          <span className={styles.iconLabel}>{chipLabel}</span>
        </button>
        {canExpand && (
          <button
            type="button"
            onClick={onExpandToggle}
            aria-expanded={isExpanded}
            aria-label={`${label}の凡例を${isExpanded ? "隠す" : "表示"}`}
            title="凡例を表示"
            className={isExpanded ? `${styles.expandToggle} ${styles.expandToggleActive}` : styles.expandToggle}
          >
            <span aria-hidden="true" className={isExpanded ? `${styles.expandArrow} ${arrowOpenClass}` : styles.expandArrow}>
              {arrowGlyph}
            </span>
          </button>
        )}
      </div>
      {isExpanded && expandDirection === "down" && <div className={styles.detailPanelInline}>{panelContent}</div>}
      {isExpanded &&
        expandDirection === "right" &&
        panelRect &&
        createPortal(
          <div
            className={styles.detailPanel}
            style={{ top: panelRect.top, left: panelRect.left, maxWidth: panelRect.maxWidth }}
          >
            {panelContent}
          </div>,
          document.body
        )}
    </div>
  );
}

// 地図の上に重ねるのは「地図を見ながら頻繁に切り替える」ON/OFFチップと、▶で開く凡例
// だけ。絞り込みの編集・色分けモードの選択など「変更を伴う設定」はすべてサイドバー
// （MapLayersPanel）で行う（地図上の▶はあくまで確認用で、以前あった「タップでサイドバーへ
// ジャンプ」動線はここが確認専用になったことで廃止した）。このコンポーネントはレイヤー
// 固有の知識を持たない汎用の描画係で、レイヤーが増えてもここは変更不要（mapLayers.tsの
// コメント参照）。
export default function MapOverlayControls({ layers, onToggle }: MapOverlayControlsProps) {
  // 凡例を常時表示すると地図の視界を圧迫するという実機フィードバックを受け、既定は
  // 非表示にし、チップ横の▶を押したレイヤーのぶんだけ薄いポップオーバーで出す。
  // 複数レイヤーを同時に開いておきたい場合もあるため、開閉はキーのSetで個別管理する。
  // キーはレイヤーID（単独チップ）またはグループキー`group:${category}`
  // （改善計画T128、カテゴリ束ねチップ）のどちらもありうるためstring。
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<string>>(new Set());
  // 内訳パネルの表示位置（viewport基準のpx）。アイコン列（chipRow）は縦スクロール可能
  // （レイヤー数が多い画面向け）だが、CSSの仕様上overflow-yを指定するとoverflow-xも
  // 暗黙にauto扱いになり、そのままではパネルをposition: absoluteでこの行の右へ
  // はみ出させる従来方式だとchipRowにクリップされて何も見えなくなる（実機フィードバック
  // 「▶を押しても何も出ない」＝この不具合）。document.bodyへポータルし、押した瞬間の
  // 行の実際の画面位置をJSで測ってposition: fixedで配置することでクリップを回避する。
  const [panelRects, setPanelRects] = useState<Partial<Record<string, PanelRect>>>({});
  const rowRefs = useRef<Partial<Record<string, HTMLDivElement | null>>>({});
  const chipRowRef = useRef<HTMLDivElement>(null);

  const toggleExpanded = (id: string) => {
    const isOpening = !expandedIds.has(id);
    if (isOpening) {
      const row = rowRefs.current[id];
      if (row) {
        const rect = row.getBoundingClientRect();
        const left = rect.right + PANEL_GAP_PX;
        setPanelRects((prev) => ({
          ...prev,
          [id]: { top: rect.top, left, maxWidth: Math.max(160, window.innerWidth - left - PANEL_GAP_PX) },
        }));
      }
    }
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // アイコン列をスクロールすると、position: fixedのパネルは行に追従できず表示が
  // ずれたままになる。ずれたパネルを見せ続けるより、スクロールを開くと同時に
  // いったん全部閉じる方が単純で分かりやすい。
  const handleChipRowScroll = () => {
    if (expandedIds.size > 0) setExpandedIds(new Set());
  };

  // 観測グループの1メンバー（改善計画T166→T169でタイル化）。推定グループの軸タイルと
  // 同じ「アイコン+略名の四角タイル+隣に付随する凡例展開ボタン」をChipButtonの再利用で
  // 表す（見た目を全要素で統一するというユーザー指摘への対応）。観測グループ自体は
  // ▼縦積み（ChipButtonのexpandDirection="down"）のため、メンバー個々の凡例は▶で
  // 右へ展開する（縦に並んだ他のメンバーと重ならないよう、グループ本体と直交する
  // 向きにする）。ONかつ凡例を持つメンバーのみ▶が付く。
  function renderRawMemberTile(member: OverlayLayerChip) {
    const key = `member:${member.id}`;
    const Icon = LAYER_ICONS[member.id] ?? AxisRampIcon;
    const hasLegend = Boolean(member.legendDetails && member.legendDetails.length > 0);
    const canExpand = Boolean(member.on && !member.disabled && hasLegend);
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
        panelContent={canExpand ? renderLegendDetails(member.legendDetails!) : <></>}
        panelRect={panelRects[key]}
        registerRow={(el) => {
          rowRefs.current[key] = el;
        }}
      />
    );
  }

  // 推定グループの各軸の下に出す材料一覧（改善計画T167）。axisMaterials（T164）から
  // 導出した一次属性を、表示レイヤーの有無で2行に分ける。レイヤーを持つ材料は
  // 「効いているものを探す」ときにそのまま地図上で確認できる旨、レイヤーを持たない材料
  // （車線数・制限速度・交差点・街灯・トンネル・自動車通行可否）は地図では見えない材料
  // として薄字で正直に見せる（略名はPRIMARY_ATTRIBUTE_CHIP_LABELS、primaryAttributes.ts
  // のコメントどおりT167用に4文字以下で全属性ぶん揃えてある）。
  function renderMaterialsNote(axisId: string) {
    const materials = axisMaterials(axisId);
    const withLayer = materials.filter((attrId) => PRIMARY_ATTRIBUTE_LAYER_IDS[attrId] !== undefined);
    const withoutLayer = materials.filter((attrId) => PRIMARY_ATTRIBUTE_LAYER_IDS[attrId] === undefined);
    if (withLayer.length === 0 && withoutLayer.length === 0) return null;
    return (
      <>
        {withLayer.length > 0 && (
          <p className={styles.detailNotice}>
            材料: {withLayer.map((attrId) => PRIMARY_ATTRIBUTE_CHIP_LABELS[attrId]).join("・")}
          </p>
        )}
        {withoutLayer.length > 0 && (
          <p className={`${styles.detailNotice} ${styles.detailRowHidden}`}>
            地図では未表示の材料: {withoutLayer.map((attrId) => PRIMARY_ATTRIBUTE_CHIP_LABELS[attrId]).join("・")}
          </p>
        )}
      </>
    );
  }

  // 「観測データ」グループ（改善計画T166）の▼内容: T128のカテゴリ束ねをそのまま小見出しへ
  // 転用し、MAP_LAYER_CATEGORY_ORDER順にメンバーを縦積みのタイル列（.memberColumn）として
  // 並べる。
  function renderObservedGroupPanel(members: readonly OverlayLayerChip[]) {
    const sections = MAP_LAYER_CATEGORY_ORDER.map((category) => ({
      label: MAP_LAYER_CATEGORY_LABELS[category],
      members: members.filter((m) => m.category === category),
    })).filter((section) => section.members.length > 0);
    return (
      <div className={styles.detailBody}>
        {sections.map((section) => (
          <div key={section.label} className={styles.detailAxis}>
            <div className={styles.detailAxisLabel}>{section.label}</div>
            <div className={styles.memberColumn}>{section.members.map((member) => renderRawMemberTile(member))}</div>
          </div>
        ))}
      </div>
    );
  }

  // 推定グループの1軸タイル（改善計画T166→T169でタイル化）。観測グループのメンバータイルと
  // 同じChipButtonを使い、見た目を統一する。専用の表示レイヤーを持つ軸（車の圧迫感・
  // 停止密度・事故密度）はlayersから対応するチップを引いてON/OFFタイルに、専用レイヤーの
  // 無い軸（勾配・舗装質・夜間）はdisabled＝タップ不能の情報タイルにする（secondaryAxes.ts
  // 参照）。推定グループ自体は▶横並び（ChipButtonのexpandDirection="right"）のため、
  // 軸タイル個々の凡例・材料一覧（改善計画T167）は▼で下へ展開する（横に並んだ他の軸と
  // 重ならないよう、グループ本体と直交する向きにする）。材料一覧はON/OFFに関わらず
  // 「材料になっている一次属性が何か」を確認できるようcanExpandへ含めるが、色の凡例は
  // 実際に地図へ描画されているときだけ意味を持つためON時のみ含める。ONにする操作自体は
  // 個別レイヤーのトグル（onToggle経由）に任せ、材料の連動ONはpage.tsx側
  // （handleLayerToggle）が行う（このコンポーネントはレイヤー固有の知識を持たない汎用
  // 描画係のまま、というファイル冒頭のコメント方針を維持する）。
  function renderAxisTile(axis: SecondaryAxisSummary, members: readonly OverlayLayerChip[]) {
    const key = `axis:${axis.axisId}`;
    const member = axis.layerId ? members.find((m) => m.id === axis.layerId) : undefined;
    const materialsNote = renderMaterialsNote(axis.axisId);
    if (!member) {
      const canExpand = Boolean(axis.proxyHint) || materialsNote !== null;
      return (
        <ChipButton
          key={key}
          Icon={AxisRampIcon}
          label={axis.label}
          chipLabel={axis.label}
          active={false}
          disabled
          title={axis.proxyHint}
          onTap={() => {}}
          canExpand={canExpand}
          isExpanded={canExpand && expandedIds.has(key)}
          onExpandToggle={() => toggleExpanded(key)}
          expandDirection="down"
          panelContent={
            <div className={styles.detailBody}>
              {axis.proxyHint && <p className={styles.detailNotice}>{axis.proxyHint}</p>}
              {materialsNote}
            </div>
          }
          panelRect={panelRects[key]}
          registerRow={(el) => {
            rowRefs.current[key] = el;
          }}
        />
      );
    }
    const Icon = LAYER_ICONS[member.id] ?? AxisRampIcon;
    const hasLegend = Boolean(member.legendDetails && member.legendDetails.length > 0);
    const showLegend = Boolean(member.on && !member.disabled && hasLegend);
    const canExpand = showLegend || materialsNote !== null;
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
        expandDirection="down"
        panelContent={
          <div className={styles.detailBody}>
            {showLegend && renderLegendDetails(member.legendDetails!)}
            {materialsNote}
          </div>
        }
        panelRect={panelRects[key]}
        registerRow={(el) => {
          rowRefs.current[key] = el;
        }}
      />
    );
  }

  function renderEstimatedGroupPanel(members: readonly OverlayLayerChip[]) {
    return <div className={styles.matrixRow}>{SECONDARY_AXES.map((axis) => renderAxisTile(axis, members))}</div>;
  }

  const chipGroups = buildChipGroups(layers);

  return (
    <div className={styles.wrapper}>
      <div className={styles.chipRow} ref={chipRowRef} onScroll={handleChipRowScroll}>
        {chipGroups.map((group) => {
          // 次数グループチップ（改善計画T166→T169でマトリックス化）。観測/推定のいずれも
          // タップは展開/収納のみ（一括ON/OFFは設けない）。推定グループはSECONDARY_AXESの
          // 情報セルがあるためmembersが0件でも常にチップを出す（buildChipGroups参照）。
          // 展開方向は中身の並びと揃える: 観測グループの内訳（category小見出し＋メンバーの
          // 縦積み）は▼で行の下へ、推定グループの内訳（6軸のアイコン横並び=マトリックス行）は
          // ▶で行の右へ（ChipButtonのexpandDirection参照）。
          if (group.key === "group:raw" || group.key === "group:composite") {
            const nature: MapLayerDataNature = group.key === "group:raw" ? "raw" : "composite";
            const RepresentativeIcon = DATA_NATURE_ICONS[nature];
            const anyOn = group.members.some((m) => m.on && !m.disabled);
            const isExpanded = expandedIds.has(group.key);
            const label = MAP_LAYER_DATA_NATURE_LABELS[nature];
            const chipLabel = MAP_LAYER_DATA_NATURE_CHIP_LABELS[nature];
            const itemCount = nature === "composite" ? SECONDARY_AXES.length : group.members.length;
            return (
              <ChipButton
                key={group.key}
                Icon={RepresentativeIcon}
                label={label}
                chipLabel={chipLabel}
                active={anyOn}
                title={`${label}[${itemCount}件をタップで一覧]`}
                onTap={() => toggleExpanded(group.key)}
                canExpand
                isExpanded={isExpanded}
                onExpandToggle={() => toggleExpanded(group.key)}
                expandDirection={nature === "raw" ? "down" : "right"}
                panelContent={
                  nature === "raw" ? renderObservedGroupPanel(group.members) : renderEstimatedGroupPanel(group.members)
                }
                panelRect={panelRects[group.key]}
                registerRow={(el) => {
                  rowRefs.current[group.key] = el;
                }}
              />
            );
          }

          // categoryを持たない単独チップ（route等のdynamicレイヤー）。
          const layer = group.members[0];
          // 二次軸rampレイヤー（改善計画T145b）はレジストリ生成物から自動で増えるため
          // レイヤーIDごとの専用アイコンを持たず、共通のAxisRampIconへフォールバックする
          // （undefinedのままJSXへ渡すとReactが「Element type is invalid」で落ちる）。
          const Icon = LAYER_ICONS[layer.id] ?? AxisRampIcon;
          const hasLegendDetails = Boolean(layer.legendDetails && layer.legendDetails.length > 0);
          const canExpand = layer.on && !layer.disabled && (hasLegendDetails || Boolean(layer.summary));
          const isExpanded = canExpand && expandedIds.has(layer.id);
          const panelContent =
            layer.legendDetails && layer.legendDetails.length > 0 ? (
              renderLegendDetails(layer.legendDetails)
            ) : (
              <p className={styles.detailNotice}>{layer.summary}</p>
            );
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
  );
}
