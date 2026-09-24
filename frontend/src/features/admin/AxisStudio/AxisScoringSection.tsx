"use client";

// 軸スタジオの「点数の決め方」の節。**材料を選べば入力欄は決まる**——数値なら
// 「この値で0点・この値で100点」、はい/いいえなら該当時と非該当時のスコア、種類なら値ごとのスコア、
// ほかの軸なら係数を掛けた合計。折れ点の並びは保存形式であって入力欄ではないので、
// 直接いじる口は詳細設定に畳んである（docs/modules/frontend/axis-studio.md参照）。

import { useScoresPreview } from "@/features/admin/useScoresPreview";
import type { ScoresPreviewRequest } from "@/features/admin/axisPreviewApi";
import { binMidpoints } from "./scoreDistribution";
import { useState } from "react";
import {
  BREAKPOINT_SHAPE_OPTIONS,
  generateBreakpoints,
  insertBreakpointAtLargestGap,
  generatorSettingsFrom,
  type BreakpointShape,
} from "./breakpointTools";
import { materialOptionText, type AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import { useMaterialValues } from "@/features/admin/useMaterialValues";
import { useAxisValueDistribution } from "@/features/admin/useAxisValueDistribution";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { InfoPopoverButton, MaterialInfoButton, SectionLabel, SliderNumberField } from "./AxisFormFields";
import { buildShape, type CategoricalRowDraft, type Draft, type TermDraft } from "./axisDraft";
import { BreakpointCurveEditor } from "./BreakpointCurveEditor";
import { DistributionPreview } from "./DistributionPreview";
import { MaterialRangeHint } from "./MaterialRangeHint";
import { Button } from "@/components/ui/Button/Button";
import { NumberInput } from "@/components/ui/NumberInput/NumberInput";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/Table/Table";
import { Input, Select } from "@/components/ui/Input/Input";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import { cardVariants } from "@/components/ui/Card/Card";
import { fieldClass } from "@/components/ui/Input/Input";

interface AxisScoringSectionProps {
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  /** 材料カタログ（実行時取得）。 */
  materialOptions: readonly AxisMaterialOption[];
  /** 「ほかの軸」を材料として選ぶための候補（他の軸の一覧）。 */
  axisTermOptions: readonly AxisMaterialOption[];
}

/** 材料の生値を折れ点の横軸(x)の値へ変換する。backend: domain/axis_definitions.py:
 * evaluate_axis_scalarの`total = value * weight`→`abs()`（preprocess="abs"の場合）と
 * 同じ変換（`terms`が1件のbreakpoint_linear軸限定、複数termの合計は対応しない）。 */
export function AxisScoringSection({ draft, setDraft, materialOptions, axisTermOptions }: AxisScoringSectionProps) {
  const selectedCategoricalDtype = materialOptions.find((m) => m.id === draft.categoricalMaterial)?.dtype;
  const { values: categoricalMaterialValues, unavailable: categoricalValuesUnavailable } = useMaterialValues(
    selectedCategoricalDtype === "categorical" ? draft.categoricalMaterial : null,
  );
  // 折れ点の自動生成フォーム（範囲＋形の3入力）。**入力のたびにdraft.breakpointsを
  // 作り直す**ため、初期値はいまの折れ点から復元する（breakpointTools.ts:
  // generatorSettingsFrom）。固定値にすると、既存の軸を開いて効き方だけを変えたときに
  // 無関係な範囲で折れ点が作り直され、較正済みの端点が黙って消える。
  // このコンポーネントは軸ごとに作り直される（AxisStudio.tsxがAxisComposerへkeyを渡す）
  // ため、初期化関数だけで足りる。
  const [generatorSeed] = useState(() => generatorSettingsFrom(draft.breakpoints));
  const [generatorZeroValue, setGeneratorZeroValue] = useState(generatorSeed.zeroValue);
  const [generatorHundredValue, setGeneratorHundredValue] = useState(generatorSeed.hundredValue);
  const [generatorShape, setGeneratorShape] = useState<BreakpointShape>(generatorSeed.shape);
  // breakpoint_linearで単一材料（他軸参照ではない）のtermを1つだけ持つ場合にのみ、その
  // 材料の参考点（reference_points）を「効き目プレビュー」「自動生成の値の目安」
  // 「曲線エディタの横軸固定」に使う。複数termの組み合わせ・他軸参照は参考点の対応が
  // 取れないため対象外。
  const primaryMaterial =
    draft.shapeKind === "breakpoint_linear" && draft.terms.length === 1
      ? materialOptions.find((m) => m.id === draft.terms[0].material)
      : undefined;
  const primaryMaterialReferencePoints = primaryMaterial?.referencePoints ?? [];
  // 分布は「材料・重み・前処理」で決まり、折れ点では変わらない。折れ点を含めない
  // キーで取得することで、折れ点のドラッグ中に通信が走らない。
  // 分布を描くのは「値ごとのスコア」（breakpoint_linear）の折れ点エディタだけ。他の形では
  // 取得しても捨てるだけで、軸や係数を触るたびにデバウンス後のPOSTが走る。
  const distributionTermsKey =
    draft.shapeKind === "breakpoint_linear"
      ? JSON.stringify([draft.preprocess, draft.terms.map((t) => [t.material, t.weight, t.required])])
      : "";
  const valueDistribution = useAxisValueDistribution(distributionTermsKey !== "", distributionTermsKey, () =>
    buildShape(draft, materialOptions),
  );
  // 分布の階級と参考点の点数・参考点の横軸の値は、backendが評価と同じ計算で返す（折れ点を動かすたびに、
  // 落ち着いたら問い合わせる）。届くまでは効き目の表と参考点のボタンを出さない。
  const scoresPreview = useScoresPreview(
    draft.shapeKind === "breakpoint_linear" && draft.terms.length > 0 && draft.breakpoints.length > 0
      ? {
          shape: buildShape(draft, materialOptions) as ScoresPreviewRequest["shape"],
          xs: binMidpoints(valueDistribution.distribution),
          material_values: primaryMaterialReferencePoints.map((p) => p.value),
        }
      : null,
  );
  const referencePoints =
    scoresPreview && scoresPreview.material_points.length === primaryMaterialReferencePoints.length
      ? primaryMaterialReferencePoints.map((p, i) => ({ ...p, ...scoresPreview.material_points[i] }))
      : [];
  // 参考点の値域（曲線エディタの横軸固定に使う）。参考点が無い・届いていなければundefinedのままで、
  // 曲線エディタはbreakpoints自体から自動スケールする。
  const breakpointReferenceRange =
    referencePoints.length > 0
      ? {
          min: Math.min(...referencePoints.map((p) => p.x)),
          max: Math.max(...referencePoints.map((p) => p.x)),
        }
      : undefined;

  // 点数のもとになるもの（材料、または他の軸）。**これの型が点数のつけ方を決める**ため、
  // 利用者に「なめらか評価／ぴったり評価」のような呼び名を選ばせない。
  const primaryMaterialId =
    draft.shapeKind === "categorical" ? draft.categoricalMaterial : (draft.terms[0]?.material ?? "");

  // 材料を1行ずつ並べる編集欄を出すか。単一の数値材料では係数は「0点/100点にする値」へ
  // 吸収されるため出さない。はい/いいえの材料を足し合わせる軸（街灯なし−50＋トンネル+50等）は
  // 係数そのものが点数の配分なので、1件でも出す。
  const showTermRows =
    draft.terms.length > 1 ||
    (draft.terms[0]?.weight ?? 1) !== 1 ||
    materialOptions.find((m) => m.id === draft.terms[0]?.material)?.dtype === "boolean";

  function selectPrimaryMaterial(id: string) {
    const isAxis = axisTermOptions.some((option) => option.id === id);
    const dtype = materialOptions.find((m) => m.id === id)?.dtype;
    setDraft((d) => {
      if (isAxis) {
        return {
          ...d,
          shapeKind: "recipe_then_breakpoint_linear",
          terms: [{ material: id, weight: 1.0, required: true }],
          preprocess: "identity",
          breakpoints: [
            [0, 0],
            [100, 100],
          ],
        };
      }
      if (dtype === "boolean" || dtype === "categorical") {
        return {
          ...d,
          shapeKind: "categorical",
          categoricalMaterial: id,
          categoricalRows:
            dtype === "categorical" && d.categoricalRows.length === 0 ? [{ value: "", score: 0 }] : d.categoricalRows,
        };
      }
      // 数値材料。既に数値で組んでいる場合は係数・折れ点を保ち、材料だけ入れ替える。
      if (d.shapeKind === "breakpoint_linear") {
        return { ...d, terms: d.terms.map((t, i) => (i === 0 ? { ...t, material: id } : t)) };
      }
      return {
        ...d,
        shapeKind: "breakpoint_linear",
        terms: [{ material: id, weight: 1.0, required: true }],
        breakpoints: [
          [0, 0],
          [10, 100],
        ],
      };
    });
  }

  /** 「0点にする値」「100点にする値」「効き方」から材料の値→スコアの変換を作り直す。
   * 折れ点の並びそのものは保存形式であって入力欄ではない——実在する軸の大半は2点の直線で、
   * 曲線は実データを見て決めるもの（較正）。直接いじる口は下の詳細設定に残してある。 */
  function applyScoringRange(zeroValue: number, hundredValue: number, shape: BreakpointShape) {
    if (zeroValue === hundredValue) return;
    setDraft((d) => ({ ...d, breakpoints: generateBreakpoints(zeroValue, hundredValue, shape) }));
  }

  function updateTerm(index: number, patch: Partial<TermDraft>) {
    setDraft((d) => ({ ...d, terms: d.terms.map((t, i) => (i === index ? { ...t, ...patch } : t)) }));
  }

  function updateBreakpoint(index: number, pos: 0 | 1, value: number) {
    setDraft((d) => ({
      ...d,
      breakpoints: d.breakpoints.map((bp, i) =>
        i === index ? ([pos === 0 ? value : bp[0], pos === 1 ? value : bp[1]] as [number, number]) : bp,
      ),
    }));
  }

  function updateCategoricalRow(index: number, patch: Partial<CategoricalRowDraft>) {
    setDraft((d) => ({
      ...d,
      categoricalRows: d.categoricalRows.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    }));
  }

  function addCategoricalRow() {
    setDraft((d) => ({ ...d, categoricalRows: [...d.categoricalRows, { value: "", score: 0 }] }));
  }

  function removeCategoricalRow(index: number) {
    setDraft((d) => ({ ...d, categoricalRows: d.categoricalRows.filter((_, i) => i !== index) }));
  }

  function renderShapeParamsStep() {
    return (
      <>
        <SectionLabel
          label="何をもとに点数をつけるか"
          description={
            "点数のつけ方はここで選んだものの型が決めます——数値なら「この値で0点・この値で100点」、" +
            "はい/いいえなら2つのスコア、種類なら値ごとのスコア、ほかの軸なら係数を掛けた合計です。"
          }
        />
        <div className="flex flex-wrap items-center gap-3">
          <Select
            aria-label="点数のもとになるもの"
            value={primaryMaterialId}
            onChange={(e) => selectPrimaryMaterial(e.target.value)}
          >
            <optgroup label="数値">
              {materialOptions
                .filter((m) => m.dtype === "numeric")
                .map((m) => (
                  <option key={m.id} value={m.id}>
                    {materialOptionText(m)}
                  </option>
                ))}
            </optgroup>
            <optgroup label="はい・いいえ / 種類">
              {materialOptions
                .filter((m) => m.dtype === "boolean" || m.dtype === "categorical")
                .map((m) => (
                  <option key={m.id} value={m.id}>
                    {materialOptionText(m)}
                  </option>
                ))}
            </optgroup>
            {axisTermOptions.length > 0 && (
              <optgroup label="ほかの軸">
                {axisTermOptions.map((m) => (
                  <option key={m.id} value={m.id}>
                    {materialOptionText(m)}
                  </option>
                ))}
              </optgroup>
            )}
          </Select>
          <MaterialInfoButton
            option={[...materialOptions, ...axisTermOptions].find((m) => m.id === primaryMaterialId)}
          />
          {draft.shapeKind !== "categorical" && draft.terms.length === 1 && (
            <>
              <label className="inline-flex items-center gap-1 text-[length:var(--font-size-sm)]">
                <Checkbox
                  checked={draft.terms[0]?.required ?? true}
                  onCheckedChange={(next) => updateTerm(0, { required: next })}
                  aria-label="必須"
                />
                必須
              </label>
              <InfoPopoverButton
                ariaLabel="「必須」の説明"
                description="この材料のデータが無い区間は、軸全体を「評価不能」として扱います。チェックを外すと、データが無い分は0として他の材料だけで評価を続けます。"
              />
            </>
          )}
        </div>
        {/* 「0=走りやすい・100=走りにくい」をこの節の先頭で1回だけ伝える
            （折れ点・カテゴリのスコア・true/falseスコアの入力欄では繰り返さない）。 */}
        <p className={textVariants({ variant: "hint" })}>スコアは0(走りやすい)〜100(走りにくい)です。</p>

        {(draft.shapeKind === "breakpoint_linear" || draft.shapeKind === "recipe_then_breakpoint_linear") && (
          <div className={cn(cardVariants({ variant: "muted" }), "flex flex-col gap-2")}>
            {draft.shapeKind === "recipe_then_breakpoint_linear" ? (
              <>
                <SectionLabel
                  label="組み合わせる軸"
                  description="各軸のスコア(0〜100)に係数(n, m…)を掛けた合計が、そのままスコアになります（nX + mYのように軸同士を重み付きで足し合わせるだけの、純粋な結合です）。"
                />
                {axisTermOptions.length === 0 && (
                  <p className={textVariants({ variant: "error" })}>
                    組み合わせられる他の軸がまだありません。先に材料から軸を1つ以上作成してから使えます。
                  </p>
                )}
              </>
            ) : (
              <SectionLabel
                label="材料"
                description="はい/いいえの材料も選べます（該当時は1、非該当時は0として係数と掛け合わされます。街灯なし・トンネルなど、複数の危険要素の有無を数えて減点・加点したい場合もここに追加してください）。複数の材料を追加すると、それぞれの「値×係数」の合計が下の折れ点でスコアへ変換されます。"
              />
            )}
            {/* booleanの材料も選べる（該当時1・非該当時0として係数と掛け合わされる、
                backend/app/domain/axis_definitions.py: evaluate_axis_scalarのBreakpointLinearShape
                分岐参照）。categoricalは非対応のまま（文字列材料と数値の掛け算はbackend側で
                エラーになる）。recipe_then_breakpoint_linearは、材料の代わりに
                他の軸(axisTermOptions)を候補にする。 */}
            {showTermRows &&
              draft.terms.map((term, i) => {
                const termOptions =
                  draft.shapeKind === "recipe_then_breakpoint_linear"
                    ? axisTermOptions
                    : materialOptions.filter((m) => m.dtype === "numeric" || m.dtype === "boolean");
                return (
                  <div key={i} className="flex flex-wrap items-center gap-2">
                    <Select value={term.material} onChange={(e) => updateTerm(i, { material: e.target.value })}>
                      {termOptions.map((m) => (
                        <option key={m.id} value={m.id}>
                          {materialOptionText(m)}
                        </option>
                      ))}
                    </Select>
                    <MaterialInfoButton option={termOptions.find((m) => m.id === term.material)} />
                    {/* 典型的な係数の範囲（±10）に絞り、範囲外の値は数値欄から直接入力する想定にした。 */}
                    <SliderNumberField
                      label="係数"
                      value={term.weight}
                      onChange={(next) => updateTerm(i, { weight: next })}
                      min={-10}
                      max={10}
                      step={0.1}
                    />
                    <label className="inline-flex items-center gap-1 text-[length:var(--font-size-sm)]">
                      <Checkbox
                        checked={term.required}
                        onCheckedChange={(next) => updateTerm(i, { required: next })}
                        aria-label="必須"
                      />
                      必須
                    </label>
                    <InfoPopoverButton
                      ariaLabel="「必須」の説明"
                      description="この材料のデータが無い区間は、軸全体を「評価不能」として扱います。チェックを外すと、データが無い分は0として他の材料だけで評価を続けます。"
                    />
                    <Button
                      size="sm"
                      onClick={() => setDraft((d) => ({ ...d, terms: d.terms.filter((_, j) => j !== i) }))}
                      disabled={draft.terms.length <= 1}
                    >
                      削除
                    </Button>
                    {/* 実データの分位は行の末尾で1行を占有させる（.termRowHintがflex-basis:100%）。
                      操作要素の間へ挟むと、狭幅の折り返しで説明文とスライダーが混ざる。
                      他の軸を組み合わせる行が持つのは軸idで、材料の分位は引けない。 */}
                    {draft.shapeKind !== "recipe_then_breakpoint_linear" && (
                      <MaterialRangeHint
                        className="basis-full"
                        materialId={term.material}
                        unit={termOptions.find((m) => m.id === term.material)?.unit}
                      />
                    )}
                  </div>
                );
              })}
            <Button
              size="sm"
              className="self-start"
              disabled={draft.shapeKind === "recipe_then_breakpoint_linear" && axisTermOptions.length === 0}
              onClick={() =>
                setDraft((d) => {
                  const termOptions =
                    d.shapeKind === "recipe_then_breakpoint_linear"
                      ? axisTermOptions
                      : materialOptions.filter((m) => m.dtype === "numeric" || m.dtype === "boolean");
                  // materialOptionsが空のとき無条件アクセスでクラッシュしないよう""へ。
                  const fallback = termOptions[0]?.id ?? materialOptions[0]?.id ?? "";
                  return { ...d, terms: [...d.terms, { material: fallback, weight: 1.0, required: false }] };
                })
              }
            >
              + {draft.shapeKind === "recipe_then_breakpoint_linear" ? "軸を足して合計する" : "材料を足して合計する"}
            </Button>

            {/* 他の軸を組み合わせる形は純粋な重み付き結合に絞り、下ごしらえ・折れ点の
                編集UIを出さない（保存時は既定値[そのまま・恒等クランプ0→0,100→100]のまま
                送信される、buildShape・selectPrimaryMaterialの設定参照）。 */}
            {draft.shapeKind === "breakpoint_linear" && (
              <>
                <label className="inline-flex items-center gap-1 text-[length:var(--font-size-sm)]">
                  <Checkbox
                    checked={draft.preprocess === "abs"}
                    onCheckedChange={(next) => setDraft((d) => ({ ...d, preprocess: next ? "abs" : "identity" }))}
                    aria-label="マイナス側も同じ強さとして扱う"
                  />
                  マイナス側も同じ強さとして扱う
                  <InfoPopoverButton
                    ariaLabel="「マイナス側も同じ強さとして扱う」の説明"
                    description={
                      "材料の値×係数の合計がマイナスでも、プラスと同じ大きさとして点数にします" +
                      "（例: 勾配は上りが+・下りが−の符号付きですが、これを付けると上り・下りのどちらでも急なほど走りにくい軸になります）。" +
                      "単一の数値材料でこれを付けた軸だけ、地図は符号つきの生値で塗ります。"
                    }
                  />
                </label>

                <SectionLabel
                  label="何点にするか"
                  description={
                    "この2つの値と効き方から、材料の値→スコアの変換を作ります。値の大小はどちら向きでも構いません" +
                    "（0点にする値の方が大きくてもよい）。細かい形は実データを見ながら決めるもので、ここでは大枠だけ決めます。" +
                    (primaryMaterial && primaryMaterialReferencePoints.length > 0
                      ? "下のボタンは材料の参考点（目安）です。"
                      : "")
                  }
                />
                <div className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-2 [&_input[type=number]]:w-18 [&_input[type=range]]:w-48">
                    <span className={cn(textVariants({ variant: "hint" }), "whitespace-nowrap")}>0点</span>
                    <NumberInput
                      commitOn="input"
                      step="any"
                      value={generatorZeroValue}
                      aria-label="0点にする値"
                      onValueChange={(next) => {
                        setGeneratorZeroValue(next);
                        applyScoringRange(next, generatorHundredValue, generatorShape);
                      }}
                    />
                  </span>
                  <span className="inline-flex items-center gap-2 [&_input[type=number]]:w-18 [&_input[type=range]]:w-48">
                    <span className={cn(textVariants({ variant: "hint" }), "whitespace-nowrap")}>100点</span>
                    <NumberInput
                      commitOn="input"
                      step="any"
                      value={generatorHundredValue}
                      aria-label="100点にする値"
                      onValueChange={(next) => {
                        setGeneratorHundredValue(next);
                        applyScoringRange(generatorZeroValue, next, generatorShape);
                      }}
                    />
                  </span>
                  <Select
                    aria-label="効き方"
                    value={generatorShape}
                    onChange={(e) => {
                      const next = e.target.value as BreakpointShape;
                      setGeneratorShape(next);
                      applyScoringRange(generatorZeroValue, generatorHundredValue, next);
                    }}
                  >
                    {BREAKPOINT_SHAPE_OPTIONS.map((opt) => (
                      <option key={opt.id} value={opt.id}>
                        {opt.label}
                      </option>
                    ))}
                  </Select>
                </div>
                {primaryMaterial && referencePoints.length > 0 && (
                  <div className="flex flex-wrap gap-1" role="group" aria-label="参考点から値を選ぶ">
                    {referencePoints.map((p) => {
                      const x = p.x;
                      return (
                        <Button
                          size="xs"
                          key={p.label}
                          title={`${p.label}: ${p.value}${primaryMaterial.unit}`}
                          onClick={() => {
                            setGeneratorZeroValue(x);
                            applyScoringRange(x, generatorHundredValue, generatorShape);
                          }}
                          onDoubleClick={() => {
                            setGeneratorHundredValue(x);
                            applyScoringRange(generatorZeroValue, x, generatorShape);
                          }}
                        >
                          {p.label}
                        </Button>
                      );
                    })}
                  </div>
                )}

                <DistributionPreview
                  distribution={valueDistribution.distribution}
                  binScores={scoresPreview?.scores ?? null}
                  loading={valueDistribution.loading}
                  error={valueDistribution.error}
                />
                <details className="[&>summary]:cursor-pointer [&>summary]:py-1 [&>summary]:text-[length:var(--font-size-sm)] [&>summary]:text-[var(--color-muted)] open:[&>summary]:text-[var(--foreground)]">
                  <summary>折れ点を直接いじる</summary>
                  <SectionLabel
                    label="折れ点"
                    description="値が大きいほど走りにくくしたければ右肩上がりに、走りやすくしたければ右肩下がりに設定してください。図はドラッグ・矢印キーでも調整できます。"
                  />
                  <BreakpointCurveEditor
                    breakpoints={draft.breakpoints}
                    onChangePoint={updateBreakpoint}
                    referenceRange={breakpointReferenceRange}
                    distribution={valueDistribution.distribution}
                  />
                  {draft.breakpoints.map((bp, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-2 [&_input]:w-20">
                      <NumberInput
                        commitOn="input"
                        step="any"
                        value={bp[0]}
                        aria-label="入力値"
                        onValueChange={(next) => updateBreakpoint(i, 0, next)}
                      />
                      <span>→</span>
                      <NumberInput
                        commitOn="input"
                        step="any"
                        value={bp[1]}
                        aria-label="スコア"
                        onValueChange={(next) => updateBreakpoint(i, 1, next)}
                      />
                      <Button
                        size="sm"
                        onClick={() =>
                          setDraft((d) => ({ ...d, breakpoints: d.breakpoints.filter((_, j) => j !== i) }))
                        }
                        disabled={draft.breakpoints.length <= 2}
                      >
                        削除
                      </Button>
                    </div>
                  ))}
                  <Button
                    size="sm"
                    className="self-start"
                    onClick={() =>
                      setDraft((d) => ({ ...d, breakpoints: insertBreakpointAtLargestGap(d.breakpoints) }))
                    }
                  >
                    + 折れ点を追加
                  </Button>
                </details>
                {primaryMaterial && referencePoints.length > 0 && (
                  <div className="flex flex-col gap-1">
                    <SectionLabel
                      label="効き目プレビュー"
                      description="今の折れ点で、材料の参考点それぞれが何点になるかです。"
                    />
                    <Table>
                      <TableHead>
                        <TableRow>
                          <TableHeader>参考点</TableHeader>
                          <TableHeader>値</TableHeader>
                          <TableHeader>スコア</TableHeader>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {referencePoints.map((p) => (
                          <TableRow key={p.label}>
                            <TableCell>{p.label}</TableCell>
                            <TableCell>
                              {p.value}
                              {primaryMaterial.unit}
                            </TableCell>
                            <TableCell>{p.score}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {draft.shapeKind === "categorical" &&
          (() => {
            // 選んだ材料のdtypeで表示を切り替える（boolean→従来の2択、
            // categorical→値ごとのスコア行）。selectedDtypeはコンポーネント冒頭の
            // selectedCategoricalDtype（useMaterialValuesの入力にも使う）と同じ計算。
            const selectedDtype = selectedCategoricalDtype;
            return (
              <div className={cn(cardVariants({ variant: "muted" }), "flex flex-col gap-2")}>
                <Button
                  size="sm"
                  className="self-start"
                  onClick={() =>
                    // 真偽材料を複数足して合計したい軸（街灯なし＋トンネル等）は、値ごとの
                    // スコアではなく「値×係数の合計」の形になる。ここが唯一の移り口。
                    setDraft((d) => ({
                      ...d,
                      shapeKind: "breakpoint_linear",
                      terms: [{ material: d.categoricalMaterial, weight: 1.0, required: true }],
                      breakpoints: [
                        [0, 0],
                        [1, 100],
                      ],
                    }))
                  }
                >
                  + 材料を足して合計する
                </Button>
                {selectedDtype === "categorical" ? (
                  <>
                    <SectionLabel
                      label="値ごとのスコア"
                      description={
                        (categoricalMaterialValues.length > 0
                          ? "値は下の候補（実データに含まれる値）から選びます。"
                          : categoricalValuesUnavailable
                            ? "候補を取得できませんでした（DBへ接続できないか、集計が時間内に終わりませんでした）。値は元データのタグ値と完全に一致する文字列で入力します。"
                            : "値は元データのタグ値と完全に一致する文字列で入力します。") +
                        "ここに設定していない値の区間は評価対象外（データなし扱い）になります。"
                      }
                    />
                    {draft.categoricalRows.map((row, i) => {
                      // 候補一覧（categoricalMaterialValues）がある材料は、候補セレクトでの
                      // 選択のみを許可し、値は常にラベルの読み取り専用表示にする（生の
                      // タグ値は画面に出さない——material_catalogに無い値を書く実運用上の
                      // 必要性は基本無く、直接入力を残すとタイプミスがそのまま「静かに
                      // 一致しない行」として残る落とし穴になる）。候補一覧が無い材料
                      // （動的値一覧に対応していない）だけ、
                      // 自由テキスト入力のままにする（選ぶ元となる候補自体が存在しないため）。
                      const hasDynamicCandidates = categoricalMaterialValues.length > 0;
                      // 選択中の値のラベルは、取得済みの候補一覧（MaterialSpec.value_labels
                      // 由来）から引く。候補一覧に無い値（編集を開いた時点で
                      // 既存軸が保持していたが、実データが変わり現在は候補から外れた値等）は
                      // 生のタグ値そのままにフォールバックする。
                      const label = categoricalMaterialValues.find((v) => v.value === row.value)?.label ?? row.value;
                      return (
                        <div key={i} className="flex flex-wrap items-center gap-2">
                          {hasDynamicCandidates && (
                            <Select
                              aria-label="値の候補"
                              value=""
                              onChange={(e) => {
                                if (e.target.value) updateCategoricalRow(i, { value: e.target.value });
                              }}
                            >
                              <option value="">候補から選ぶ...</option>
                              {categoricalMaterialValues.map((v) => (
                                <option key={v.value} value={v.value}>
                                  {v.label}
                                </option>
                              ))}
                            </Select>
                          )}
                          {hasDynamicCandidates ? (
                            // 実体は読み取り専用のinputにする（素のspanではなく
                            // input[type=text] にすることで、globals.cssの共通スタイルが
                            // そのまま当たり見た目が他のinputと揃う）。編集不可
                            // （readOnly）で、値は候補セレクトからのみ設定する。
                            <Input
                              type="text"
                              value={label}
                              readOnly
                              aria-label="値"
                              placeholder="候補から選択してください"
                            />
                          ) : (
                            <Input
                              type="text"
                              value={row.value}
                              aria-label="値"
                              placeholder="例: separated"
                              onChange={(e) => updateCategoricalRow(i, { value: e.target.value })}
                            />
                          )}
                          <SliderNumberField
                            label="スコア"
                            value={row.score}
                            onChange={(next) => updateCategoricalRow(i, { score: next })}
                            min={-100}
                            max={100}
                            step={1}
                          />
                          <Button
                            size="sm"
                            onClick={() => removeCategoricalRow(i)}
                            disabled={draft.categoricalRows.length <= 1}
                          >
                            削除
                          </Button>
                        </div>
                      );
                    })}
                    <Button size="sm" className="self-start" onClick={addCategoricalRow}>
                      + 値を追加
                    </Button>
                  </>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center gap-3">
                      <label className={fieldClass}>
                        該当時(true)のスコア
                        <SliderNumberField
                          label="はいのときのスコア"
                          value={draft.trueScore}
                          onChange={(next) => setDraft((d) => ({ ...d, trueScore: next }))}
                          min={-100}
                          max={100}
                          step={1}
                        />
                      </label>
                      <label className={fieldClass}>
                        非該当時(false)のスコア
                        <SliderNumberField
                          label="いいえのときのスコア"
                          value={draft.falseScore}
                          onChange={(next) => setDraft((d) => ({ ...d, falseScore: next }))}
                          min={-100}
                          max={100}
                          step={1}
                        />
                      </label>
                    </div>
                  </>
                )}
              </div>
            );
          })()}
      </>
    );
  }

  return renderShapeParamsStep();
}
