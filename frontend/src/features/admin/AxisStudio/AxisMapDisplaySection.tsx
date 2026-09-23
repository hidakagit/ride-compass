"use client";

// 軸スタジオの「地図の色分け・チップ・公開」の節。しきい値はまとめて入力し、その場で
// 段階の並びと色を出す——色は地図の凡例と同じ関数で作るため、ここで見えているものと
// 地図がずれない。

import { useState } from "react";
import { bandLabelsForBandCount, buildRangeLegendBands } from "@/lib/mapDisplay/mapColorLegend";
import { AXIS_ICON_PALETTE, axisIconFor } from "@/lib/mapDisplay/axisIconPalette";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { FieldLabel } from "@/components/ui/FieldLabel/FieldLabel";
import type { AxisDefinitionResponse } from "@/types/route";
import { InfoPopoverButton, SectionLabel } from "./AxisFormFields";
import { NO_MAP_BANDS_JUDGEMENT } from "@/features/admin/useMapBandsOfThresholds";
import type { MapBandsOfThresholds } from "@/features/admin/axisPreviewApi";
import {
  bandLabelsOnMap,
  formatThresholdList,
  parseThresholdList,
  resizeBandLabels,
  thresholdsKeptOnMap,
  type Draft,
} from "./axisDraft";
import { Button } from "@/components/ui/Button/Button";
import { Input, Select, Textarea } from "@/components/ui/Input/Input";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import { cardVariants } from "@/components/ui/Card/Card";
import { fieldClass } from "@/components/ui/Input/Input";

interface AxisMapDisplaySectionProps {
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  /** 編集対象（新規作成はnull）。地図表示ができない軸の注記の判定にだけ使う。 */
  editing: AxisDefinitionResponse | null;
  /** 公開済み軸は表示専用フィールドしか変えられないため、公開の切り替えを出さない。 */
  restrictedDisplayOnly: boolean;
  /** 「調整する」で一時的に下書きへ戻した軸か。保存が必ず公開へ戻すため、
   * 切り替えの代わりにその事実を出す。 */
  republishing?: boolean;
  /** 段階プレビューの配色・単位（親が軸カタログから渡す）。 */
  mapBandColors?: (boundaries: readonly number[]) => readonly string[];
  mapValueUnit: string;
  /** 入力したしきい値が地図でどの段になるか（判定はbackend、親が取得して渡す）。 */
  mapBands?: MapBandsOfThresholds;
  /** まとめ入力が読めない間は保存させないため、親の検証へ伝える。 */
  onThresholdErrorChange: (error: string | null) => void;
}

export function AxisMapDisplaySection({
  draft,
  setDraft,
  editing,
  restrictedDisplayOnly,
  republishing = false,
  mapBandColors,
  mapValueUnit,
  mapBands = NO_MAP_BANDS_JUDGEMENT,
  onThresholdErrorChange,
}: AxisMapDisplaySectionProps) {
  const thresholdsDroppedOnMap = mapBands.droppedOnMap;
  const [thresholdText, setThresholdText] = useState(() => formatThresholdList(draft.displayThresholdsOverride ?? []));
  const [thresholdError, setThresholdErrorState] = useState<string | null>(null);

  function setThresholdError(next: string | null) {
    setThresholdErrorState(next);
    onThresholdErrorChange(next);
  }

  // 色分けのしきい値（display_thresholds_override）は境界値の並びをまとめて入力する。
  // 入力欄の文字列はこのコンポーネントが持ち、読めた時だけdraftへ反映する——読めない
  // 途中の状態でdraftを書き換えると、直前に入っていた並びが消えてしまう。読めないまま
  // 保存しようとした場合はフォームの検証が止める（下書きの値で黙って保存させない）。
  function applyThresholdText(text: string) {
    setThresholdText(text);
    const { values, error } = parseThresholdList(text);
    setThresholdError(error);
    if (error) return;
    setDraft((d) => ({
      ...d,
      displayThresholdsOverride: values,
      // 段階数（しきい値+1）が変わったら体感ラベルの件数も合わせる。まとめて入れ替えると
      // 段階数が何段階も動くため、1件ずつの増減では追従できない。
      displayBandLabelsOverride:
        d.displayBandLabelsOverride && resizeBandLabels(d.displayBandLabelsOverride, values.length + 1),
    }));
  }

  function enableThresholdOverride() {
    setThresholdText("");
    setThresholdError(null);
    setDraft((d) => ({ ...d, displayThresholdsOverride: [] }));
  }

  function disableThresholdOverride() {
    setThresholdText("");
    setThresholdError(null);
    // 体感ラベルはしきい値が決める段階数と対応するため、しきい値の上書き自体をやめるときは
    // 体感ラベルの上書きも一緒に解除する（残すとbackend側の「体感ラベルはしきい値の
    // 上書きが設定済みでなければならない」に反する）。
    setDraft((d) => ({ ...d, displayThresholdsOverride: null, displayBandLabelsOverride: null }));
  }

  function updateBandLabelOverrideValue(index: number, value: string) {
    setDraft((d) => ({
      ...d,
      displayBandLabelsOverride: (d.displayBandLabelsOverride ?? []).map((v, i) => (i === index ? value : v)),
    }));
  }

  /** いま入力されているしきい値が地図でどう見えるか（段階のレンジ・体感ラベル・色）を
   * そのまま描く。段は地図が作るものだけ（地図では効かない値は除く）で数え、凡例の組み立ては
   * 地図と同じ`buildRangeLegendBands`を通すため、ここで見えているものと地図の凡例がずれる
   * ことがない。色は親から渡された軸の配色（`mapBandColors`）で、地図に出る経路がまだ
   * 決まっていない軸では色を持たない。 */
  function renderBandPreview() {
    const entered = draft.displayThresholdsOverride ?? [];
    if (entered.length === 0) return null;
    const boundaries = thresholdsKeptOnMap(entered, thresholdsDroppedOnMap);
    const bandCount = boundaries.length + 1;
    const colors = mapBandColors?.(boundaries) ?? Array.from({ length: bandCount }, () => "");
    const labels = bandLabelsForBandCount(
      draft.displayBandLabelsOverride && bandLabelsOnMap(draft.displayBandLabelsOverride, mapBands.bandsOnMap),
      bandCount,
    );
    const bands = buildRangeLegendBands(boundaries, colors, mapValueUnit, labels);
    return (
      <div className="mt-2" aria-label={`色分けプレビュー（${bandCount}段階）`}>
        <p className={cn(textVariants({ variant: "hint" }), "mb-1")}>{bandCount}段階になります</p>
        <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-x-2 gap-y-0.5 p-0">
          {bands.map((band) => (
            <li key={band.key} className="flex items-center gap-1.5 text-[length:var(--font-size-sm)] tabular-nums">
              {band.color && (
                <span
                  aria-hidden="true"
                  className="inline-block h-2 w-3.5 shrink-0 rounded-[1px]"
                  style={{ background: band.color }}
                />
              )}
              {band.label}
            </li>
          ))}
        </ul>
        {!mapBandColors && (
          <p className={textVariants({ variant: "hint" })}>
            この軸が地図で使う配色はまだ決まっていません（公開して地図に出ると色が付きます）。
          </p>
        )}
      </div>
    );
  }

  function enableBandLabelsOverride() {
    setDraft((d) => ({
      ...d,
      displayBandLabelsOverride: resizeBandLabels([], (d.displayThresholdsOverride ?? []).length + 1),
    }));
  }

  function disableBandLabelsOverride() {
    setDraft((d) => ({ ...d, displayBandLabelsOverride: null }));
  }

  // 選択中iconIdのプレビュー表示用。axisIconFor自体はaxisIconPalette.tsxの固定辞書を
  // 引くだけの純関数だが、react-hooks/static-componentsのeslintルールはコンポーネント
  // 本体直下で`const X = fn(); <X/>`という形を「レンダー毎にコンポーネントを新規生成
  // している」と静的に誤検知する（MapOverlayControls.tsxのrenderRawMemberTile等、
  // ネストした関数内では同じ形でも誤検知しないため、ここも小さな関数に包んで回避する）。
  function renderIconPreview() {
    const PreviewIcon = axisIconFor(draft.iconId || null);
    return <PreviewIcon size={20} />;
  }

  function renderDisplayPublishFields() {
    // 自動導出もdisplay_thresholds_overrideも効かず地図表示不可
    // （kind="none"）な場合の注記。新規作成中（editingがnull）は計算済みのdisplayを
    // まだ受け取っていないため、既存軸の編集時のみ判定する（保存すればkindが確定するため、
    // 新規作成時は保存後に軸一覧から再度開けば確認できる）。
    const showMapDisplayUnavailableNote = editing !== null && editing.display.kind === "none";
    return (
      <>
        {showMapDisplayUnavailableNote && (
          <p className={textVariants({ variant: "hint" })}>
            この軸で使っている材料の一部は、まだ地図表示用のデータ取得経路が用意されていません（ルート探索のコストには反映されます）
          </p>
        )}

        <div className={cn(cardVariants({ variant: "muted" }), "flex flex-col gap-2")}>
          <SectionLabel
            label="地図の色分けしきい値(任意)"
            description="未設定のままなら自動計算されたしきい値が使われます。段階を細かく刻みたい場合だけ、境界値を小さい順にまとめて入力してください（区切りはカンマでも空白でも構いません）。下に実際の段階とその色が出ます。地図表示自体ができない軸（上の注記が出ている場合）には効果がありません。"
          />
          {draft.displayThresholdsOverride === null ? (
            <Button size="sm" className="self-start" onClick={enableThresholdOverride}>
              + しきい値を自分で設定する
            </Button>
          ) : (
            <>
              <Input
                type="text"
                className="w-full tabular-nums"
                value={thresholdText}
                aria-label="色分けのしきい値（まとめて入力）"
                placeholder="例: -10, -5, -1, 1, 2, 3"
                onChange={(e) => applyThresholdText(e.target.value)}
              />
              {thresholdError && <p className={cn(textVariants({ variant: "error" }), "mt-1")}>{thresholdError}</p>}
              {!thresholdError && thresholdsDroppedOnMap.length > 0 && (
                <div className="flex items-center gap-1">
                  <p className={cn(textVariants({ variant: "error" }), "mt-1")}>
                    地図では効かない: {formatThresholdList(thresholdsDroppedOnMap)}
                  </p>
                  <InfoPopoverButton
                    ariaLabel="地図では効かない値の説明"
                    description="点数の決め方で、この値は1つ手前の境界と同じ点数になります。地図は点数が変わらない所に段を作らないため、下の段階はこの値を除いた地図の段で出しています。刻みたい場合は、点数の決め方（0点・100点にする値や折れ点）を先に広げてください。"
                  />
                </div>
              )}
              {renderBandPreview()}
              <div className="flex flex-wrap items-center gap-3">
                <Button size="sm" onClick={disableThresholdOverride}>
                  自動計算に戻す
                </Button>
              </div>
            </>
          )}
        </div>

        {draft.displayThresholdsOverride !== null && (
          <div className={cn(cardVariants({ variant: "muted" }), "flex flex-col gap-2")}>
            <SectionLabel
              label="地図の色分け体感ラベル(任意)"
              description="未設定のままなら数値レンジ（例:「2〜6」）だけの凡例になります。段階ごとに「強い向かい風」のような体感で分かる短い言葉を添えたい場合だけ入力してください。しきい値の上書きを解除する（自動計算に戻す）と、体感ラベルの上書きも一緒に解除されます。"
            />
            {draft.displayBandLabelsOverride === null ? (
              <Button size="sm" className="self-start" onClick={enableBandLabelsOverride}>
                + 体感ラベルを設定する
              </Button>
            ) : (
              <>
                {draft.displayBandLabelsOverride.map((value, i) => (
                  <div key={i} className="flex flex-wrap items-center gap-2">
                    <Input
                      type="text"
                      value={value}
                      aria-label={`体感ラベル${i + 1}`}
                      onChange={(e) => updateBandLabelOverrideValue(i, e.target.value)}
                    />
                    {mapBands.bandsOnMap && !mapBands.bandsOnMap.includes(i) && (
                      <span className={textVariants({ variant: "hint" })}>地図には出ない</span>
                    )}
                  </div>
                ))}
                <Button size="sm" onClick={disableBandLabelsOverride}>
                  体感ラベルの設定をやめる
                </Button>
              </>
            )}
          </div>
        )}

        <div className={cn(cardVariants({ variant: "muted" }), "flex flex-col gap-2")}>
          <SectionLabel
            label="地図チップ表示要素(任意)"
            description="いずれも未設定のままでよい（アイコンは汎用アイコン、略称は表示名(label)、レイヤー一覧の説明は説明(description)がそれぞれ代わりに使われる）。"
          />
          <label className="inline-flex items-center gap-1 text-[length:var(--font-size-sm)]">
            <Checkbox
              checked={draft.showMapIcon}
              onCheckedChange={(next) => setDraft((d) => ({ ...d, showMapIcon: next }))}
              aria-label="地図に出す"
            />
            地図に出す（オフにすると地図上チップにこの軸が現れなくなります）
          </label>
          <div className={fieldClass}>
            <FieldLabel
              label="アイコン"
              description="地図チップに表示するアイコン。既存の意匠から選ぶ（新しい形状の追加はコード変更が必要）。"
            />
            <div className="flex flex-wrap items-center gap-3">
              <Select
                value={draft.iconId}
                aria-label="アイコン"
                onChange={(e) => setDraft((d) => ({ ...d, iconId: e.target.value }))}
              >
                <option value="">（未設定、汎用アイコン）</option>
                {Object.entries(AXIS_ICON_PALETTE).map(([iconId, entry]) => (
                  <option key={iconId} value={iconId}>
                    {entry.label}
                  </option>
                ))}
              </Select>
              {renderIconPreview()}
            </div>
          </div>

          <div className={fieldClass}>
            <FieldLabel
              label="チップの略称"
              description="4文字以内（地図チップは固定サイズのタイルのため必須の上限。未設定時は表示名(label)がそのまま使われるが、正式名が4文字を超える場合はここで略称を設定すること）。"
            />
            <Input
              type="text"
              value={draft.chipLabel}
              aria-label="チップの略称"
              onChange={(e) => setDraft((d) => ({ ...d, chipLabel: e.target.value }))}
              maxLength={4}
              placeholder="例: 未舗装"
            />
          </div>

          <label className={fieldClass}>
            地図のレイヤー一覧向け説明文(panel_hint)
            <Textarea
              value={draft.panelHint}
              onChange={(e) => setDraft((d) => ({ ...d, panelHint: e.target.value }))}
              rows={2}
              placeholder="一般ユーザー向けに噛み砕いた説明文（未設定時は説明(description)がそのまま使われる）"
            />
          </label>
        </div>

        {/* 制限モード（公開済み軸を表示専用フィールドだけ編集）では
            is_publishedを変更させない（変更するとcheck_publish_immutability/
            is_cosmetic_only_updateの表示専用フィールドのみという前提から外れ、backend側で
            拒否される）。公開状態の切り替えは「非公開に戻す」専用ボタン（AxisStudio.tsx）
            に導線を一本化済み。 */}
        {/* 「調整する」の最中は、保存が必ず公開へ戻す。切り替えを出すと、チェックを外して
            保存しても公開へ戻り、画面の操作結果が無言で反転する（design-principles.md
            「1つの状態は1つの場所でだけ操作する」）。ここでは事実だけを示す。 */}
        {republishing ? (
          <p className={textVariants({ variant: "hint" })}>
            「調整する」で一時的に下書きへ戻しています。保存すると公開へ戻ります。
          </p>
        ) : (
          !restrictedDisplayOnly && (
            <label className="inline-flex items-center gap-1 text-[length:var(--font-size-sm)]">
              <Checkbox
                checked={draft.isPublished}
                onCheckedChange={(next) => setDraft((d) => ({ ...d, isPublished: next }))}
                aria-label="公開する"
              />
              公開する（一般向けルート設定画面に表示。公開後は更新・削除ができなくなります——改良は複製から）
            </label>
          )
        )}
      </>
    );
  }

  return renderDisplayPublishFields();
}
