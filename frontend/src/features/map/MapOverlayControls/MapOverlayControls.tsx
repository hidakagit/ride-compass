"use client";

import { useEffect, useState, type CSSProperties, type ReactElement, type ReactNode } from "react";
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
import { legendSwatchBackground, type LegendEntry } from "@/lib/mapDisplay/legendFilter";
import { mapDisplay } from "@/types/generated/mapDisplay";
import LegendCheckboxList from "@/features/map/LegendCheckboxList/LegendCheckboxList";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import {
  EnvironmentDataIcon,
  InfoIcon,
  RoadIcon,
  SpotDataIcon,
  type MapIconComponent,
} from "@/components/ui/icons/icons";
import { Button } from "@/components/ui/Button/Button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { cn } from "@/lib/cn";
import { Dot } from "@/components/ui/Dot/Dot";
import { cardVariants } from "@/components/ui/Card/Card";
import { badgeVariants } from "@/components/ui/Badge/Badge";

/** 色見本の点の直径と、線の見本の長さ（px）。点は色が読める大きさにする。 */
const SWATCH_DOT_PX = 12;
const SWATCH_LINE_LENGTH_PX = 20;

/** 地図上のチップ1つ分の凡例（1軸ぶん）。 */
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
  /** チップ下の短い表記（未指定ならlabel）。 */
  chipLabel?: string;
  on: boolean;
  disabled?: boolean;
  /** チップのtitle（ONにすると何が出るか、disabledなら使えない理由）。 */
  title?: string;
  /** ▶を開いたとき**凡例の代わりに**出す案内（例:「ズームインすると表示されます」）。案内が出るのは
   * 「ONにしても何も出ない」状態だけで、そのときの凡例は地図に無い色見本の表になるため。 */
  notice?: string | null;
  /** ▶を開いたときの、軸ごとの全カテゴリの内訳（表示中・非表示のどちらも含む）。 */
  legendDetails?: readonly LegendFilterSummaryAxis[];
  category?: MapLayerCategory;
  dataNature?: MapLayerDataNature;
  /** 軸スタジオ由来のレイヤーか。渡し漏れると専用way値配信軸が単独チップとして地図へ出る。 */
  axisStudioLayer?: boolean;
  /** 「表示する項目を選ぶ」パネルで、この項目のⓘから開く説明。 */
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
}

const MAP_OVERLAY_GROUP_ICONS: Record<MapOverlayGroup, (props: { size?: number }) => ReactElement> = {
  road: RoadIcon,
  environment: EnvironmentDataIcon,
  spot: SpotDataIcon,
};

/** グループの色。見出しとメンバーが同じ色を持ち、縦に並んだチップがどのグループの一員か一目で分かる。 */
const GROUP_TINTS = {
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

// 開いたグループと、「表示する項目を選ぶ」で隠した項目は次の訪問でも保つ。▶の内訳の開閉は一時的な確認なので保たない。
const EXPANDED_GROUPS_STORAGE_KEY = "ridecompass:map-overlay-expanded-groups";
const HIDDEN_IDS_STORAGE_KEY = "ridecompass:map-overlay-hidden-ids";

/** 保存の形は`group:<グループ>`の並び。 */
function expandKey(group: MapOverlayGroup): string {
  return `group:${group}`;
}

/** 開いたままにできるグループの数を超えたぶんを、古く開いたものから畳む。保存済みの値にも効かせる。 */
function withinExpandedLimit(groups: readonly MapOverlayGroup[]): MapOverlayGroup[] {
  return groups.slice(Math.max(0, groups.length - MAP_OVERLAY_MAX_EXPANDED_GROUPS));
}

function readStringArray(raw: string): string[] | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === "string") : null;
  } catch {
    return null;
  }
}

/** 色見本。パネルへ直に、地図と同じ形（線なら線、点なら点）で置く——明るい台に載せると、暗いパネルの上では台の
 * 白が色より目立ち、明るい色は台に溶ける。線の行は地図と同じ太さ、大きさで意味を示す行は地図の点と同じ直径で出す。
 * 見本の枠の幅はそろえ、ラベルの位置を行ごとにずらさない。 */
function renderSwatch(entry: LegendEntry) {
  const size = entry.line
    ? { width: SWATCH_LINE_LENGTH_PX, height: mapDisplay.road.lineWidthPx }
    : entry.diameterPx !== undefined
      ? { width: entry.diameterPx, height: entry.diameterPx }
      : { width: SWATCH_DOT_PX, height: SWATCH_DOT_PX };
  return (
    <span aria-hidden="true" className="inline-flex w-6 flex-shrink-0 items-center justify-center">
      <span className="rounded-full" style={{ background: legendSwatchBackground(entry), ...size }} />
    </span>
  );
}

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
    <div className="flex flex-col gap-2">
      {axes.map((axis, axisIndex) => (
        <div key={axis.axisId ?? axis.label ?? axisIndex} className="flex flex-col gap-1">
          {axis.axisId ? (
            // 1つのチェックボックスで両方向を兼ねる（全部表示中なら全部隠す、1つでも隠れていれば全部出す）。
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
              listClassName="m-0 flex list-none flex-col gap-0.5 p-0"
              rowClassName="flex items-center gap-1.5 text-[length:var(--font-size-sm)]"
              rowFallbackClassName="mt-1 border-t border-dashed border-[var(--color-border)] pt-1"
              renderSwatch={renderSwatch}
            />
          ) : (
            <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
              {axis.legend.map((entry) => {
                const hidden = axis.hiddenKeys.includes(entry.key);
                return (
                  <li
                    key={entry.key}
                    className={cn(
                      "flex items-center gap-1.5 text-[length:var(--font-size-sm)]",
                      hidden && "opacity-50",
                      // 「不明・他」等の受け皿は他の項目と同列の判定値ではないため区切る。
                      entry.isFallback && "mt-1 border-t border-dashed border-[var(--color-border)] pt-1",
                    )}
                  >
                    {renderSwatch(entry)}
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

/** 地図上のチップ（アイコン＋短いラベルを縦に積む）。枠線の太さが、グループ・ON/展開の状態を読む手がかり。 */
function chipClass({ tinted, header, on }: { tinted: boolean; header: boolean; on: boolean }): string {
  return cn(
    "relative min-w-13 w-max flex-col gap-0.5 rounded-md border-2 p-1 text-center leading-[1.15] disabled:text-[var(--color-neutral)] disabled:opacity-100",
    tinted && "border-[var(--tint)] hover:enabled:border-[var(--tint)]",
    // 見出しはメンバーのON/OFFを表さないため青を使わない（「グループの内容が地図に出ている」と読まれる）。
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

/** 地図の上に浮かせる内訳パネル。画面の端・下端に収まる大きさはRadixが測る。 */
const DETAIL_PANEL_CLASS = cn(
  cardVariants({ variant: "glass" }),
  "z-[var(--z-map-detail)] max-h-[min(45vh,16rem,var(--radix-popover-content-available-height))] w-72 max-w-[min(calc(100vw-2*var(--space-3)),var(--radix-popover-content-available-width))] overflow-y-auto px-3 py-2",
);

/** チップの行はそれぞれ高さが違うため、吸着させずに離した位置で止める。先頭を上端に揃え、末尾より先へは送らない。 */
const CHIP_ROW_OPTIONS = { axis: "y", align: "start", dragFree: true, containScroll: "trimSnaps" } as const;

const FILTERED_LABEL = "絞り込み中";

/** ONのレイヤーが凡例の絞り込みで一部を隠しているか。OFFの間は地図に何も出さないため数えない。 */
function isLegendFiltered(layer: OverlayLayerChip): boolean {
  return layer.on && !layer.disabled && (layer.legendDetails ?? []).some((axis) => axis.hiddenKeys.length > 0);
}

/** 状態のドットの意味を文で読ませる置き場は▶の中（`title`はスマホでは出ない）。 */
function dataStatusNotice(layer: OverlayLayerChip): string | null {
  if (!layer.on || layer.disabled || !layer.dataStatus) return null;
  return LAYER_DATA_STATUS_LABELS[layer.dataStatus];
}

/** ▶の中身。無ければ▶自体を出さない（開いても空になる）。 */
function panelContentFor(
  layer: OverlayLayerChip,
  handlers: Pick<MapOverlayControlsProps, "onLegendEntryToggle" | "onLegendAxisSetHidden">,
): ReactNode {
  if (layer.disabled) return null;
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

/** チップの横の丸いボタンから開く、地図の上に浮かせたパネル。 */
function DetailPopover({
  triggerLabel,
  title,
  regionLabel,
  side,
  trigger,
  children,
}: {
  triggerLabel: string;
  title: string;
  regionLabel: string;
  side: "right" | "bottom";
  trigger: ReactNode;
  children: ReactNode;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="float"
          size="iconRound"
          className={cn("group", ROUND_TOGGLE)}
          aria-label={triggerLabel}
          title={title}
        >
          {trigger}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        side={side}
        align="start"
        collisionPadding={8}
        aria-label={regionLabel}
        className={DETAIL_PANEL_CLASS}
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}

function ChipButton({
  Icon,
  label,
  chipLabel,
  on,
  pressed,
  expanded,
  disabled,
  title,
  onTap,
  groupTint,
  dataStatus,
  filtered = false,
  panel,
}: {
  Icon: (props: { size?: number }) => ReactElement;
  label: string;
  chipLabel: string;
  /** 見た目のON（塗りつぶし）。 */
  on: boolean;
  /** ON/OFFのチップなら押下状態。グループの見出しは代わりに`expanded`を持つ。 */
  pressed?: boolean;
  expanded?: boolean;
  disabled?: boolean;
  title?: string;
  onTap: () => void;
  /** 属するグループ。無ければ（ルート等）無色。 */
  groupTint?: MapOverlayGroup;
  dataStatus?: LayerDataStatus;
  /** 凡例の絞り込みで一部を隠しているか（絞り込みは保存されるため、欠けた地図を「データが無い」と読ませない）。 */
  filtered?: boolean;
  /** ▶で開く中身。無ければ▶を出さない。 */
  panel?: ReactNode;
}) {
  const showStatusDot = on && dataStatus != null;
  const titleNotes = [
    showStatusDot ? LAYER_DATA_STATUS_LABELS[dataStatus] : undefined,
    filtered ? FILTERED_LABEL : undefined,
  ]
    .filter(Boolean)
    .join("・");
  const chipTitle = titleNotes ? (title ? `${title}（${titleNotes}）` : titleNotes) : title;
  return (
    <div data-slot="chip-row-item" className="flex flex-shrink-0 items-center gap-1 self-start">
      <Button
        variant="float"
        size="bare"
        aria-pressed={pressed}
        aria-expanded={expanded}
        disabled={disabled}
        title={chipTitle}
        onClick={onTap}
        style={groupTint ? GROUP_TINTS[groupTint] : undefined}
        className={chipClass({ tinted: groupTint !== undefined, header: expanded !== undefined, on })}
      >
        <Icon />
        {showStatusDot && <Dot aria-hidden="true" tone={dataStatus} className="absolute top-0.5 right-0.5" />}
        {filtered && (
          <span
            aria-hidden="true"
            className="absolute top-1 left-1 h-2 w-2.5 bg-current [clip-path:polygon(0_0,100%_0,62%_50%,62%_100%,38%_100%,38%_50%)]"
          />
        )}
        <span className="whitespace-nowrap text-[0.58rem]">{chipLabel}</span>
      </Button>
      {panel && (
        <DetailPopover
          triggerLabel={`${label}の凡例`}
          title="凡例"
          regionLabel={`${label}の内訳`}
          side="right"
          trigger={
            <span
              aria-hidden="true"
              className="inline-block text-[0.6rem] leading-none transition-transform duration-150 group-aria-expanded:rotate-90"
            >
              ▶
            </span>
          }
        >
          {panel}
        </DetailPopover>
      )}
    </div>
  );
}

// 地図の上に重ねるのは「地図を見ながら頻繁に切り替える」ON/OFFチップと、▶で開く凡例。レイヤー固有の知識を持たない
// 描画係で、レイヤーが増えてもここは変わらない（グループ分けと並びはレイヤーカタログから導く）。
export default function MapOverlayControls({
  layers,
  onToggle,
  onLegendEntryToggle,
  onLegendAxisSetHidden,
}: MapOverlayControlsProps) {
  const handlers = { onLegendEntryToggle, onLegendAxisSetHidden };
  const [expandedGroups, setExpandedGroups] = useStoredState<readonly MapOverlayGroup[]>(
    EXPANDED_GROUPS_STORAGE_KEY,
    [],
    {
      serialize: (groups) => JSON.stringify(groups.map(expandKey)),
      deserialize: (raw) => {
        const keys = readStringArray(raw);
        return keys && withinExpandedLimit(MAP_OVERLAY_GROUP_ORDER.filter((group) => keys.includes(expandKey(group))));
      },
    },
  );
  // 「表示する項目を選ぶ」で隠した項目。キーは`<グループ>:<レイヤーid>`。
  const [hiddenIds, setHiddenIds] = useStoredState<ReadonlySet<string>>(HIDDEN_IDS_STORAGE_KEY, new Set(), {
    serialize: (ids) => JSON.stringify([...ids]),
    deserialize: (raw) => {
      const ids = readStringArray(raw);
      return ids && new Set(ids);
    },
  });

  // チップ列が縦にはみ出したら、なぞって（PCはホイールでも）送る。▲▼はまだ隠れている側がある間だけ出す。
  const [chipRowRef, chipRowApi] = useEmblaCarousel(CHIP_ROW_OPTIONS, [WheelGesturesPlugin({ forceWheelAxis: "y" })]);
  const [hasLess, setHasLess] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  useEffect(() => {
    if (!chipRowApi) return;
    const sync = () => {
      setHasLess(chipRowApi.canScrollPrev());
      setHasMore(chipRowApi.canScrollNext());
    };
    sync();
    chipRowApi.on("select", sync).on("reInit", sync).on("scroll", sync);
    return () => {
      chipRowApi.off("select", sync).off("reInit", sync).off("scroll", sync);
    };
  }, [chipRowApi]);

  function toggleGroup(group: MapOverlayGroup) {
    setExpandedGroups((prev) =>
      prev.includes(group) ? prev.filter((g) => g !== group) : withinExpandedLimit([...prev, group]),
    );
  }

  /** 隠した項目のレイヤーがONならOFFにする（チップが消えるとOFFにする手段が無くなる）。出し直してもONにはしない。 */
  function toggleHidden(hiddenKey: string, member: OverlayLayerChip) {
    const hiding = !hiddenIds.has(hiddenKey);
    setHiddenIds((prev) => {
      const next = new Set(prev);
      if (hiding) next.add(hiddenKey);
      else next.delete(hiddenKey);
      return next;
    });
    if (hiding && member.on) onToggle(member.id, false);
  }

  function memberTile(member: OverlayLayerChip, group: MapOverlayGroup) {
    const on = member.on && !member.disabled;
    return (
      <ChipButton
        key={member.id}
        Icon={member.icon}
        label={member.label}
        chipLabel={member.chipLabel ?? member.label}
        on={on}
        pressed={on}
        disabled={member.disabled}
        title={member.title}
        onTap={() => onToggle(member.id, !member.on)}
        groupTint={group}
        dataStatus={member.dataStatus}
        filtered={isLegendFiltered(member)}
        // 凡例はON/OFFに関わらず開ける（OFFの間に「ONにすると何が出るか」を先に確かめられる）。
        panel={panelContentFor(member, handlers)}
      />
    );
  }

  /** 畳んだグループの見出しの脇に置く「表示する項目を選ぶ」。開いたグループはメンバーが見えるため出さない。 */
  function visibilitySettings(group: MapOverlayGroup, label: string, members: readonly OverlayLayerChip[]) {
    return (
      <div data-slot="chip-row-item" className="flex flex-shrink-0 items-center self-start">
        <DetailPopover
          triggerLabel={`${label}の表示項目`}
          title="表示する項目を選ぶ"
          regionLabel={`${label}の表示項目`}
          side="bottom"
          trigger={<InfoIcon size={12} />}
        >
          <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
            {members.map((member) => {
              const hiddenKey = `${group}:${member.id}`;
              const hidden = hiddenIds.has(hiddenKey);
              const name = member.chipLabel ?? member.label;
              return (
                <li key={member.id} className="flex items-center gap-1.5 text-[length:var(--font-size-sm)]">
                  <Checkbox
                    checked={!hidden}
                    onCheckedChange={() => toggleHidden(hiddenKey, member)}
                    aria-label={`${name}を${hidden ? "表示する" : "表示しない"}`}
                  />
                  <member.icon size={16} />
                  <span className="min-w-0 flex-1">{name}</span>
                  {member.panelHint && (
                    <InfoPopover triggerAriaLabel={`${name}の説明`} side="right">
                      {member.panelHint}
                    </InfoPopover>
                  )}
                </li>
              );
            })}
          </ul>
        </DetailPopover>
      </div>
    );
  }

  function groupRow(group: MapOverlayGroup, members: readonly OverlayLayerChip[]) {
    const ordered = MAP_LAYER_CATEGORY_ORDER.flatMap((category) => members.filter((m) => m.category === category));
    const expanded = expandedGroups.includes(group);
    const label = MAP_OVERLAY_GROUP_LABELS[group];
    const Icon = MAP_OVERLAY_GROUP_ICONS[group];
    return (
      // 開閉のどちらでも同じkeyの行に見出しを置き、見出しのボタンを作り直さない（作り直すとフォーカスが外れる）。
      <div
        key={expandKey(group)}
        className={expanded ? "flex flex-col gap-2 self-start" : "flex min-w-0 max-w-full items-start gap-1 self-start"}
      >
        <ChipButton
          Icon={Icon}
          label={label}
          chipLabel={label}
          on={expanded}
          expanded={expanded}
          title={`${label}[${members.length}件をタップで一覧]`}
          onTap={() => toggleGroup(group)}
          groupTint={group}
          filtered={!expanded && members.some(isLegendFiltered)}
        />
        {expanded
          ? ordered
              .filter((member) => !hiddenIds.has(`${group}:${member.id}`))
              .map((member) => memberTile(member, group))
          : visibilitySettings(group, label, ordered)}
      </div>
    );
  }

  function singleChip(layer: OverlayLayerChip) {
    const on = layer.on && !layer.disabled;
    return (
      <ChipButton
        key={layer.id}
        Icon={layer.icon}
        label={layer.label}
        chipLabel={layer.chipLabel ?? layer.label}
        on={on}
        pressed={on}
        disabled={layer.disabled}
        title={layer.title}
        onTap={() => onToggle(layer.id, !layer.on)}
        dataStatus={layer.dataStatus}
        filtered={isLegendFiltered(layer)}
        panel={on ? panelContentFor(layer, handlers) : null}
      />
    );
  }

  const rows = [
    ...MAP_OVERLAY_GROUP_ORDER.flatMap((group) => {
      const members = layers.filter((layer) => mapOverlayGroupFor(layer) === group);
      return members.length > 0 ? [groupRow(group, members)] : [];
    }),
    // どのグループにも属さないレイヤー（ルート等）は単独チップ。軸スタジオ由来のレイヤーは地図のチップに出さない。
    ...layers.filter((layer) => !mapOverlayGroupFor(layer) && !isAxisStudioLayer(layer)).map(singleChip),
  ];

  return (
    <div className="pointer-events-none absolute top-3 left-3 z-[var(--z-map-control)] flex w-max max-w-[calc(100%-2*var(--space-3)-3rem)] flex-col items-start gap-2 max-mobile:bottom-[calc(var(--space-3)+var(--mobile-tabbar-height)+var(--bottom-control-row-height,0px))]">
      {hasLess && (
        <Button
          variant="float"
          size="bare"
          className="h-6.5 self-stretch rounded-md px-1 text-[1.1rem] shadow-none"
          onClick={() => chipRowApi?.scrollPrev()}
          aria-label="上を表示"
          title="上を表示"
        >
          ▲
        </Button>
      )}
      <div className="w-max max-w-full max-h-[min(80vh,42rem)] overflow-hidden" ref={chipRowRef}>
        <div className="flex w-max max-w-full flex-col gap-2">{rows}</div>
      </div>
      {hasMore && (
        <Button
          variant="float"
          size="bare"
          className="h-6.5 self-stretch rounded-md px-1 text-[1.1rem] shadow-none"
          onClick={() => chipRowApi?.scrollNext()}
          aria-label="下を表示"
          title="下を表示"
        >
          ▼
        </Button>
      )}
    </div>
  );
}
