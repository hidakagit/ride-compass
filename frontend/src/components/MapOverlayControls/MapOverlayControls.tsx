"use client";

import { useRef, useState, type ReactElement } from "react";
import { createPortal } from "react-dom";
import {
  MAP_LAYER_CATEGORY_LABELS,
  MAP_LAYER_CATEGORY_ORDER,
  MAP_LAYER_DATA_NATURE_LABELS,
  type MapLayerCategory,
  type MapLayerDataNature,
  type MapLayerId,
} from "@/components/Map/mapLayers";
import type { LegendEntry, LegendFilterSummaryAxis } from "@/components/Map/legendFilter";
import {
  AccidentIcon,
  AxisRampIcon,
  DesignationIcon,
  ElevationIcon,
  RoadIcon,
  RoadSurfaceIcon,
  CarStressIcon,
  BicycleInfraIcon,
  StopPoiIcon,
  SupplyPoiIcon,
  RouteIcon,
} from "@/components/Map/icons";
import LayerChip from "@/components/Map/LayerChip";
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
  /** カテゴリ束ね（改善計画T128）用。mapLayers.ts: MapLayerDescriptor.categoryをそのまま渡す。
   * 同じcategoryを持つチップが2件以上あるときだけグループ化される（1件だけのカテゴリは
   * 従来どおり単独チップのまま。未指定＝route等のdynamicレイヤーも単独チップ）。 */
  category?: MapLayerCategory;
  /** グループを展開したときの小見出し分け（改善計画T128、交通・安全グループの
   * 「推定指標（合成）」「観測データ」）に使う。mapLayers.ts: MapLayerDescriptor.dataNature
   * をそのまま渡す。未指定は"raw"扱い。 */
  dataNature?: MapLayerDataNature;
}

interface MapOverlayControlsProps {
  layers: readonly OverlayLayerChip[];
  onToggle: (id: MapLayerId, on: boolean) => void;
}

// カテゴリ単位でグルーピングされたチップの中身。1件しかないカテゴリ・categoryを持たない
// レイヤー（route等）は単独チップ（members.length === 1）としてまとめて表現し、単独/グループの
// 分岐をレンダリング側で1本化する（実装時の想定どおり「1件だけのグループ」として同じ
// コンポーネントで扱う。改善計画T128の実装メモ参照）。
interface ChipGroup {
  key: string;
  members: readonly OverlayLayerChip[];
}

// category単位でMAP_LAYER_CATEGORY_ORDER順にグルーピングし、categoryを持たないレイヤー
// （route等のdynamic）は元の並び順のまま末尾へ単独チップとして追加する。
function buildChipGroups(layers: readonly OverlayLayerChip[]): ChipGroup[] {
  const groups: ChipGroup[] = [];
  for (const category of MAP_LAYER_CATEGORY_ORDER) {
    const members = layers.filter((layer) => layer.category === category);
    if (members.length > 0) groups.push({ key: category, members });
  }
  for (const layer of layers) {
    if (!layer.category) groups.push({ key: layer.id, members: [layer] });
  }
  return groups;
}

// カテゴリ内訳を「推定指標（合成）」「観測データ」の小見出しへ分ける（改善計画T128）。
// 全メンバーが同じdataNatureならグループ内で分ける意味が無いため、複数のnatureが混在する
// ときだけ小見出しを出す（現状これに該当するのはtrafficSafetyのみ）。
function groupByDataNature(
  members: readonly OverlayLayerChip[],
): { label: string | null; members: readonly OverlayLayerChip[] }[] {
  const natures = new Set(members.map((m) => m.dataNature ?? "raw"));
  if (natures.size <= 1) return [{ label: null, members }];
  const order: MapLayerDataNature[] = ["composite", "raw"];
  return order
    .map((nature) => ({
      label: MAP_LAYER_DATA_NATURE_LABELS[nature],
      members: members.filter((m) => (m.dataNature ?? "raw") === nature),
    }))
    .filter((section) => section.members.length > 0);
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

// グループチップ（改善計画T128）を代表するアイコン。1件しかないカテゴリは常に単独チップの
// ままでグループ化されない（buildChipGroups参照）ため、実際に使われるのは現状
// roadCondition・trafficSafetyのみ。それ以外のカテゴリが将来複数件になったときは
// 先頭メンバーのアイコンへフォールバックする（renderChipButton呼び出し側参照）。
const CATEGORY_ICONS: Partial<Record<MapLayerCategory, (props: { size?: number }) => ReactElement>> = {
  roadCondition: RoadIcon,
  trafficSafety: CarStressIcon,
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
// 「本体ボタン+隣の▶ボタン」の2ボタン構成を使う（アイコン＋▼という見た目の一貫性を
// 優先）。単独チップは本体タップ=ON/OFF・▶=凡例展開の別アクションだが、グループ
// チップは束ねた個々のレイヤーのON/OFFが一意に決まらず一括ON/OFFは設けない
// （誤操作リスク、改善計画T128の実装メモ参照）ため、本体タップも▶と同じ展開/収納に
// する（呼び出し側でonTapにonExpandToggleと同じ関数を渡す）。
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
}) {
  return (
    <div ref={registerRow} className={styles.iconWithToggle}>
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
          <span
            aria-hidden="true"
            className={isExpanded ? `${styles.expandArrow} ${styles.expandArrowOpen}` : styles.expandArrow}
          >
            ▶
          </span>
        </button>
      )}
      {isExpanded &&
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

  // グループチップ（改善計画T128）の▶内容: メンバーレイヤーごとの行（アイコン+ON/OFF）を
  // 「推定指標（合成）」「観測データ」の小見出しへ分けて並べる（groupByDataNature参照。
  // 全メンバーが同じ性質なら見出し無しのフラットな1本のリストになる）。各行はサイドバー
  // （MapLayersPanel）の「表示」チップと同じLayerChip部品を再利用し、ONのメンバーに
  // 凡例があれば単独チップと同じrenderLegendDetailsをその場に続けて出す（もう1段階の
  // ▶展開は設けず、グループを開いた時点で内訳まで見える方が操作が少なく分かりやすい）。
  function renderGroupMembers(members: readonly OverlayLayerChip[]) {
    const sections = groupByDataNature(members);
    return (
      <div className={styles.detailBody}>
        {sections.map((section, sectionIndex) => (
          <div key={section.label ?? sectionIndex} className={styles.detailAxis}>
            {section.label && <div className={styles.detailAxisLabel}>{section.label}</div>}
            <ul className={styles.detailList}>
              {section.members.map((member) => {
                const Icon = LAYER_ICONS[member.id] ?? AxisRampIcon;
                const hasLegend = Boolean(member.legendDetails && member.legendDetails.length > 0);
                return (
                  <li key={member.id} className={styles.memberRow}>
                    <div className={styles.detailRow}>
                      <Icon size={14} />
                      <LayerChip
                        label={member.chipLabel ?? member.label}
                        on={member.on}
                        disabled={member.disabled}
                        title={member.title}
                        onClick={() => onToggle(member.id, !member.on)}
                      />
                    </div>
                    {member.on && !member.disabled && hasLegend && (
                      <div className={styles.memberLegend}>{renderLegendDetails(member.legendDetails!)}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    );
  }

  const chipGroups = buildChipGroups(layers);

  return (
    <div className={styles.wrapper}>
      <div className={styles.chipRow} ref={chipRowRef} onScroll={handleChipRowScroll}>
        {chipGroups.map((group) => {
          if (group.members.length === 1) {
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
          }

          // カテゴリ束ねチップ（改善計画T128）。複数レイヤーをまとめて代表する1個のチップで、
          // タップは展開/収納のみ（一括ON/OFFは設けない）。いずれかのメンバーがONなら
          // アクティブ色にして「このグループの中で何か表示中」を示す。
          const category = group.key as MapLayerCategory;
          const RepresentativeIcon = CATEGORY_ICONS[category] ?? LAYER_ICONS[group.members[0].id] ?? AxisRampIcon;
          const groupKey = `group:${category}`;
          const anyOn = group.members.some((m) => m.on && !m.disabled);
          const isExpanded = expandedIds.has(groupKey);
          const label = MAP_LAYER_CATEGORY_LABELS[category];
          return (
            <ChipButton
              key={groupKey}
              Icon={RepresentativeIcon}
              label={label}
              chipLabel={label}
              active={anyOn}
              title={`${label}[${group.members.length}件をタップで一覧]`}
              onTap={() => toggleExpanded(groupKey)}
              canExpand
              isExpanded={isExpanded}
              onExpandToggle={() => toggleExpanded(groupKey)}
              panelContent={renderGroupMembers(group.members)}
              panelRect={panelRects[groupKey]}
              registerRow={(el) => {
                rowRefs.current[groupKey] = el;
              }}
            />
          );
        })}
      </div>
    </div>
  );
}
