"use client";

import { useState, type PointerEvent as ReactPointerEvent } from "react";
import * as Popover from "@radix-ui/react-popover";
import { FieldLabel } from "@/components/Map/recipeControls";
import { InfoIcon } from "@/components/Map/icons";
import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import { useMaterialCatalog } from "@/hooks/useMaterialCatalog";
import { useMaterialValues } from "@/hooks/useMaterialValues";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import type { AxisDefinitionPayload, AxisDefinitionResponse, AxisShape } from "@/types/route";
import { AXIS_ICON_PALETTE, axisIconFor } from "@/components/Map/axisIconPalette";
import styles from "./AxisStudio.module.css";
// 情報アイコン(ⓘ)ポップオーバーのCSS（.infoButton/.infoTooltip）はrecipeControls.tsxの
// FieldLabelが既に定義済みのものをそのまま流用する（同じ見た目・z-index対策[T305]を
// 材料選択の情報アイコンでも二重定義せず共有するため。改善計画T345）。
import recipeControlStyles from "@/components/Map/recipeControls.module.css";

// 軸コンポーザー（改善計画T270、T221 Stage E）。表示名→点数のつけ方を選ぶ→点数の詳細→
// 地図表示・公開、という4ステップのウィザードで軸を組み立てる中核機能。既存の
// `AxisDefinition.shape`（判別union、backend/app/domain/axis_definitions.py）をそのまま
// GUIの入力欄群へ写す構造は変えず、専門知識のないユーザーにも辿れる導線へ再構成した
// （改善計画T332、UIレビュー2026-08-25のF-2「変換テンプレート4択が数式的な語彙のまま」
// への対応。カード選択の文言化でF-2の元ネタT324、地図チップ折れ点のスコア向き説明で
// T327、旧ドロップダウンの「真偽2値→定数」という食い違った文言の撤去でT326も併せて解消）。
//
// 内部で保持する4種の変換テンプレート(shape kind)自体は変えない（ADR「新しい計算
// テンプレートの追加は引き続きコード変更が必要、際限のない汎用化は目指さない」という
// 承認済み方針）。材料はuseMaterialCatalog()（改善計画T277、GET /api/material-catalog）が
// 返す候補から選ぶ（目論見書7章・歯止め4「材料の天井」。API取得失敗時はlib/
// axisMaterialsCatalog.tsの静的フォールバックへ自動的に切り替わる）。

type ShapeKind = "breakpoint_linear" | "recipe_then_breakpoint_linear" | "categorical";

// 改善計画T397: 軸スタジオの合成ロジックが2プリミティブ+合成へ再設計された（T396）ことに
// 合わせ、4枚のカードを3枚へ整理した。「複数の要素の有無を数えて減点・加点する」
// （旧flag_sum）は「数値の大きさに応じて点数を変える」（なめらか評価）に吸収した——
// backend側では元々同一の仕組み（真偽値材料は該当時1・非該当時0として係数と掛け合わされる）
// で、専用の別画面を持たせる理由が無かったため（カードの説明文に両方の具体例を残し、
// どちらの用途で来たユーザーも迷わないようにする）。recipe_then_breakpoint_linear
// （かけあわせ評価）は他の軸を組み合わせる専用の入口として引き続き独立させるが、
// 「純粋な重み付き結合（nX + mY）」に絞り、折れ点の編集UIは出さない（ユーザー判断、
// 条件判定等は含めない）。
interface ShapeKindOption {
  kind: ShapeKind;
  title: string;
  description: string;
  advanced?: boolean;
}

const SHAPE_KIND_OPTIONS: ShapeKindOption[] = [
  {
    kind: "breakpoint_linear",
    title: "なめらか評価",
    description: "数値の大きさや、複数の要素の有無に応じて点数を変える（例: 勾配が急なほど、街灯なしが該当するほど）",
  },
  {
    kind: "categorical",
    title: "ぴったり評価",
    description: "はい/いいえ、または種類ごとに点数を決める（例: 一方通行かどうか、道路の種類ごと）",
  },
  {
    kind: "recipe_then_breakpoint_linear",
    title: "かけあわせ評価",
    description: "既にある軸のスコアに重みを掛けて合計する（例: 勾配の軸を2倍重視、風の軸を1倍）",
    advanced: true,
  },
];

function shapeKindOption(kind: ShapeKind): ShapeKindOption {
  return SHAPE_KIND_OPTIONS.find((o) => o.kind === kind) ?? SHAPE_KIND_OPTIONS[0];
}

/** 改善計画T345: 材料選択セレクトの隣に置く情報アイコン(ⓘ)。選択中の材料の説明文
 * （backend/app/domain/material_catalog.py: MaterialSpec.description）をポップオーバーで
 * 表示する。「材料名だけでは何を表しているか分かりにくい」というユーザー指摘への対応。
 * 材料が複数行並ぶ欄（terms/flags）でも行ごとに選択中の材料が違うため、FieldLabelを
 * そのまま流用せずラベル文言を持たない専用の小型トリガーにする（行ごとに毎回同じ文言を
 * 繰り返し表示すると煩雑なため）。実体はInfoPopoverButton（ラベル文言を持たない汎用版）。 */
function InfoPopoverButton({ ariaLabel, description }: { ariaLabel: string; description: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button type="button" className={recipeControlStyles.infoButton} aria-label={`${ariaLabel}を${open ? "隠す" : "表示"}`}>
          <InfoIcon />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className={recipeControlStyles.infoTooltip} side="bottom" align="start" sideOffset={6}>
          {description}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function MaterialInfoButton({ option }: { option: AxisMaterialOption | undefined }) {
  if (!option) return null;
  return <InfoPopoverButton ariaLabel={`${option.label}の説明`} description={option.description} />;
}

/** 改善計画T397フォローアップ（ユーザー指摘: 説明文が常に表示されていて見にくい）:
 * 見出し＋詳しい説明は(ⓘ)ポップオーバーへ折りたたむ（表示名・既定重み欄で既に使っている
 * FieldLabelと同じ考え方を、フォーム項目1つではなく材料一覧・折れ点等のセクション
 * 単位に広げたもの）。descriptionを省略した場合は見出しだけを出す。 */
function SectionLabel({ label, description }: { label: string; description?: string }) {
  return (
    <div className={styles.sectionLabelRow}>
      <p className={styles.groupLabel}>{label}</p>
      {description && <InfoPopoverButton ariaLabel={`${label}の説明`} description={description} />}
    </div>
  );
}

/** 改善計画T397: 係数・スコアの入力を「スライダーで大まかに調整＋数値で正確に入力」の
 * 組み合わせにする（ユーザー指摘: 数値入力だけでなくスライダーも使いたい）。両者は同じ
 * stateを指すため常に同期する。値そのものの取りうる範囲は材料ごとに大きく異なる
 * （傾斜の係数1.0、車線数の係数0.1、旧flag_sumの加点50等）ため、スライダーの範囲は
 * あくまで「大まかな調整用の目安」とし、範囲外の値は数値入力欄から直接指定できる
 * （スライダー自体はその値を表示できないが、隣の数値入力の値がそのまま送信される）。 */
function SliderNumberField({
  value,
  onChange,
  label,
  min,
  max,
  step,
}: {
  value: number;
  onChange: (next: number) => void;
  label: string;
  min: number;
  max: number;
  step: number;
}) {
  const clamped = Math.min(max, Math.max(min, value));
  return (
    <span className={styles.sliderNumberField}>
      <input
        type="range"
        aria-label={`${label}(スライダー)`}
        min={min}
        max={max}
        step={step}
        value={clamped}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <input
        type="number"
        step={step}
        value={value}
        aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </span>
  );
}

/** 改善計画T397: 折れ点(breakpoints)をドラッグで調整できる曲線エディタ。既存の数値入力
 * 行（正確な値の入力・行の追加削除）はそのまま残し、この曲線はその可視化＋補助的な
 * 操作手段として上に添える（両者は同じdraft.breakpoints stateを指すため常に同期する）。
 * 横軸・縦軸とも現在のbreakpointsの値から自動的にスケールする。 */
function BreakpointCurveEditor({
  breakpoints,
  onChangePoint,
}: {
  breakpoints: [number, number][];
  onChangePoint: (index: number, pos: 0 | 1, value: number) => void;
}) {
  const width = 400;
  const height = 160;
  const padding = 28;
  const xs = breakpoints.map((bp) => bp[0]);
  const ys = breakpoints.map((bp) => bp[1]);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(0, ...ys);
  const yMax = Math.max(100, ...ys);
  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;

  function toScreen(bp: [number, number]): [number, number] {
    const sx = padding + ((bp[0] - xMin) / xSpan) * (width - padding * 2);
    const sy = height - padding - ((bp[1] - yMin) / ySpan) * (height - padding * 2);
    return [sx, sy];
  }

  function fromScreen(sx: number, sy: number): [number, number] {
    const x = xMin + ((sx - padding) / (width - padding * 2)) * xSpan;
    const y = yMin + ((height - padding - sy) / (height - padding * 2)) * ySpan;
    return [Math.round(x * 10) / 10, Math.round(y)];
  }

  const points = breakpoints.map(toScreen);
  const polyline = points.map(([x, y]) => `${x},${y}`).join(" ");

  function handlePointerMove(e: ReactPointerEvent<SVGCircleElement>, index: number) {
    if (e.buttons !== 1) return;
    const svg = e.currentTarget.ownerSVGElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const sx = ((e.clientX - rect.left) / rect.width) * width;
    const sy = ((e.clientY - rect.top) / rect.height) * height;
    const [x, y] = fromScreen(sx, sy);
    onChangePoint(index, 0, x);
    onChangePoint(index, 1, y);
  }

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={styles.curveEditor}
      role="img"
      aria-label="折れ点の曲線プレビュー（ドラッグで調整可能）"
    >
      <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} className={styles.curveAxis} />
      <line x1={padding} y1={padding} x2={padding} y2={height - padding} className={styles.curveAxis} />
      <polyline points={polyline} className={styles.curveLine} />
      {points.map(([x, y], i) => (
        <circle
          key={i}
          cx={x}
          cy={y}
          r={7}
          className={styles.curvePoint}
          onPointerDown={(e) => e.currentTarget.setPointerCapture(e.pointerId)}
          onPointerMove={(e) => handlePointerMove(e, i)}
        />
      ))}
    </svg>
  );
}

// 改善計画T305: axis_idはユーザー入力欄から撤去した。ユーザーからの指摘「axis_idは
// システムが勝手に一意な何かを自動採番してくれればよい。設定画面に不要では？画面上は
// 表示名があればよい」への対応——内部識別子であって人間が読む必要はなく、実際に画面上で
// 意味を持つのは表示名(label)の方だけだったため。新規作成・複製時にここで自動生成し、
// 編集時は既存のaxis_idをそのまま使う（axis_id自体はbackend側で形式制約が無い[str]ため、
// 半角英数字で読みやすいprefix+乱数のみで十分）。
function generateAxisId(): string {
  // コードレビュー指摘の修正: crypto.randomUUIDはセキュアコンテキスト（HTTPS/localhost）
  // でのみ定義される。/adminが平文HTTPの非localhostオリジン（TLS終端がNext.jsの手前に
  // 無いオンプレ運用時の内部LAN IP等）から配信されると、この関数がuseState初期化子内で
  // TypeErrorを送出し、AxisComposerのマウント自体が失敗する（エラー表示すら出ない）。
  // Math.randomベースのフォールバックを用意する（axis_idは内部識別子で暗号学的な
  // 一意性は不要、衝突時はbackend側のPRIMARY KEY制約で409になるだけで安全）。
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `axis_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
  }
  return `axis_${Math.random().toString(16).slice(2, 14).padEnd(12, "0")}`;
}

interface TermDraft {
  material: string;
  weight: number;
  required: boolean;
}

/** 改善計画T322: categorical材料（highway/bicycle_infra等、真偽値ではなく文字列多値）を
 * 「はい/いいえ、または種類ごとに点数を決める」で使うための(値, スコア)行。値は自由入力
 * テキストで持つ（mapping未登録の値は評価対象外[欠損]として扱われる）。改善計画T340:
 * highway/surface/smoothnessのようにGET /api/material-catalog/{material_id}/valuesが
 * 実データの値一覧を返せる材料では、入力欄の隣に候補選択セレクトを添えてタグ生値の
 * 暗記・手入力の負担を減らす（値の保存先はこのvalueフィールドのまま変わらない）。 */
interface CategoricalRowDraft {
  value: string;
  score: number;
}

interface Draft {
  axisId: string;
  label: string;
  description: string;
  defaultWeight: number;
  shapeKind: ShapeKind;
  terms: TermDraft[];
  preprocess: "identity" | "abs";
  breakpoints: [number, number][];
  categoricalMaterial: string;
  trueScore: number;
  falseScore: number;
  /** 改善計画T322: categoricalMaterialのdtypeが"categorical"のときのみ使う行群。
   * dtype="boolean"の材料を選んでいる間はtrueScore/falseScoreの方を使う。 */
  categoricalRows: CategoricalRowDraft[];
  /** 改善計画T271: 公開状態。trueにすると一般向けGET /api/axis-catalogへ現れ、以後
   * backend側で更新・削除が拒否される（不変制約）ため、確定前によく確認してからONにする。 */
  isPublished: boolean;
  /** 改善計画T310: 地図チップ表示要素（未設定は空文字列で表し、送信時にnullへ変換する）。 */
  iconId: string;
  chipLabel: string;
  panelHint: string;
  /** 改善計画T318: この軸のアイコンを地図上チップ・地図の見え方パネルに表示するか
   * どうか。既定true（表示する）。旧proxyHint（専用地図レイヤーを持たない軸向けの
   * 代役案内文）はこのON/OFFに置き換わり撤去した。 */
  showMapIcon: boolean;
  /** コードレビュー指摘の修正: priority_overrides（改善計画T292、0次条件）はこの
   * フォームに編集欄を持たないが、既存軸の値をpayloadへ素通しして保持する
   * （以前はpayloadに含めておらず、公開済み軸を非公開へ戻して軽微な編集をしただけで
   * これが黙って失われていた——エラーも警告も出ない静かなデータ破壊だったため）。 */
  priorityOverrides: AxisDefinitionResponse["priority_overrides"];
  /** 改善計画T404: 地図の色分けしきい値だけを差し替える軽量な上書き。未設定(null)は
   * 自動導出したしきい値をそのまま使う。数値の配列を直接編集するシンプルなUIで
   * このフォームで直接編集できる（旧display_overrideは生JSON編集が必要で編集欄を
   * 持てなかったが、改善計画T409でフィールド自体を削除した。domain/axis_definitions.py:
   * AxisDefinition.display_thresholds_overrideのdocstring参照）。 */
  displayThresholdsOverride: number[] | null;
  /** 改善計画T352: time_scope/supports_route_coloringも同じ理由（このフォームに編集欄を
   * 持たないが、既存軸の値をpayloadへ素通しして保持する）で追加。domain/axis_definitions.py:
   * AxisDefinition.time_scope/supports_route_coloringのdocstring参照。 */
  timeScope: AxisDefinitionResponse["time_scope"];
  supportsRouteColoring: AxisDefinitionResponse["supports_route_coloring"];
  /** この軸が専用のway_id→値配信レイヤーを持つかの宣言。time_scope/
   * supportsRouteColoringと同じ理由（このフォームに編集欄を持たないが、既存軸の値を
   * payloadへ素通しして保持する）で追加。domain/axis_definitions.py:
   * AxisDefinition.dedicated_way_value_layerのdocstring参照。 */
  dedicatedWayValueLayer: boolean;
}

function emptyDraft(materialOptions: readonly AxisMaterialOption[]): Draft {
  // T424修正: materialOptionsが空配列（useMaterialCatalogが取得成功したがmaterials
  // 0件の場合、docs/tasks/T424.md参照）のとき、以前は`materialOptions[0].id`を無条件
  // 参照しマウント直後にTypeErrorでクラッシュしていた。空文字列(""へ)フォールバックし、
  // 呼び出し元(AxisComposer本体)が materialOptions.length === 0 のとき早期にエラー状態
  // UIへ切り替えてこの空文字列のdraftをそもそも画面に出さないようにする。
  const firstBoolean = materialOptions.find((m) => m.dtype === "boolean")?.id ?? materialOptions[0]?.id ?? "";
  return {
    axisId: generateAxisId(),
    label: "",
    description: "",
    defaultWeight: 0.1,
    shapeKind: "breakpoint_linear",
    terms: [{ material: materialOptions[0]?.id ?? "", weight: 1.0, required: true }],
    preprocess: "identity",
    breakpoints: [
      [0, 0],
      [10, 100],
    ],
    categoricalMaterial: firstBoolean,
    trueScore: 0,
    falseScore: 80,
    categoricalRows: [],
    isPublished: false,
    iconId: "",
    chipLabel: "",
    panelHint: "",
    showMapIcon: true,
    priorityOverrides: [],
    displayThresholdsOverride: null,
    timeScope: "always",
    supportsRouteColoring: false,
    dedicatedWayValueLayer: false,
  };
}

function draftFromExisting(def: AxisDefinitionResponse, materialOptions: readonly AxisMaterialOption[]): Draft {
  const base = emptyDraft(materialOptions);
  const shape = def.shape;
  const common = {
    ...base,
    axisId: def.axis_id,
    label: def.label,
    description: def.description,
    defaultWeight: def.default_weight,
    isPublished: def.is_published,
    iconId: def.icon_id ?? "",
    chipLabel: def.chip_label ?? "",
    panelHint: def.panel_hint ?? "",
    showMapIcon: def.show_map_icon,
    priorityOverrides: def.priority_overrides,
    displayThresholdsOverride: def.display_thresholds_override ?? null,
    timeScope: def.time_scope,
    supportsRouteColoring: def.supports_route_coloring,
    dedicatedWayValueLayer: def.dedicated_way_value_layer ?? false,
  };
  // "kind"の判別子で分岐する（AxisShapeは3種のPydantic discriminated unionの構造をそのまま
  // 写した型のため、"terms"/"material"/"flags"というフィールド有無による判別も可能だが、
  // backend側の判別子(kind)に合わせてこちらを単一の判定基準にする）。
  if (shape.kind === "categorical") {
    // 改善計画T322: 材料のdtypeで真偽値2択/カテゴリ値複数行のどちらの編集UIを
    // 初期表示するか決める（保存済みmapping自体のキー型からは判別しない。JSON化された
    // mappingのキーは常に文字列で、bool材料でも"true"/"false"という文字列キーになるため）。
    const dtype = materialOptions.find((m) => m.id === shape.material)?.dtype;
    if (dtype === "categorical") {
      return {
        ...common,
        shapeKind: "categorical",
        categoricalMaterial: shape.material,
        categoricalRows: Object.entries(shape.mapping).map(([value, score]) => ({ value, score })),
      };
    }
    return {
      ...common,
      shapeKind: "categorical",
      categoricalMaterial: shape.material,
      trueScore: shape.mapping["true"] ?? 0,
      falseScore: shape.mapping["false"] ?? 0,
    };
  }
  // 改善計画T396/T397: backendはbreakpoint_linear/recipe_then_breakpoint_linear/flag_sumの
  // 3種を"breakpoint_linear"1種へ統合したため、保存済みのkindだけでは元々どのカードで
  // 作られた軸かを判別できない。termsの構造（材料か他軸か）から表示するカードを推定し直す
  // （domain/axis_display.pyの構造判定と同じ考え方）。旧flag_sum相当（全termがboolean材料）は
  // T397で「なめらか評価」カードへ吸収されたため、専用の判別は不要になった。
  const isAxisReference = (material: string) => !materialOptions.some((m) => m.id === material);
  if (shape.terms.length > 0 && shape.terms.every((t) => isAxisReference(t.material))) {
    return {
      ...common,
      shapeKind: "recipe_then_breakpoint_linear",
      terms: shape.terms.map((t) => ({ material: t.material, weight: t.weight, required: t.required })),
      preprocess: shape.preprocess,
      breakpoints: shape.breakpoints,
    };
  }
  return {
    ...common,
    shapeKind: "breakpoint_linear",
    terms: shape.terms.map((t) => ({ material: t.material, weight: t.weight, required: t.required })),
    preprocess: shape.preprocess,
    breakpoints: shape.breakpoints,
  };
}

/** 複製（改善計画T271、公開済み軸を「改良」する唯一の経路）。既存の内容を丸ごと写すが、
 * axis_idは新規に自動採番し（改善計画T305）、is_publishedは常にfalse（下書き）から
 * 始める——複製元が公開済みでも複製先まで公開扱いを引き継がない。 */
function draftFromDuplicate(def: AxisDefinitionResponse, materialOptions: readonly AxisMaterialOption[]): Draft {
  return { ...draftFromExisting(def, materialOptions), axisId: generateAxisId(), isPublished: false };
}

function buildShape(draft: Draft, materialOptions: readonly AxisMaterialOption[]): AxisShape {
  // 改善計画T396: backend側はbreakpoint_linear/recipe_then_breakpoint_linear/flag_sumの
  // 3種を「連続演算」1種（kind="breakpoint_linear"）へ統合した。draft.shapeKindは
  // ユーザー向けカード選択（UIの入り口）としては引き続き4種を保つが、保存する
  // shape.kindは常に"breakpoint_linear"へ正規化する。
  if (draft.shapeKind === "breakpoint_linear" || draft.shapeKind === "recipe_then_breakpoint_linear") {
    return {
      kind: "breakpoint_linear",
      terms: draft.terms.map((t) => ({ material: t.material, weight: t.weight, required: t.required })),
      preprocess: draft.preprocess,
      breakpoints: draft.breakpoints,
    };
  }
  const dtype = materialOptions.find((m) => m.id === draft.categoricalMaterial)?.dtype;
  if (dtype === "categorical") {
    return {
      kind: "categorical",
      material: draft.categoricalMaterial,
      mapping: Object.fromEntries(
        draft.categoricalRows.filter((r) => r.value.trim() !== "").map((r) => [r.value.trim(), r.score]),
      ),
    };
  }
  return {
    kind: "categorical",
    material: draft.categoricalMaterial,
    mapping: { true: draft.trueScore, false: draft.falseScore },
  };
}

interface AxisComposerProps {
  /** 編集対象。nullなら新規作成（下記duplicateFromが無ければ空欄から）。公開済み軸は
   * 呼び出し側（AxisStudio）が編集ボタン自体を無効化するため、ここへは渡らない想定。 */
  editing: AxisDefinitionResponse | null;
  /** 複製元（改善計画T271）。editingがnullのとき、この軸の内容（axis_id/is_published除く）
   * で新規作成フォームを初期化する。 */
  duplicateFrom: AxisDefinitionResponse | null;
  /** 改善計画T345: 既定重み(default_weight)欄に「他の公開軸の重みに対して何%か」を
   * 参考表示するための、この軸以外を含む全軸一覧（AxisStudio.tsxが一覧取得済みのものを
   * そのまま渡す）。省略時（テスト等）は参考表示自体を出さない。 */
  otherAxes?: readonly AxisDefinitionResponse[];
  onCancelEdit: () => void;
  onSave: (payload: AxisDefinitionPayload, isNew: boolean) => Promise<void>;
}

// 改善計画T332: 4ステップのウィザード。ステップ自体の追加・削除はコード変更を要する
// （4テンプレート限定の方針と同様、際限のない動的ステップ化は目指さない）。
const STEPS = ["basic", "shape_kind", "shape_params", "display_publish"] as const;
type Step = (typeof STEPS)[number];
const STEP_TITLES: Record<Step, string> = {
  basic: "基本情報",
  shape_kind: "点数のつけ方を選ぶ",
  shape_params: "点数の詳細を設定",
  display_publish: "地図表示・公開",
};

export default function AxisComposer({ editing, duplicateFrom, otherAxes, onCancelEdit, onSave }: AxisComposerProps) {
  const materialOptions = useMaterialCatalog();
  const [draft, setDraft] = useState<Draft>(() => {
    if (editing) return draftFromExisting(editing, materialOptions);
    if (duplicateFrom) return draftFromDuplicate(duplicateFrom, materialOptions);
    return emptyDraft(materialOptions);
  });
  // 改善計画T340: categorical材料の値入力欄に候補選択を添えるための実データ値一覧。
  // dtype="categorical"の材料を選んでいる間だけ取得する（boolean材料選択中・
  // categorical材料でも動的値一覧に対応していない場合[bicycle_infra等]は空配列が返り、
  // 呼び出し先の入力欄は自由テキストのままになる）。
  const selectedCategoricalDtype = materialOptions.find((m) => m.id === draft.categoricalMaterial)?.dtype;
  const categoricalMaterialValues = useMaterialValues(
    selectedCategoricalDtype === "categorical" ? draft.categoricalMaterial : null,
  );
  const [stepIndex, setStepIndex] = useState(0);
  const step = STEPS[stepIndex];
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isNew = editing === null;

  // T424修正: useMaterialCatalog()は取得成功したがmaterialsが0件のとき、静的
  // フォールバック（AXIS_MATERIAL_OPTIONS）へは留まらず空配列をそのまま返す仕様
  // （useMaterialCatalog.tsのdocstring参照、2026-08-25の修正）。backend側の
  // material_catalog.pyが運用上の何らかの理由（材料レジストリ空・DB接続不調時の
  // 空応答等）で0件を返すとここに到達する。材料が1件も無ければ「材料」「値ごとの
  // スコア」等どのステップも選択肢が作れず、ウィザードを進めても保存不能な軸しか
  // 作れない（かつdraft初期化時のフォールバックが空文字列のmaterial idになるため、
  // そのまま送信すればbackend側のバリデーションエラーになる）。ウィザード全体の
  // 代わりに空状態エラーを出し、材料が0件のままではフォームを開かせない。
  // 上記のフック呼び出し（useMaterialCatalog/useState/useMaterialValues）はすべて
  // このガードより前で無条件に呼び終えているため、Rules of Hooksには反しない。
  if (materialOptions.length === 0) {
    return (
      <div className={styles.composer}>
        <p className={styles.errorText}>
          材料カタログを取得できませんでした（0件の応答）。時間をおいて再度開くか、backend側の材料カタログ（material_catalog.py）の状態を確認してください。
        </p>
        <div className={styles.row}>
          <button type="button" onClick={onCancelEdit}>
            閉じる
          </button>
        </div>
      </div>
    );
  }

  // ユーザー指摘（軸同士の線形結合nX+mYがGUIから組めない）への対応: backend側は元々
  // MaterialTerm.materialへ他の軸のaxis_idを指定できる設計（domain/axis_definitions.py:
  // AxisDefinition docstring「軸の階層」）だが、「他の軸の計算結果をもとに点数を変える」
  // テンプレートの材料セレクトがmaterialOptions（MATERIAL_CATALOGの材料のみ）しか
  // 出しておらず、他の軸を選ぶ手段自体がGUI上に存在しなかった（実装漏れ）。編集中の
  // 軸自身は自己参照になるため候補から除く。軸のスコアは常に0〜100（difficultyの規約）
  // のためdtype="numeric"として扱う。
  const axisTermOptions: readonly AxisMaterialOption[] = (otherAxes ?? [])
    .filter((a) => a.axis_id !== draft.axisId)
    .map((a) => ({ id: a.axis_id, label: a.label, description: a.description, dtype: "numeric" as const }));

  // 一覧から別の軸の編集を選び直した場合の切り替えは、呼び出し側（AxisStudio）が
  // <AxisComposer key={editing?.axis_id ?? "new"}> のようにkeyを変えてコンポーネント自体を
  // 再マウントする方式に委ねる（このコンポーネント内でeditingの変化を検知しない）。

  // 改善計画T332: ステップを進める前の検証。「表示名が無いまま次へ進んで、最後の保存時に
  // 初めてエラーが出る」という手戻りを避け、該当ステップに留まったまま原因を示す。
  function validateStep(target: Step): string | null {
    if (target === "basic") {
      if (draft.label.trim() === "") return "表示名(label)を入力してください。";
    }
    if (target === "shape_params" && draft.shapeKind === "breakpoint_linear") {
      // 改善計画T425（ゼロベース網羅レビュー指摘）: display_thresholds_override
      // （色分け表示用）と同じ昇順チェックを、評価に使うdraft.breakpoints
      // （backend: shape.breakpoints）にも先回りして適用する。backend側の対応する
      // 検証（axis_admin.py: _check_materials_are_known内）は保存時の最終防衛のため、
      // ここでは早期にステップへ留めてユーザーへ知らせる。
      const xs = draft.breakpoints.map((bp) => bp[0]);
      if (xs.some((x, i) => i > 0 && x <= xs[i - 1])) {
        return "折れ点は横軸（左の入力欄）の値が小さい順になるようにしてください（同じ値は使えません）。";
      }
    }
    if (target === "shape_params" && draft.shapeKind === "categorical") {
      // 改善計画T322: categorical材料選択時、値の行が1つも入力されていないと
      // mapping={}のまま保存されてしまい（全区間で評価不能=欠損になるだけで保存自体は
      // 通ってしまう）、設定し忘れに気づきにくいため事前に弾く。
      const dtype = materialOptions.find((m) => m.id === draft.categoricalMaterial)?.dtype;
      if (dtype === "categorical" && draft.categoricalRows.every((r) => r.value.trim() === "")) {
        return "値ごとのスコアを少なくとも1件設定してください。";
      }
    }
    if (target === "display_publish") {
      // コードレビュー指摘の修正: backend側の検証（axis_admin.py:
      // _check_label_length_or_chip_label）と同じ条件をここでも先回りしてチェックし、
      // 保存時まで待たせない。地図チップの略称(chip_label)欄はこのステップにあるため、
      // ここでチェックする（「基本情報」ステップでチェックすると、まだ入力欄が無い
      // 「地図表示・公開」ステップへ誘導するだけで先へ進めない詰みを生む——実機確認で
      // 発覚したT332実装時の不具合、修正済み）。
      if (draft.chipLabel.trim() === "" && draft.label.trim().length > 4) {
        return "表示名(label)が4文字を超えています。地図チップの略称(chip_label)を設定してください。";
      }
      // 改善計画T404: backend側の検証（axis_admin.py: AxisDefinitionPayload._check_
      // display_thresholds_override_is_ascending）と同じ条件を先回りしてチェックする。
      if (draft.displayThresholdsOverride !== null) {
        if (draft.displayThresholdsOverride.length === 0) {
          return "色分けのしきい値を1件以上入力するか、上書きをオフにしてください。";
        }
        for (let i = 1; i < draft.displayThresholdsOverride.length; i++) {
          if (draft.displayThresholdsOverride[i] <= draft.displayThresholdsOverride[i - 1]) {
            return "色分けのしきい値は小さい順に並べてください（同じ値は使えません）。";
          }
        }
      }
    }
    return null;
  }

  function goNext() {
    const err = validateStep(step);
    if (err) {
      setError(err);
      return;
    }
    setError(null);
    setStepIndex((i) => Math.min(i + 1, STEPS.length - 1));
  }

  function goBack() {
    setError(null);
    setStepIndex((i) => Math.max(i - 1, 0));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    // 改善計画T332: 最終ステップ以外でのEnterキー送信は「次へ」として扱う
    // （このコンポーネントは単一の<form>のまま、表示するステップだけを切り替える設計の
    // ため、type="submit"ボタンが常にDOM上に無くても暗黙のフォーム送信は起こりうる）。
    if (step !== "display_publish") {
      goNext();
      return;
    }
    setError(null);
    // basic・shape_paramsステップの検証を保存直前にも通す（ステップを戻って値を空へ
    // 書き換えてから、戻らずに保存を試みた場合の安全網）。
    for (const target of STEPS) {
      const err = validateStep(target);
      if (err) {
        setError(err);
        setStepIndex(STEPS.indexOf(target));
        return;
      }
    }
    const payload: AxisDefinitionPayload = {
      axis_id: draft.axisId,
      label: draft.label.trim(),
      description: draft.description,
      // 改善計画T305: 軸スタジオが作る軸は常に「推定」（複数材料を判定式で合成する軸）。
      // 「観測」（タグ・POIをそのまま読む）「動的」（気象等、時々刻々変わる外部データ由来）は
      // どちらもそれ自体が材料の性質であり、材料を組み合わせて判定式を作る軸スタジオの
      // 仕組みからこれらを生み出すのは概念上おかしい、というユーザー指摘を受けて固定した。
      category: "推定",
      default_weight: draft.defaultWeight,
      shape: buildShape(draft, materialOptions),
      is_published: draft.isPublished,
      // 改善計画T310: 空文字列は「未設定」の意味でnullへ変換する（trim()の理由はlabelと同じ、
      // 空白のみの入力を未設定扱いにする）。
      icon_id: draft.iconId.trim() === "" ? null : draft.iconId,
      chip_label: draft.chipLabel.trim() === "" ? null : draft.chipLabel.trim(),
      panel_hint: draft.panelHint.trim() === "" ? null : draft.panelHint.trim(),
      // 改善計画T318: 地図上にアイコンを表示するかどうかのON/OFF（既定true）。
      show_map_icon: draft.showMapIcon,
      // コードレビュー指摘の修正: このフォームに編集欄を持たないフィールドも、既存値を
      // 素通しして送る（未送信＝サーバー側の既定値[空リスト/null]で上書きされ、既存軸の
      // 値が消えるのを防ぐ）。
      priority_overrides: draft.priorityOverrides,
      display_thresholds_override: draft.displayThresholdsOverride,
      time_scope: draft.timeScope,
      supports_route_coloring: draft.supportsRouteColoring,
      dedicated_way_value_layer: draft.dedicatedWayValueLayer,
    };
    setSaving(true);
    try {
      // 改善計画T304: 保存成功後は呼び出し側（AxisStudio）がモーダルごと閉じるため、
      // ここでフォームをリセットして開いたままにする必要はない（以前の「新規作成時は
      // 続けて次の1件を入力できるようフォームを空へ戻す」挙動は撤去した）。
      await onSave(payload, isNew);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  function updateTerm(index: number, patch: Partial<TermDraft>) {
    setDraft((d) => ({ ...d, terms: d.terms.map((t, i) => (i === index ? { ...t, ...patch } : t)) }));
  }

  function updateBreakpoint(index: number, pos: 0 | 1, value: number) {
    setDraft((d) => ({
      ...d,
      breakpoints: d.breakpoints.map((bp, i) => (i === index ? ([pos === 0 ? value : bp[0], pos === 1 ? value : bp[1]] as [number, number]) : bp)),
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

  // 改善計画T404: 色分けのしきい値（display_thresholds_override）編集用ヘルパー。
  // 生のJSON編集ではなく、数値の配列だけを直接編集するシンプルなUIにする
  // （AxisDefinition.display_thresholds_overrideのdocstring参照）。
  function updateThresholdOverrideValue(index: number, value: number) {
    setDraft((d) => ({
      ...d,
      displayThresholdsOverride: (d.displayThresholdsOverride ?? []).map((v, i) => (i === index ? value : v)),
    }));
  }

  function addThresholdOverrideValue() {
    setDraft((d) => {
      const current = d.displayThresholdsOverride ?? [];
      const next = current.length > 0 ? current[current.length - 1] + 1 : 1;
      return { ...d, displayThresholdsOverride: [...current, next] };
    });
  }

  function removeThresholdOverrideValue(index: number) {
    setDraft((d) => ({
      ...d,
      displayThresholdsOverride: (d.displayThresholdsOverride ?? []).filter((_, i) => i !== index),
    }));
  }

  /** 改善計画T345: 既定重みの絶対値だけでは効果が分からないという指摘への対応。
   * backend側の合成（domain/difficulty.py: composite_difficulty）は重み付き"平均"
   * （重みの合計で正規化）で、かつ対象は公開軸のみ（domain/axis_definitions.py:
   * default_axis_weights）のため、「他の公開軸の重み合計に対して何%か」を参考表示する。
   * 非公開の軸はそもそもこの合成に加わらないため、公開してから意味を持つ旨を案内する。
   * otherAxes未指定（テスト等）・公開軸が1つも無い場合は表示しない。 */
  function renderWeightShare() {
    if (!otherAxes) return null;
    if (!draft.isPublished) {
      return (
        <p className={styles.hint}>
          この軸は現在非公開のため、重みはルート探索へ直接使われません（公開すると、他の公開軸との比率で効くようになります）。
        </p>
      );
    }
    const publishedOthers = otherAxes.filter((a) => a.is_published && a.axis_id !== draft.axisId);
    const total = publishedOthers.reduce((sum, a) => sum + a.default_weight, 0) + draft.defaultWeight;
    if (total <= 0) return null;
    const sharePercent = (draft.defaultWeight / total) * 100;
    return (
      <p className={styles.hint}>
        参考: 現在の公開軸全体（{publishedOthers.length + 1}軸）の重み合計に対して約{sharePercent.toFixed(1)}%です。
      </p>
    );
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

  function renderBasicStep() {
    return (
      <>
        <div className={styles.field}>
          <FieldLabel
            label="表示名(label)"
            description="一般ユーザー向けのルート設定画面・地図の凡例に表示される名前です。"
          />
          <input
            type="text"
            value={draft.label}
            aria-label="表示名(label)"
            onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))}
            placeholder="例: 未舗装回避"
          />
        </div>

        <label className={styles.fieldFull}>
          説明(description)
          <textarea
            value={draft.description}
            onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
            rows={2}
          />
        </label>

        <div className={styles.field}>
          <FieldLabel
            label="既定重み(default_weight)"
            description="この軸を誰も上書きしていないときに使われる重みです。他の公開軸の重みとの比率だけがルートの選ばれ方を左右します（数値そのものに意味はありません。例: 全軸の重みを一律2倍にしても結果は変わりません）。大きくするほど、他の軸に対して相対的にこの軸を重視します。0にすると計算から除外されます。"
          />
          <input
            type="number"
            min="0"
            step="0.01"
            aria-label="既定重み(default_weight)"
            value={draft.defaultWeight}
            onChange={(e) => setDraft((d) => ({ ...d, defaultWeight: Number(e.target.value) }))}
          />
          {renderWeightShare()}
        </div>
      </>
    );
  }

  function renderShapeKindStep() {
    return (
      <>
        <p className={styles.groupLabel}>この軸はどうやって点数をつけますか？</p>
        <div className={styles.shapeKindOptions}>
          {SHAPE_KIND_OPTIONS.map((option) => (
            <label
              key={option.kind}
              className={
                option.kind === draft.shapeKind
                  ? `${styles.shapeKindOption} ${styles.shapeKindOptionSelected}`
                  : styles.shapeKindOption
              }
            >
              <input
                type="radio"
                name="shapeKind"
                value={option.kind}
                checked={draft.shapeKind === option.kind}
                onChange={() =>
                  setDraft((d) => {
                    if (d.shapeKind === option.kind) return d;
                    // 材料(terms)の選択候補が「軸一覧」⇔「材料一覧」で入れ替わるテンプレート
                    // 切り替え時は、選択中のtermsを新しい候補一覧に存在しないidのまま
                    // 持ち越さないよう、先頭の候補で作り直す（保存不能な組み合わせを防ぐ）。
                    if (option.kind === "recipe_then_breakpoint_linear") {
                      return {
                        ...d,
                        shapeKind: option.kind,
                        terms: [{ material: axisTermOptions[0]?.id ?? "", weight: 1.0, required: true }],
                        preprocess: "identity",
                        breakpoints: [
                          [0, 0],
                          [100, 100],
                        ],
                      };
                    }
                    if (d.shapeKind === "recipe_then_breakpoint_linear" && option.kind === "breakpoint_linear") {
                      // T424修正: materialOptionsが空のときはfindも[0]も両方undefinedになりうる
                      // ため、最終フォールバックは""（この分岐へ到達する時点で早期リターン済みの
                      // はずだが、念のため無条件アクセスを排除する）。
                      const firstMaterial =
                        materialOptions.find((m) => m.dtype === "numeric" || m.dtype === "boolean")?.id ??
                        materialOptions[0]?.id ??
                        "";
                      return {
                        ...d,
                        shapeKind: option.kind,
                        terms: [{ material: firstMaterial, weight: 1.0, required: true }],
                        breakpoints: [
                          [0, 0],
                          [10, 100],
                        ],
                      };
                    }
                    return { ...d, shapeKind: option.kind };
                  })
                }
              />
              <span className={styles.shapeKindOptionBody}>
                <strong>
                  {option.title}
                  {option.advanced && <span className={styles.hint}>（上級者向け）</span>}
                </strong>
                <span className={styles.hint}>{option.description}</span>
              </span>
            </label>
          ))}
        </div>
      </>
    );
  }

  function renderShapeParamsStep() {
    return (
      <>
        <p className={styles.groupLabel}>選択中: {shapeKindOption(draft.shapeKind).title}</p>
        {/* 改善計画T397フォローアップ（ユーザー指摘: 説明文が多く見にくい）: 折れ点・
            カテゴリのスコア・true/falseスコアの3箇所で繰り返していた「0=走りやすい・
            100=走りにくい」を、このステップの先頭で1回だけ短く伝える形へ統合した。 */}
        <p className={styles.hint}>スコアは0(走りやすい)〜100(走りにくい)です。</p>

        {(draft.shapeKind === "breakpoint_linear" || draft.shapeKind === "recipe_then_breakpoint_linear") && (
          <div className={styles.shapeGroup}>
            {draft.shapeKind === "recipe_then_breakpoint_linear" ? (
              <>
                <SectionLabel
                  label="組み合わせる軸"
                  description="各軸のスコア(0〜100)に係数(n, m…)を掛けた合計が、そのままスコアになります（nX + mYのように軸同士を重み付きで足し合わせるだけの、純粋な結合です）。"
                />
                {axisTermOptions.length === 0 && (
                  <p className={styles.errorText}>
                    組み合わせられる他の軸がまだありません。先に「なめらか評価」等で軸を1つ以上作成してから使えます。
                  </p>
                )}
              </>
            ) : (
              <SectionLabel
                label="材料"
                description="はい/いいえの材料も選べます（該当時は1、非該当時は0として係数と掛け合わされます。街灯なし・トンネルなど、複数の危険要素の有無を数えて減点・加点したい場合もここに追加してください）。複数の材料を追加すると、それぞれの「値×係数」の合計が下の折れ点でスコアへ変換されます。"
              />
            )}
            {/* 改善計画T342: booleanの材料も選べる（該当時1・非該当時0として係数と掛け合わされる、
                backend/app/domain/axis_definitions.py: evaluate_axis_scalarのBreakpointLinearShape
                分岐参照）。categoricalは非対応のまま（文字列材料と数値の掛け算はbackend側で
                エラーになる）。recipe_then_breakpoint_linear（かけあわせ評価）は、材料の代わりに
                他の軸(axisTermOptions)を候補にする。 */}
            {draft.terms.map((term, i) => {
              const termOptions =
                draft.shapeKind === "recipe_then_breakpoint_linear"
                  ? axisTermOptions
                  : materialOptions.filter((m) => m.dtype === "numeric" || m.dtype === "boolean");
              return (
                <div key={i} className={styles.termRow}>
                  <select value={term.material} onChange={(e) => updateTerm(i, { material: e.target.value })}>
                    {termOptions.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                  <MaterialInfoButton option={termOptions.find((m) => m.id === term.material)} />
                  {/* 改善計画T397フォローアップ（ユーザー指摘: スライダーが小さいのに数字が
                      大きく振れて設定しにくい）: 典型的な係数の範囲（±10）に絞り、範囲外の
                      値（旧flag_sumの加点50等）は数値欄から直接入力する想定にした。 */}
                  <SliderNumberField
                    label="係数"
                    value={term.weight}
                    onChange={(next) => updateTerm(i, { weight: next })}
                    min={-10}
                    max={10}
                    step={0.1}
                  />
                  <label className={styles.inlineCheckbox}>
                    <Checkbox checked={term.required} onCheckedChange={(next) => updateTerm(i, { required: next })} aria-label="必須" />
                    必須
                  </label>
                  <InfoPopoverButton
                    ariaLabel="「必須」の説明"
                    description="この材料のデータが無い区間は、軸全体を「評価不能」として扱います。チェックを外すと、データが無い分は0として他の材料だけで評価を続けます。"
                  />
                  <button
                    type="button"
                    onClick={() => setDraft((d) => ({ ...d, terms: d.terms.filter((_, j) => j !== i) }))}
                    disabled={draft.terms.length <= 1}
                  >
                    削除
                  </button>
                </div>
              );
            })}
            <button
              type="button"
              className={styles.addButton}
              disabled={draft.shapeKind === "recipe_then_breakpoint_linear" && axisTermOptions.length === 0}
              onClick={() =>
                setDraft((d) => {
                  const termOptions =
                    d.shapeKind === "recipe_then_breakpoint_linear"
                      ? axisTermOptions
                      : materialOptions.filter((m) => m.dtype === "numeric" || m.dtype === "boolean");
                  // T424修正: materialOptionsが空のとき無条件アクセスでクラッシュしないよう""へ。
                  const fallback = termOptions[0]?.id ?? materialOptions[0]?.id ?? "";
                  return { ...d, terms: [...d.terms, { material: fallback, weight: 1.0, required: false }] };
                })
              }
            >
              + {draft.shapeKind === "recipe_then_breakpoint_linear" ? "軸を追加" : "材料を追加"}
            </button>

            {/* 改善計画T397: 「かけあわせ評価」は純粋な重み付き結合に絞り、下ごしらえ・
                折れ点の編集UIを出さない（保存時は既定値[そのまま・恒等クランプ0→0,100→100]の
                まま送信される、buildShape/renderShapeKindStepのdefault設定参照）。 */}
            {draft.shapeKind === "breakpoint_linear" && (
              <>
                <SectionLabel
                  label="下ごしらえ"
                  description={
                    "材料の値×係数を合計してから、折れ点でスコアに変換する前に行う下ごしらえです。通常は「そのまま」で問題ありません。「絶対値」は合計がマイナスでもプラスとして扱います" +
                    "（例: 勾配は上り+・下り−の符号付き数値ですが、絶対値を使うと上り・下りのどちらでも急なほど走りにくい、という軸にできます）。"
                  }
                />
                <div className={styles.radioRow}>
                  <label className={styles.inlineCheckbox}>
                    <input
                      type="radio"
                      name="preprocess"
                      checked={draft.preprocess === "identity"}
                      onChange={() => setDraft((d) => ({ ...d, preprocess: "identity" }))}
                    />
                    そのまま
                  </label>
                  <label className={styles.inlineCheckbox}>
                    <input
                      type="radio"
                      name="preprocess"
                      checked={draft.preprocess === "abs"}
                      onChange={() => setDraft((d) => ({ ...d, preprocess: "abs" }))}
                    />
                    絶対値
                  </label>
                </div>

                {/* 改善計画T345: T327（UIレビュー2026-08-25 F-5）が明文化したこのヒント文は
                    実際の向きと逆だった（バグ）。組み込みのgradient軸を確認すると、勾配0%→
                    スコア0・勾配15%→スコア100（description="登り坂の急さが小さいほど易しい"）、
                    すなわち0が最も走りやすく100が最も走りにくい。この値はbackend全体で
                    「difficulty(0-100、大きいほど走りにくい)」として扱われる規約
                    （EdgeCostResult.difficulty等）とも一致する。T327時点の認識が逆だったため
                    ここで向きを訂正する。改善計画T397フォローアップ: 説明文はポップオーバーへ
                    折りたたむ（0-100の向きの説明は下の共通キャプション参照）。 */}
                <SectionLabel
                  label="折れ点"
                  description="値が大きいほど走りにくくしたければ右肩上がりに、走りやすくしたければ右肩下がりに設定してください。図はドラッグでも調整できます。"
                />
                <BreakpointCurveEditor breakpoints={draft.breakpoints} onChangePoint={updateBreakpoint} />
                {draft.breakpoints.map((bp, i) => (
                  <div key={i} className={styles.breakpointRow}>
                    <input type="number" step="0.1" value={bp[0]} aria-label="入力値" onChange={(e) => updateBreakpoint(i, 0, Number(e.target.value))} />
                    <span>→</span>
                    <input type="number" step="1" value={bp[1]} aria-label="スコア" onChange={(e) => updateBreakpoint(i, 1, Number(e.target.value))} />
                    <button
                      type="button"
                      onClick={() => setDraft((d) => ({ ...d, breakpoints: d.breakpoints.filter((_, j) => j !== i) }))}
                      disabled={draft.breakpoints.length <= 2}
                    >
                      削除
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className={styles.addButton}
                  onClick={() => setDraft((d) => ({ ...d, breakpoints: [...d.breakpoints, [0, 0]] }))}
                >
                  + 折れ点を追加
                </button>
              </>
            )}
          </div>
        )}

        {draft.shapeKind === "categorical" && (() => {
          // 改善計画T322: 選んだ材料のdtypeで表示を切り替える（boolean→従来の2択、
          // categorical→値ごとのスコア行）。selectedDtypeはコンポーネント冒頭の
          // selectedCategoricalDtype（useMaterialValuesの入力にも使う、改善計画T340）と同じ計算。
          const selectedDtype = selectedCategoricalDtype;
          return (
            <div className={styles.shapeGroup}>
              {/* 改善計画T345フォローアップ（実機フィードバック: 情報アイコンが独立した行に
                  はみ出て中央寄せに見える不具合）: .fieldはcolumn方向のflexのため、
                  兄弟要素としてただ並べると縦に積まれてしまう。.row（横方向flex）で
                  括ってラベルの隣に揃える。 */}
              <div className={styles.row}>
                <label className={styles.field}>
                  材料(material)
                  <select
                    value={draft.categoricalMaterial}
                    onChange={(e) => {
                      const nextMaterial = e.target.value;
                      const nextDtype = materialOptions.find((m) => m.id === nextMaterial)?.dtype;
                      setDraft((d) => ({
                        ...d,
                        categoricalMaterial: nextMaterial,
                        categoricalRows:
                          nextDtype === "categorical" && d.categoricalRows.length === 0
                            ? [{ value: "", score: 0 }]
                            : d.categoricalRows,
                      }));
                    }}
                  >
                    {materialOptions
                      .filter((m) => m.dtype === "boolean" || m.dtype === "categorical")
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.label}
                        </option>
                      ))}
                  </select>
                </label>
                <MaterialInfoButton option={materialOptions.find((m) => m.id === draft.categoricalMaterial)} />
              </div>
              {selectedDtype === "categorical" ? (
                <>
                  <SectionLabel
                    label="値ごとのスコア"
                    description={
                      (categoricalMaterialValues.length > 0
                        ? "値は下の候補（実データに含まれる値）から選びます。"
                        : "値は元データのタグ値と完全に一致する文字列で入力します。") +
                      "ここに設定していない値の区間は評価対象外（データなし扱い）になります。"
                    }
                  />
                  {draft.categoricalRows.map((row, i) => {
                    // 改善計画T345フォローアップ（ユーザー指摘: 候補が存在する材料では
                    // 生のタグ値の直接入力自体が不要——material_catalogに無い値を書く
                    // 実運用上の必要性は基本無く、直接入力を残すとタイプミスがそのまま
                    // 「静かに一致しない行」として残る落とし穴になる）: 候補一覧
                    // （categoricalMaterialValues）がある材料は、候補セレクトでの選択のみを
                    // 許可し、値は常にラベルの読み取り専用表示にする（生のタグ値は画面に
                    // 出さない）。候補一覧が無い材料（bicycle_infra等、動的値一覧に
                    // 対応していない）だけ、従来どおり自由テキスト入力のままにする
                    // （選ぶ元となる候補自体が存在しないため）。
                    const hasDynamicCandidates = categoricalMaterialValues.length > 0;
                    // 選択中の値のラベルは、取得済みの候補一覧（backendが返すMaterialSpec.
                    // value_labelsのラベル）から引く。候補一覧に無い値（編集を開いた時点で
                    // 既存軸が保持していたが、実データが変わり現在は候補から外れた値等）は
                    // 生のタグ値そのままにフォールバックする。
                    const label = categoricalMaterialValues.find((v) => v.value === row.value)?.label ?? row.value;
                    return (
                      <div key={i} className={styles.termRow}>
                        {hasDynamicCandidates && (
                          <select
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
                          </select>
                        )}
                        {hasDynamicCandidates ? (
                          // 改善計画T345フォローアップ（ユーザー指摘: 「選択欄」と「値の入力欄」の
                          // 2つだけで見えるようにしたい）: 実体は読み取り専用のinputにする
                          // （素のspanではなく input[type=text] にすることで、globals.cssの
                          // 共通スタイルがそのまま当たり見た目が他のinputと揃う）。編集不可
                          // （readOnly）で、値は候補セレクトからのみ設定する。
                          <input type="text" value={label} readOnly aria-label="値" placeholder="候補から選択してください" />
                        ) : (
                          <input
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
                        <button
                          type="button"
                          onClick={() => removeCategoricalRow(i)}
                          disabled={draft.categoricalRows.length <= 1}
                        >
                          削除
                        </button>
                      </div>
                    );
                  })}
                  <button type="button" className={styles.addButton} onClick={addCategoricalRow}>
                    + 値を追加
                  </button>
                </>
              ) : (
                <>
                  <div className={styles.row}>
                    <label className={styles.field}>
                      該当時(true)のスコア
                      <SliderNumberField
                        label="該当時(true)のスコア"
                        value={draft.trueScore}
                        onChange={(next) => setDraft((d) => ({ ...d, trueScore: next }))}
                        min={-100}
                        max={100}
                        step={1}
                      />
                    </label>
                    <label className={styles.field}>
                      非該当時(false)のスコア
                      <SliderNumberField
                        label="非該当時(false)のスコア"
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

  function renderDisplayPublishStep() {
    // 改善計画T404: 自動導出（derive_ramp_inputs）もdisplay_thresholds_overrideも効かず
    // 地図表示不可（kind="none"）な場合の注記（T400.mdで文言を確定済み）。新規作成中
    // （editingがnull）はまだbackendが計算したdisplayを持たないため、既存軸の編集時のみ
    // 判定する（保存すればkindが確定するため、新規作成時は保存後に軸一覧から再度開けば
    // 確認できる）。
    const showMapDisplayUnavailableNote = editing !== null && editing.display.kind === "none";
    return (
      <>
        {showMapDisplayUnavailableNote && (
          <p className={styles.hint}>
            この軸で使っている材料の一部は、まだ地図表示用のデータ取得経路が用意されていません（ルート探索のコストには反映されます）
          </p>
        )}

        <div className={styles.shapeGroup}>
          <SectionLabel
            label="地図の色分けしきい値(任意)"
            description="未設定のままなら自動計算されたしきい値が使われます。段階を細かく刻みたい場合だけ、境界値を小さい順に入力してください（例: 1, 2, 4 と入力すると、1未満／1〜2／2〜4／4以上の4段階になります）。地図表示自体ができない軸（上の注記が出ている場合）には効果がありません。"
          />
          {draft.displayThresholdsOverride === null ? (
            <button
              type="button"
              className={styles.addButton}
              onClick={() => setDraft((d) => ({ ...d, displayThresholdsOverride: [1] }))}
            >
              + しきい値を自分で設定する
            </button>
          ) : (
            <>
              {draft.displayThresholdsOverride.map((value, i) => (
                <div key={i} className={styles.termRow}>
                  {/* 改善計画T404: しきい値は軸によって整数（stop_density: 1,2,4）にも
                      小数（accident: 0.133,0.267,0.5）にもなりうるため、step="any"で
                      刻み幅を固定しない（step="0.1"のような固定刻みは、浮動小数点誤差で
                      「1」のような値さえHTML5のstep制約検証に引っかかりsubmitイベント
                      自体が発火しなくなる実バグをテスト作成時に発見・修正した）。 */}
                  <input
                    type="number"
                    step="any"
                    value={value}
                    aria-label={`しきい値${i + 1}`}
                    onChange={(e) => updateThresholdOverrideValue(i, Number(e.target.value))}
                  />
                  <button type="button" onClick={() => removeThresholdOverrideValue(i)}>
                    削除
                  </button>
                </div>
              ))}
              <div className={styles.row}>
                <button type="button" className={styles.addButton} onClick={addThresholdOverrideValue}>
                  + しきい値を追加
                </button>
                <button
                  type="button"
                  onClick={() => setDraft((d) => ({ ...d, displayThresholdsOverride: null }))}
                >
                  自動計算に戻す
                </button>
              </div>
            </>
          )}
        </div>

        <div className={styles.shapeGroup}>
          <SectionLabel
            label="地図チップ表示要素(任意)"
            description="いずれも未設定のままでよい（アイコンは汎用アイコン、略称は表示名(label)、地図の見え方パネルの説明は説明(description)がそれぞれ代わりに使われる）。"
          />
          <label className={styles.inlineCheckbox}>
            <Checkbox
              checked={draft.showMapIcon}
              onCheckedChange={(next) => setDraft((d) => ({ ...d, showMapIcon: next }))}
              aria-label="地図上にアイコンを表示する(show_map_icon)"
            />
            地図上にアイコンを表示する(show_map_icon)（オフにすると地図上チップ・地図の見え方パネルのどちらにもこの軸が現れなくなります）
          </label>
          <div className={styles.field}>
            <FieldLabel label="アイコン(icon_id)" description="地図チップに表示するアイコン。既存の意匠から選ぶ（新しい形状の追加はコード変更が必要）。" />
            <div className={styles.row}>
              <select
                value={draft.iconId}
                aria-label="アイコン(icon_id)"
                onChange={(e) => setDraft((d) => ({ ...d, iconId: e.target.value }))}
              >
                <option value="">（未設定、汎用アイコン）</option>
                {Object.entries(AXIS_ICON_PALETTE).map(([iconId, entry]) => (
                  <option key={iconId} value={iconId}>
                    {entry.label}
                  </option>
                ))}
              </select>
              {renderIconPreview()}
            </div>
          </div>

          <div className={styles.field}>
            <FieldLabel
              label="地図チップの略称(chip_label)"
              description="4文字以内（地図チップは固定サイズのタイルのため必須の上限。未設定時は表示名(label)がそのまま使われるが、正式名が4文字を超える場合はここで略称を設定すること）。"
            />
            <input
              type="text"
              value={draft.chipLabel}
              aria-label="地図チップの略称(chip_label)"
              onChange={(e) => setDraft((d) => ({ ...d, chipLabel: e.target.value }))}
              maxLength={4}
              placeholder="例: 未舗装"
            />
          </div>

          <label className={styles.fieldFull}>
            地図の見え方パネル向け説明文(panel_hint)
            <textarea
              value={draft.panelHint}
              onChange={(e) => setDraft((d) => ({ ...d, panelHint: e.target.value }))}
              rows={2}
              placeholder="一般ユーザー向けに噛み砕いた説明文（未設定時は説明(description)がそのまま使われる）"
            />
          </label>
        </div>

        <label className={styles.inlineCheckbox}>
          <Checkbox
            checked={draft.isPublished}
            onCheckedChange={(next) => setDraft((d) => ({ ...d, isPublished: next }))}
            aria-label="公開する"
          />
          公開する（一般向けルート設定画面に表示。公開後は更新・削除ができなくなります——改良は複製から）
        </label>
      </>
    );
  }

  return (
    <form onSubmit={handleSubmit} className={styles.composer}>
      <p className={styles.stepIndicator}>
        ステップ {stepIndex + 1}/{STEPS.length}: {STEP_TITLES[step]}
      </p>

      {step === "basic" && renderBasicStep()}
      {step === "shape_kind" && renderShapeKindStep()}
      {step === "shape_params" && renderShapeParamsStep()}
      {step === "display_publish" && renderDisplayPublishStep()}

      {error && <p className={styles.errorText}>{error}</p>}

      <div className={styles.row}>
        {stepIndex > 0 && (
          <button type="button" onClick={goBack} disabled={saving}>
            戻る
          </button>
        )}
        {step !== "display_publish" ? (
          // 実機不具合の修正: keyを付けずtype="button"↔"submit"を切り替えると、
          // 同じ場所（ツリー上の位置）にある同じ要素種別(button)としてReactがDOMノードを
          // 再利用し、type属性だけをその場で書き換える（要素の作り直しをしない）。
          // 「次へ」クリックでgoNext()がstepIndexを進めてこの分岐が切り替わると、
          // クリックを受けたその<button>自身のtype属性が"button"→"submit"へ同期的に
          // 書き換わり、ブラウザ側のクリックのデフォルト動作判定（type="submit"なら
          // フォーム送信）がこの書き換え後のtypeを見てしまい、「次へ」を押しただけで
          // フォームが暗黙に送信されてしまっていた（本番環境で発生していた「ウィザードの
          // 4/4画面に着くと勝手に閉じる」不具合の原因——実際には閉じたのではなく、
          // 未変更のドラフトのまま無言で保存・成功しモーダルが閉じていた）。
          // key を変えることでReactに「別の要素」と認識させ、既存ノードを書き換えず
          // 必ずunmount→mountさせる（type属性がクリック後に書き変わる余地を無くす）。
          <button key="next" type="button" onClick={goNext} className={styles.saveButton}>
            次へ
          </button>
        ) : (
          <button key="submit" type="submit" disabled={saving} className={styles.saveButton}>
            {saving ? "保存中..." : isNew ? "作成する" : "更新する"}
          </button>
        )}
        {!isNew && (
          <button type="button" onClick={onCancelEdit} disabled={saving}>
            編集をやめる
          </button>
        )}
      </div>
    </form>
  );
}
