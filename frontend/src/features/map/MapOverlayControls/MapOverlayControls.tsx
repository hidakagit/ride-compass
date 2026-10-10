"use client";

import { useId, useState, type CSSProperties, type ReactElement, type ReactNode } from "react";
import { useStoredState } from "@/hooks/useStoredState";
import {
  LAYER_DATA_STATUS_LABELS,
  layerDataStatusNotice,
  MAP_LAYER_CATEGORY_ORDER,
  MAP_OVERLAY_GROUP_LABELS,
  MAP_OVERLAY_GROUP_ORDER,
  mapOverlayGroupFor,
  type LayerDataStatus,
  type MapLayerCategory,
  type MapLayerId,
  type MapOverlayGroup,
} from "@/features/map/layers/mapLayers";
import { LEGEND_SWATCH_RING_CLASS, legendSwatchBackground, type LegendEntry } from "@/lib/mapDisplay/legendFilter";
import LegendCheckboxList from "@/features/map/LegendCheckboxList/LegendCheckboxList";
import LegendRow, { DescriptionToggle, RowDescription } from "@/features/map/LegendCheckboxList/LegendRow";
import { PointIconSwatch } from "@/features/map/layers/pointIcon";
import { hiddenAfterToggleAll } from "@/features/map/view/legendFilters";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import {
  ChooseItemsIcon,
  ClearAllFiltersIcon,
  ClearAllLayersIcon,
  EnvironmentDataIcon,
  DisplayItemsIcon,
  RoadIcon,
  SpotDataIcon,
  type MapIconComponent,
} from "@/components/ui/icons/icons";
import { Button } from "@/components/ui/Button/Button";
import { Popover, PopoverContent, PopoverTrigger, POPOVER_COLLISION_PADDING_PX } from "@/components/ui/Popover/Popover";
import { cn } from "@/lib/cn";
import { Dot } from "@/components/ui/Dot/Dot";
import { cardVariants } from "@/components/ui/Card/Card";
import { badgeVariants } from "@/components/ui/Badge/Badge";

/** 色見本の点の直径と、線の見本の長さと太さ（px）。点は色が読める大きさにする。 */
const SWATCH_DOT_PX = 12;
const SWATCH_LINE_LENGTH_PX = 20;
const SWATCH_LINE_WIDTH_PX = 7;

/** 一覧の1行ぶんの凡例（1軸ぶん）。 */
export interface LegendFilterSummaryAxis {
  /** 軸の名前（例:「路面の種類」）。 */
  label: string;
  legend: readonly LegendEntry[];
  hiddenKeys: readonly string[];
  /** 非表示キーの保存先の軸id。**これを持つ軸だけが絞り込める**——配信元が色を焼き込み済みで
   * カテゴリ単位に絞れない軸（降水・風・災害の危険度等）は持たず、読み取り専用の凡例になる。 */
  axisId?: string;
}

export interface OverlayLayerChip {
  id: MapLayerId;
  label: string;
  icon: MapIconComponent;
  on: boolean;
  /** 行のtitle（ONにすると何が出るか）。 */
  title?: string;
  /** ▶を開いたとき**凡例の代わりに**出す案内（例:「ズームインすると表示されます」）。案内が出るのは
   * 「ONにしても何も出ない」状態だけで、そのときの凡例は地図に無い色見本の表になるため。 */
  notice?: string | null;
  /** ▶を開いたときの、軸ごとの全カテゴリの内訳（表示中・非表示のどちらも含む）。 */
  legendDetails?: readonly LegendFilterSummaryAxis[];
  category?: MapLayerCategory;
  /** 行のⓘから開く、descriptionより詳しい説明。 */
  panelHint?: string;
  /** データの取得状態。ONの間だけ状態のドットと▶の中の一文で出す。 */
  dataStatus?: LayerDataStatus;
}

interface MapOverlayControlsProps {
  layers: readonly OverlayLayerChip[];
  onToggle: (id: MapLayerId, on: boolean) => void;
  /** ▶の中の1行の表示/非表示を切り替える（`axisId`を持つ軸だけ）。保存先はレンズの凡例と同じ。 */
  onLegendEntryToggle: (axisId: string, key: string) => void;
  /** ▶の中の1軸をまとめて表示/非表示にする。 */
  onLegendAxisSetHidden: (axisId: string, hiddenKeys: string[]) => void;
  /** 一覧の行を全部OFFにする（既定へ戻すのではない）。 */
  onHideAllLayers: () => void;
  /** 地図に出しているもの（色分けと、出しているレイヤー）の凡例で隠している行があるか。色分けの凡例は一覧の外にあるため、呼ぶ側が数える。 */
  anyLegendHidden: boolean;
  /** 凡例で隠した行を全部戻す。 */
  onShowAllLegendRows: () => void;
}

const MAP_OVERLAY_GROUP_ICONS: Record<MapOverlayGroup, (props: { size?: number }) => ReactElement> = {
  road: RoadIcon,
  environment: EnvironmentDataIcon,
  spot: SpotDataIcon,
};

/** 群の見出しの色。どの群の行かを一覧の中で見分ける。 */
const GROUP_COLORS = {
  road: { color: "var(--color-group-road)" },
  environment: { color: "var(--color-group-environment)" },
  spot: { color: "var(--color-group-spot)" },
} satisfies Record<MapOverlayGroup, CSSProperties>;

/** 画面の名前（「表示」のボタンが開く一覧の見出し）。 */
const LIST_SCREEN_NAME = "地図に出す情報";

const LIST_USAGE =
  "チェックを入れた情報を地図に重ね、外すと消します。▶で凡例を開くと、段階ごとに隠せます。漏斗の印は、一部を隠している合図です。";

/** 色見本。パネルへ直に、地図と同じ形（線なら線、点なら点、絵記号の点なら絵記号）で置く——明るい台に載せると、暗いパネルの上では台の
 * 白が色より目立ち、明るい色は台に溶ける。線の行は地図の線より太く、大きさで意味を示す行は地図の点と同じ直径で出す。
 * 見本の枠の幅はそろえ、ラベルの位置を行ごとにずらさない。 */
function renderSwatch(entry: LegendEntry) {
  if (entry.glyph !== undefined) {
    return (
      <span aria-hidden="true" className="inline-flex w-6 flex-shrink-0 items-center justify-center">
        <PointIconSwatch
          color={entry.color}
          glyph={entry.glyph}
          className={cn("rounded-[4px]", LEGEND_SWATCH_RING_CLASS)}
        />
      </span>
    );
  }
  const size = entry.line
    ? { width: SWATCH_LINE_LENGTH_PX, height: SWATCH_LINE_WIDTH_PX }
    : entry.diameterPx !== undefined
      ? { width: entry.diameterPx, height: entry.diameterPx }
      : { width: SWATCH_DOT_PX, height: SWATCH_DOT_PX };
  return (
    <span aria-hidden="true" className="inline-flex w-6 flex-shrink-0 items-center justify-center">
      <span
        className={cn("rounded-full", LEGEND_SWATCH_RING_CLASS)}
        style={{ background: legendSwatchBackground(entry), ...size }}
      />
    </span>
  );
}

// 「不明・他」等の受け皿は他の項目と同列の判定値ではないため区切る。
const FALLBACK_ROW_CLASS = "mt-1 border-t border-dashed border-[var(--color-border)] pt-1";

/** ▶の中の内訳。軸の全カテゴリを並べ、`axisId`を持つ軸はその場で絞り込める。持たない軸は非表示分を薄く見せる。 */
function LegendDetails({
  axes,
  onEntryToggle,
  onAxisSetHidden,
}: {
  axes: readonly LegendFilterSummaryAxis[];
  onEntryToggle: (axisId: string, key: string) => void;
  onAxisSetHidden: (axisId: string, hiddenKeys: string[]) => void;
}) {
  return (
    <div
      className="flex flex-col gap-2"
      data-usage="チェックを外した段階は、地図から隠れます。見出しのチェックで、その全部をまとめて切り替えます。"
    >
      {axes.map(({ axisId, ...axis }, axisIndex) => (
        <div key={axisId ?? axisIndex} className="flex flex-col gap-1">
          {axisId ? (
            <>
              <label className="flex cursor-pointer items-center gap-1.5">
                <Checkbox
                  checked={axis.hiddenKeys.length === 0}
                  onCheckedChange={() => onAxisSetHidden(axisId, hiddenAfterToggleAll(axis.legend, axis.hiddenKeys))}
                  aria-label={axis.label ? `${axis.label}をまとめて表示/非表示` : "凡例の全段階をまとめて表示/非表示"}
                />
                <span className="text-[length:var(--font-size-xs)] font-bold text-[var(--color-neutral)]">
                  {/* 軸の名前が無いのは、軸が1本だけでチップ名で足りる凡例（道の線）。地図の色分けと同じ名前にする。 */}
                  {axis.label || "凡例"}
                </span>
              </label>
              <LegendCheckboxList
                legend={axis.legend}
                hiddenKeys={axis.hiddenKeys}
                onToggle={(key) => onEntryToggle(axisId, key)}
                listClassName="m-0 flex list-none flex-col gap-0.5 p-0"
                rowClassName="flex items-center gap-1.5 text-[length:var(--font-size-sm)]"
                rowFallbackClassName={FALLBACK_ROW_CLASS}
                renderSwatch={renderSwatch}
              />
            </>
          ) : (
            <>
              {axis.label && (
                <div className="text-[length:var(--font-size-xs)] font-bold text-[var(--color-neutral)]">
                  {axis.label}
                </div>
              )}
              <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                {axis.legend.map((entry) => {
                  const hidden = axis.hiddenKeys.includes(entry.key);
                  return (
                    <li key={entry.key} className={cn(entry.isFallback && FALLBACK_ROW_CLASS)}>
                      <LegendRow entry={entry}>
                        <div
                          className={cn(
                            "flex items-center gap-1.5 text-[length:var(--font-size-sm)]",
                            hidden && "opacity-50",
                          )}
                        >
                          {renderSwatch(entry)}
                          <span className="min-w-0 flex-1">{entry.label}</span>
                          {hidden && <span className={badgeVariants({ variant: "outline" })}>非表示</span>}
                        </div>
                      </LegendRow>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

/** 地図の上に浮かせる一覧。画面の端・下端に収まる大きさはRadixが測り、ⓘと▶は一覧の中の行の下に開く——一覧の上に
 * 別の浮きパネルを重ねると、スマホの幅では行そのものを覆い、下端で切れる。重なり順は`Popover`の既定（下部シートより上）の
 * まま——下端まで伸びた一覧がスマホの下部シート・タブバーの下へ潜ると、潜った行を押せない。 */
const FLOATING_PANEL_CLASS = cn(
  cardVariants({ variant: "glass" }),
  "max-w-[min(calc(100vw-2*var(--space-3)),var(--radix-popover-content-available-width))] overflow-y-auto px-3 py-2",
);

const FILTERED_LABEL = "絞り込み中";

// たたんだ群と、「表示する項目を選ぶ」で外した項目は次の訪問でも保つ。ⓘ・▶の開閉は一時の確かめなので保たない。
const COLLAPSED_GROUPS_STORAGE_KEY = "ridecompass:map-overlay-collapsed-groups";
const HIDDEN_IDS_STORAGE_KEY = "ridecompass:map-overlay-hidden-ids";

/** 外した項目の保存の形は`<群>:<レイヤーid>`。 */
function hiddenKeyOf(group: MapOverlayGroup, id: MapLayerId): string {
  return `${group}:${id}`;
}

function readStringArray(raw: string): string[] | null {
  const parsed: unknown = JSON.parse(raw);
  return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === "string") : null;
}

const storedStringArray = {
  serialize: (values: readonly string[]) => JSON.stringify(values),
  deserialize: readStringArray,
};

/** 凡例の絞り込みで一部を隠している合図（漏斗の形）。絞り込みは保存されるため、欠けた地図を「データが無い」と読ませない。 */
function FilteredMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block h-2 w-2.5 flex-shrink-0 bg-current [clip-path:polygon(0_0,100%_0,62%_50%,62%_100%,38%_100%,38%_50%)]",
        className,
      )}
    />
  );
}

/** ONのレイヤーが凡例の絞り込みで一部を隠しているか。OFFの間は地図に何も出さないため数えない。 */
export function isLegendFiltered(layer: OverlayLayerChip): boolean {
  return layer.on && (layer.legendDetails ?? []).some((axis) => axis.hiddenKeys.length > 0);
}

/** 状態のドットの意味を文で読ませる置き場は▶の中（`title`はスマホでは出ない）。 */
function dataStatusNotice(layer: OverlayLayerChip): string | null {
  if (!layer.on) return null;
  return layerDataStatusNotice(layer.dataStatus);
}

/** ▶の中身。無ければ▶自体を出さない（開いても空になる）。 */
function panelContentFor(
  layer: OverlayLayerChip,
  handlers: Pick<MapOverlayControlsProps, "onLegendEntryToggle" | "onLegendAxisSetHidden">,
): ReactNode {
  if (layer.notice)
    return <p className="m-0 text-[length:var(--font-size-sm)] text-[var(--foreground)]">{layer.notice}</p>;
  const status = dataStatusNotice(layer);
  const axes = layer.legendDetails ?? [];
  if (!status && axes.length === 0) return null;
  return (
    <>
      {status && (
        <p className="mb-2 text-[length:var(--font-size-sm)] text-[var(--foreground)]" role="status">
          {status}
        </p>
      )}
      <LegendDetails
        axes={axes}
        onEntryToggle={handlers.onLegendEntryToggle}
        onAxisSetHidden={handlers.onLegendAxisSetHidden}
      />
    </>
  );
}

/** 一覧の1行。チェックで地図に出し入れし、ⓘで説明を、▶で凡例を行のすぐ下に開く。ⓘ・▶はチェックの`label`の外に
 * 置く——中に置くと、押したときに出し入れまで切り替わる。 */
function LayerRow({
  layer,
  panel,
  onToggle,
}: {
  layer: OverlayLayerChip;
  /** ▶で開く中身。無ければ▶を出さない。 */
  panel: ReactNode;
  onToggle: (id: MapLayerId, on: boolean) => void;
}) {
  const [hintOpen, setHintOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const hintId = useId();
  const panelId = useId();
  const showStatusDot = layer.on && layer.dataStatus != null;
  const filtered = isLegendFiltered(layer);
  const notes = [
    showStatusDot ? LAYER_DATA_STATUS_LABELS[layer.dataStatus!] : undefined,
    filtered ? FILTERED_LABEL : undefined,
  ]
    .filter(Boolean)
    .join("・");
  const title = notes ? (layer.title ? `${layer.title}[${notes}]` : notes) : layer.title;
  return (
    <li className="flex flex-col text-[length:var(--font-size-sm)]">
      <div className="flex items-center gap-1">
        <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 py-0.5" title={title}>
          <Checkbox checked={layer.on} onCheckedChange={() => onToggle(layer.id, !layer.on)} aria-label={layer.label} />
          <span aria-hidden="true" className="inline-flex w-5 flex-shrink-0 justify-center">
            <layer.icon size={16} />
          </span>
          <span className="min-w-0 flex-1">{layer.label}</span>
          {showStatusDot && <Dot aria-hidden="true" tone={layer.dataStatus} />}
          {filtered && <FilteredMark />}
        </label>
        {layer.panelHint && (
          <DescriptionToggle
            label={layer.label}
            open={hintOpen}
            descriptionId={hintId}
            usage="この情報の説明を、行のすぐ下に開きます。"
            onToggle={() => setHintOpen((current) => !current)}
          />
        )}
        {panel && (
          <Button
            variant="float"
            size="iconRound"
            className="group text-[var(--color-neutral)] shadow-none aria-expanded:border-[var(--color-accent)] aria-expanded:text-[var(--foreground)]"
            aria-expanded={panelOpen}
            aria-controls={panelOpen ? panelId : undefined}
            aria-label={`${layer.label}の凡例`}
            title="凡例"
            onClick={() => setPanelOpen((current) => !current)}
            usage="凡例を行のすぐ下に開きます。チェックを外した段階は地図から隠れます。"
          >
            <span
              aria-hidden="true"
              className="inline-block text-[0.6rem] leading-none transition-transform duration-150 group-aria-expanded:rotate-90"
            >
              ▶
            </span>
          </Button>
        )}
      </div>
      {hintOpen && <RowDescription id={hintId}>{layer.panelHint}</RowDescription>}
      {panel && panelOpen && (
        <div
          id={panelId}
          role="region"
          aria-label={`${layer.label}の内訳`}
          className="mt-0.5 mb-1.5 ml-6 border-l-2 border-[var(--color-border)] pl-2"
        >
          {panel}
        </div>
      )}
    </li>
  );
}

/** 群の中で一覧に並べる項目を選ぶ。外した項目は、群を開いても並べない。 */
function ItemChooser({
  label,
  members,
  isHidden,
  onToggleHidden,
  onSetAllHidden,
}: {
  label: string;
  members: readonly OverlayLayerChip[];
  isHidden: (member: OverlayLayerChip) => boolean;
  onToggleHidden: (member: OverlayLayerChip) => void;
  onSetAllHidden: (hidden: boolean) => void;
}) {
  const allListed = members.every((member) => !isHidden(member));
  return (
    <ul
      className="m-0 flex list-none flex-col gap-0.5 py-0.5 pl-0"
      data-usage="チェックを外した項目は、この一覧に並べません。地図に出していれば消えます。"
    >
      {/* 1つのチェックボックスで両方向を兼ねる（凡例の軸の見出しと同じ）。 */}
      <li data-usage="この群の項目をまとめて選びます。全部並んでいれば全部外し、1つでも外れていれば全部並べます。">
        <label className="flex cursor-pointer items-center gap-1.5 py-0.5 text-[length:var(--font-size-sm)] font-bold">
          <Checkbox
            checked={allListed}
            onCheckedChange={() => onSetAllHidden(allListed)}
            aria-label={`${label}の項目をすべて選ぶ/外す`}
          />
          すべて
        </label>
      </li>
      {members.map((member) => {
        const hidden = isHidden(member);
        return (
          <li key={member.id}>
            <label className="flex cursor-pointer items-center gap-1.5 py-0.5 text-[length:var(--font-size-sm)]">
              <Checkbox
                checked={!hidden}
                onCheckedChange={() => onToggleHidden(member)}
                aria-label={`${member.label}を一覧に並べる`}
              />
              <span aria-hidden="true" className="inline-flex w-5 flex-shrink-0 justify-center">
                <member.icon size={16} />
              </span>
              <span className="min-w-0 flex-1">{member.label}</span>
            </label>
          </li>
        );
      })}
    </ul>
  );
}

// 地図に重ねる情報の出し入れの入口（「表示」のボタン）と、押すと開く一覧。レイヤー固有の知識を持たない描画係で、
// レイヤーが増えてもここは変わらない（群の分け方と並びはレイヤーカタログから導く）。置き場は呼び出し側が決める。
export default function MapOverlayControls({
  layers,
  onToggle,
  onLegendEntryToggle,
  onLegendAxisSetHidden,
  onHideAllLayers,
  anyLegendHidden,
  onShowAllLegendRows,
}: MapOverlayControlsProps) {
  const handlers = { onLegendEntryToggle, onLegendAxisSetHidden };
  const shownCount = layers.filter((layer) => layer.on).length;
  const anyFiltered = layers.some(isLegendFiltered);
  const [collapsedGroups, setCollapsedGroups] = useStoredState<readonly string[]>(
    COLLAPSED_GROUPS_STORAGE_KEY,
    [],
    storedStringArray,
  );
  const [hiddenIds, setHiddenIds] = useStoredState<readonly string[]>(HIDDEN_IDS_STORAGE_KEY, [], storedStringArray);
  const [choosingGroup, setChoosingGroup] = useState<MapOverlayGroup | null>(null);

  function toggleCollapsed(group: MapOverlayGroup) {
    setCollapsedGroups((prev) => (prev.includes(group) ? prev.filter((g) => g !== group) : [...prev, group]));
  }

  /** 外した項目のレイヤーがONならOFFにする（一覧から消えるとOFFにする手段が無くなる）。並べ直してもONにはしない。 */
  function toggleHidden(group: MapOverlayGroup, member: OverlayLayerChip) {
    const key = hiddenKeyOf(group, member.id);
    const hiding = !hiddenIds.includes(key);
    setHiddenIds((prev) => (hiding ? [...prev, key] : prev.filter((id) => id !== key)));
    if (hiding && member.on) onToggle(member.id, false);
  }

  /** 群の項目をまとめて外す・並べる。1つずつ外すときと同じく、外す項目のONはOFFにし、並べ直してもONにはしない。 */
  function setAllHidden(group: MapOverlayGroup, members: readonly OverlayLayerChip[], hiding: boolean) {
    const keys = members.map((member) => hiddenKeyOf(group, member.id));
    setHiddenIds((prev) =>
      hiding ? [...prev, ...keys.filter((key) => !prev.includes(key))] : prev.filter((id) => !keys.includes(id)),
    );
    if (hiding) for (const member of members) if (member.on) onToggle(member.id, false);
  }

  const groups = MAP_OVERLAY_GROUP_ORDER.flatMap((group) => {
    const members = MAP_LAYER_CATEGORY_ORDER.flatMap((category) =>
      layers.filter((layer) => layer.category === category && mapOverlayGroupFor(layer) === group),
    );
    if (members.length === 0) return [];
    const label = MAP_OVERLAY_GROUP_LABELS[group];
    const Icon = MAP_OVERLAY_GROUP_ICONS[group];
    const collapsed = collapsedGroups.includes(group);
    const choosing = choosingGroup === group;
    const isHidden = (member: OverlayLayerChip) => hiddenIds.includes(hiddenKeyOf(group, member.id));
    const listed = members.filter((member) => !isHidden(member));
    return [
      <section key={group} aria-label={label} className="flex flex-col">
        <div className="mt-1.5 flex items-center gap-1">
          <h3 className="m-0 min-w-0 flex-1 text-[length:var(--font-size-xs)] font-bold" style={GROUP_COLORS[group]}>
            <Button
              variant="ghost"
              size="bare"
              className="w-full justify-start gap-1.5 py-0.5 font-bold text-inherit hover:enabled:bg-transparent hover:enabled:text-inherit"
              aria-expanded={!collapsed}
              onClick={() => toggleCollapsed(group)}
              usage="押すと、この群の中身をたたみ、もう一度押すと開きます。"
            >
              <Icon size={14} />
              {label}
              {/* たたんでいる間は行が見えないため、見出しが行の絞り込みを示す。 */}
              {collapsed && members.some(isLegendFiltered) && <FilteredMark />}
              <span
                aria-hidden="true"
                className={cn("text-[0.6rem] transition-transform duration-150", !collapsed && "rotate-90")}
              >
                ▶
              </span>
            </Button>
          </h3>
          <Button
            variant="info"
            size="bare"
            aria-pressed={choosing}
            aria-label={`${label}の表示項目を選ぶ`}
            title="表示する項目を選ぶ"
            onClick={() => setChoosingGroup(choosing ? null : group)}
            usage="この群の一覧に並べる項目を選びます。"
          >
            <ChooseItemsIcon size={14} />
          </Button>
        </div>
        {choosing ? (
          <ItemChooser
            label={label}
            members={members}
            isHidden={isHidden}
            onToggleHidden={(member) => toggleHidden(group, member)}
            onSetAllHidden={(hiding) => setAllHidden(group, members, hiding)}
          />
        ) : (
          !collapsed && (
            <ul className="m-0 flex list-none flex-col p-0" data-usage={LIST_USAGE}>
              {listed.map((member) => (
                // 凡例はON/OFFに関わらず開ける（OFFの間に「ONにすると何が出るか」を先に確かめられる）。
                <LayerRow
                  key={member.id}
                  layer={member}
                  panel={panelContentFor(member, handlers)}
                  onToggle={onToggle}
                />
              ))}
            </ul>
          )
        )}
      </section>,
    ];
  });

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="float"
          size="bare"
          className="pointer-events-auto relative size-10 flex-none flex-col gap-0.5 rounded-md text-center leading-none"
          aria-label={LIST_SCREEN_NAME}
          title={[`${LIST_SCREEN_NAME}[${shownCount}件を表示中]`, anyFiltered ? FILTERED_LABEL : undefined]
            .filter(Boolean)
            .join("・")}
          usage="地図に重ねる情報（路面・雨雲・補給の店など）の一覧を開きます。数字は今地図に出している件数です。"
        >
          <DisplayItemsIcon size={16} />
          <span className="text-[0.6rem]">表示</span>
          {shownCount > 0 && (
            <span
              aria-hidden="true"
              className="absolute top-0.5 right-0.5 h-3.5 min-w-3.5 rounded-full bg-[var(--color-accent)] px-0.5 text-[0.55rem] leading-3.5 text-white"
            >
              {shownCount}
            </span>
          )}
          {anyFiltered && <FilteredMark className="absolute top-1 left-1" />}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="start"
        collisionPadding={POPOVER_COLLISION_PADDING_PX}
        aria-label={LIST_SCREEN_NAME}
        className={cn(FLOATING_PANEL_CLASS, "max-h-[var(--radix-popover-content-available-height)] w-72")}
      >
        <p className="m-0 font-semibold">{LIST_SCREEN_NAME}</p>
        {groups}
        <div className="mt-1.5 flex flex-col border-t border-[var(--color-border)] pt-1">
          <Button
            variant="menu"
            size="sm"
            onClick={onHideAllLayers}
            disabled={shownCount === 0}
            usage="この一覧でONにした情報を、まとめてOFFにします。"
          >
            <ClearAllLayersIcon size={15} />
            表示中のレイヤーをすべて非表示
          </Button>
          <Button
            variant="menu"
            size="sm"
            onClick={onShowAllLegendRows}
            disabled={!anyLegendHidden}
            usage="凡例のチェックを外して隠した段階を、まとめて地図に戻します（地図の色分けの凡例も）。"
          >
            <ClearAllFiltersIcon size={15} />
            絞り込みをすべて解除
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
