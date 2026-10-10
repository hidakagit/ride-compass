"use client";

import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useRef, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
import { ConfirmDialog, DialogContent, DialogRoot } from "@/components/ui/Dialog/Dialog";
import { MATERIAL_CATALOG, materialCatalogLabel } from "@/lib/axisMaterialsCatalog";
import {
  createAxisDefinition,
  deleteAxisDefinition,
  listAxisDefinitions,
  unpublishAxisDefinition,
  updateAxisDefinition,
} from "@/features/admin/adminApi";
import { bandColorsFor } from "@/lib/mapDisplay/valueScale";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import type { AxisDefinitionPayload, AxisDefinitionResponse, AxisShape } from "@/types/route";
import AxisComposer from "./AxisComposer";
import { Button } from "@/components/ui/Button/Button";
import { textVariants } from "@/components/ui/Text/Text";
import { calloutVariants } from "@/components/ui/Callout/Callout";
import { cn } from "@/lib/cn";
import { cardVariants } from "@/components/ui/Card/Card";
import { getQueryClient } from "@/lib/queryClient";
import { useIsomorphicLayoutEffect } from "@/hooks/useIsomorphicLayoutEffect";
import { errorMessage } from "@/lib/apiError";

// shapeが参照する材料id一覧（`kind`ごとにフィールド名が異なるため統一する）。この中には
// 材料カタログの材料idだけでなく、他axis_idを指すもの（他axis_idを材料として参照する
// 内部軸階層）も混在しうる。
function materialIdsOf(shape: AxisShape): string[] {
  if (shape.kind === "categorical") return [shape.material];
  return shape.terms.map((t) => t.material);
}

const LEFT_AS_DRAFT_NOTICE =
  `「調整する」で下書きへ戻したまま編集を終えました。この軸は一般ユーザーには表示されません。` +
  `下書きタブで編集を保存すると公開へ戻ります。`;

// shapeのtermは材料idと他の軸idのどちらも指しうる。軸として見つかればその表示名を、
// 見つからなければ材料カタログから引く。
function labelForMaterialOrAxis(id: string, definitions: readonly AxisDefinitionResponse[]): string {
  return definitions.find((d) => d.axis_id === id)?.label ?? materialCatalogLabel(id, MATERIAL_CATALOG);
}

// 開いているフォーム。複製は新規作成として複製元の内容で初期化する（axis_idは新しく振り、公開済み軸を複製しても
// 下書きから始まる）。`republish`は「調整する」で一時的に下書きへ戻した軸の編集で、保存時に公開へ戻す——編集を
// 中断した場合は下書きのまま残るため、その事実を必ず知らせる（黙って非公開になると一般ユーザー向けの軸カタログから
// 消えたことに気づけない）。
type ComposerTarget =
  | { mode: "edit"; axisId: string; republish: boolean }
  | { mode: "duplicate"; from: AxisDefinitionResponse }
  | { mode: "new" };

// 軸スタジオのトップレベルコンポーネント。一覧取得・作成・更新・削除の状態管理をここに
// 集約し、フォーム自体はAxisComposerへ委ねる。認証・route handler経由の詳細は
// docs/modules/frontend/axis-studio.md「AxisStudio.tsx（一覧・状態管理）」節参照。
export default function AxisStudio() {
  const definitionsQuery = useQuery({ queryKey: ["axis-definitions"], queryFn: listAxisDefinitions }, getQueryClient());
  const definitions = definitionsQuery.data ?? null;
  // 作成・更新以外の操作（下書きへ戻す・削除）の失敗。一覧を読み直すと消える。
  const [actionError, setActionError] = useState<string | null>(null);
  const listError = actionError ?? (definitionsQuery.error && errorMessage(definitionsQuery.error));
  const [deletingAxisId, setDeletingAxisId] = useState<string | null>(null);
  // 「削除」を押した軸。確認で「削除する」を押すまで消さない（消した軸を戻す手段が無いため）。
  const [confirmingDelete, setConfirmingDelete] = useState<AxisDefinitionResponse | null>(null);
  const [unpublishingAxisId, setUnpublishingAxisId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // モーダル（components/ui/Dialog）で開いているフォーム。編集・複製・新規作成のいずれかを選んだときだけ開く
  // （一覧を隠さない・目的の操作を選んでから開く導線）。
  const [composer, setComposer] = useState<ComposerTarget | null>(null);
  const editingAxisId = composer?.mode === "edit" ? composer.axisId : null;
  const duplicateFrom = composer?.mode === "duplicate" ? composer.from : null;
  const republishing = composer?.mode === "edit" && composer.republish;
  // AxisComposerのkey。別のフォームを開くと中身を作り直す。
  const composerKey =
    composer === null
      ? null
      : composer.mode === "edit"
        ? composer.axisId
        : composer.mode === "duplicate"
          ? `duplicate-${composer.from.axis_id}`
          : "new";
  // いま開いているフォーム。待った後は、押した時点に閉じ込めた値ではなくこれを見る（待つ間に閉じる・別のフォームを
  // 開くと、押した時点のフォームはもう開いていない）。
  const liveComposerKey = useRef(composerKey);
  useIsomorphicLayoutEffect(() => {
    liveComposerKey.current = composerKey;
  });

  async function reload() {
    setActionError(null);
    await definitionsQuery.refetch();
  }

  /** モーダルを閉じる。`republished`は「保存で公開へ戻したか」で、**呼び出し側が渡す**
   * ——保存を待った後に呼んでも、この関数が読む`republishing`は保存を押したレンダーの
   * クロージャのままで、再公開に成功した直後に「下書きのまま残った」と通知してしまう。 */
  function closeComposer(republished = false) {
    if (republishing && !republished) setNotice(LEFT_AS_DRAFT_NOTICE);
    setComposer(null);
  }

  async function handleSave(payload: AxisDefinitionPayload, isNew: boolean) {
    const savedKey = composerKey;
    let republished = false;
    if (isNew) {
      await createAxisDefinition(payload);
    } else {
      // 「調整する」で一時的に下書きへ戻した軸は、保存と同時に公開へ戻す
      // （公開済み軸は不変という原則は保ったまま、unpublish→更新→再公開という
      // 正規の手順をボタン1つに畳んだもの）。
      republished = republishing;
      await updateAxisDefinition(payload.axis_id, republished ? { ...payload, is_published: true } : payload);
    }
    await reload();
    // 待つ間に閉じて別のフォームを開いていたら、そのフォームは閉じない。閉じたときに出した「下書きのまま」の
    // 知らせは、保存で公開へ戻したなら外す。
    if (liveComposerKey.current === savedKey) closeComposer(republished);
    else if (republished) setNotice(null);
  }

  // 待ちの印は、自分が立てたものだけを外す（待つ間にほかの軸で立てた印を外すと、その軸の待ちの間に押せてしまう）。
  const clearUnpublishing = (axisId: string) =>
    setUnpublishingAxisId((current) => (current === axisId ? null : current));

  async function handleAdjustPublished(def: AxisDefinitionResponse) {
    // 公開済み軸の材料・計算式・折れ点を変えるには一度下書きへ戻す必要がある
    // （backendの`check_publish_immutability`）。その手順をここで畳む。
    setNotice(null);
    setUnpublishingAxisId(def.axis_id);
    try {
      await unpublishAxisDefinition(def.axis_id);
      await reload();
      // 待つ間に別のフォームを開いていたら、そのフォームを替えない（打ちかけの入力が消える）。この軸は下書きのまま残る。
      if (liveComposerKey.current !== null) {
        setNotice(LEFT_AS_DRAFT_NOTICE);
        return;
      }
      setComposer({ mode: "edit", axisId: def.axis_id, republish: true });
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      clearUnpublishing(def.axis_id);
    }
  }

  async function handleUnpublish(axisId: string) {
    // 公開済み軸を下書きへ戻す。一般ユーザー向けの軸カタログから即座に消えるが、利用者の画面は保存した
    // 重みのキーをカタログへ合わせ直す（features/route/routePreferenceSync.ts）ので、消えた軸の重みは残らない。
    setUnpublishingAxisId(axisId);
    try {
      await unpublishAxisDefinition(axisId);
      await reload();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      clearUnpublishing(axisId);
    }
  }

  // 消せるか（ほかの軸が参照している・最後の1軸）はbackendが判定し、断った理由をそのまま出す。
  async function handleDelete(axisId: string) {
    setDeletingAxisId(axisId);
    try {
      await deleteAxisDefinition(axisId);
      await reload();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setDeletingAxisId((current) => (current === axisId ? null : current));
    }
  }

  const editingDefinition = definitions?.find((d) => d.axis_id === editingAxisId) ?? null;
  // 編集中の軸を地図がどの値の種類で塗るかは、軸の形ではなく「どの経路で地図に出ているか」で
  // 決まる（ramp軸はタイルの重み付き和を、専用way値配信軸は地図表示値を塗る）。判定を持たずに
  // 軸カタログの実際の分類をそのまま引き、地図と同じ`bandColorsFor`を通すことで、しきい値
  // プレビューの色が地図とずれない。
  const catalog = useAxisCatalog();
  const previewAxisId = editingAxisId ?? duplicateFrom?.axis_id ?? null;
  const previewCatalogAxis = catalog.axes.find((axis) => axis.axisId === previewAxisId);
  const previewMapValueKind = previewCatalogAxis?.mapValueKind;
  // 軸カタログの分類をそのまま引くだけの軽い導出のため、参照の安定化はしない
  // （渡し先は節のコンポーネントで、再描画の重さは持たない）。
  const mapBandColors = previewMapValueKind
    ? (boundaries: readonly number[]) => bandColorsFor(previewMapValueKind, boundaries)
    : undefined;
  const mapValueUnit = previewCatalogAxis?.mapValueUnit ?? "";
  const composerTitle = editingDefinition
    ? editingDefinition.is_published
      ? `表示専用フィールドを編集: ${editingDefinition.label}`
      : `軸を編集: ${editingDefinition.label}`
    : duplicateFrom
      ? `「${duplicateFrom.label}」を複製して新しい軸を作る`
      : "新しい軸を作る";

  const draftDefs = definitions?.filter((d) => !d.is_published) ?? [];
  const publishedDefs = definitions?.filter((d) => d.is_published) ?? [];

  function renderRow(def: AxisDefinitionResponse, actions: ReactNode) {
    return (
      <div
        key={def.axis_id}
        className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border)] pb-2 last:border-b-0 last:pb-0"
      >
        <div className="flex min-w-0 flex-col">
          <span className={textVariants({ variant: "heading" })}>{def.label}</span>
          <span className={cn(textVariants({ variant: "hint" }), "[overflow-wrap:anywhere]")}>
            {def.axis_id} ・ {def.category} ・ 重み{def.default_weight.toFixed(2)} ・{" "}
            {materialIdsOf(def.shape)
              .map((id) => labelForMaterialOrAxis(id, definitions ?? []))
              .join("・")}
          </span>
        </div>
        <div className="flex flex-wrap gap-1">{actions}</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {listError && <p className={textVariants({ variant: "error" })}>{listError}</p>}
      {notice && <p className={calloutVariants({ tone: "warning" })}>{notice}</p>}

      {/* 下書きタブが既定表示。公開済みタブに削除ボタンは出さない（削除は先に
          「非公開に戻す」という導線を残す）。編集ボタンは「表示だけ編集」として、
          AxisComposerが編集対象の公開状態を見て自動的に表示専用フィールドのみの
          制限モードへ切り替わる（材料・計算式・重みを変えたい場合は「複製して
          新規作成」に導線を残す。詳細はdocs/modules/frontend/axis-studio.md
          「AxisStudio.tsx（一覧・状態管理）」節参照）。 */}
      <Tabs className="flex flex-col gap-2" defaultValue="draft">
        <TabsList>
          <TabsTrigger value="draft">下書き（{draftDefs.length}）</TabsTrigger>
          <TabsTrigger value="published">公開済み（{publishedDefs.length}）</TabsTrigger>
        </TabsList>

        <TabsContent className={cn(cardVariants({ variant: "outline" }), "flex flex-col gap-2")} value="draft">
          {draftDefs.length === 0 && <p className={textVariants({ variant: "hint" })}>下書きの軸はありません。</p>}
          {draftDefs.map((def) =>
            renderRow(
              def,
              <>
                <Button size="sm" onClick={() => setComposer({ mode: "edit", axisId: def.axis_id, republish: false })}>
                  編集
                </Button>
                <Button size="sm" onClick={() => setComposer({ mode: "duplicate", from: def })}>
                  複製して新規作成
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => setConfirmingDelete(def)}
                  disabled={deletingAxisId === def.axis_id}
                >
                  削除
                </Button>
              </>,
            ),
          )}
        </TabsContent>

        <TabsContent className={cn(cardVariants({ variant: "outline" }), "flex flex-col gap-2")} value="published">
          {publishedDefs.length === 0 ? (
            <p className={textVariants({ variant: "hint" })}>公開済みの軸はありません。</p>
          ) : (
            <ul className={cn(textVariants({ variant: "hint" }), "list-disc pl-5")}>
              <li>
                表示だけ編集: アイコン・色分けしきい値等の表示の項目だけを変えます。材料・計算式・重みは変えられません。
              </li>
              <li>調整する: 材料・計算式・折れ点を変えます。編集の間は一時的に下書きになり、保存で公開に戻ります。</li>
              <li>
                非公開に戻す:
                一般向けの軸カタログから外し、下書きへ戻します。削除するには、そのあと下書きの一覧で「削除」を押します。
              </li>
            </ul>
          )}
          {publishedDefs.map((def) =>
            renderRow(
              def,
              <>
                <Button size="sm" onClick={() => setComposer({ mode: "edit", axisId: def.axis_id, republish: false })}>
                  表示だけ編集
                </Button>
                <Button
                  size="sm"
                  onClick={() => handleAdjustPublished(def)}
                  disabled={unpublishingAxisId === def.axis_id}
                >
                  調整する
                </Button>
                <Button size="sm" onClick={() => setComposer({ mode: "duplicate", from: def })}>
                  複製して新規作成
                </Button>
                <Button
                  size="sm"
                  onClick={() => handleUnpublish(def.axis_id)}
                  disabled={unpublishingAxisId === def.axis_id}
                >
                  非公開に戻す
                </Button>
              </>,
            ),
          )}
        </TabsContent>
      </Tabs>

      <Button size="sm" className="self-start font-bold" onClick={() => setComposer({ mode: "new" })}>
        + 新しい軸を作る
      </Button>

      <DialogRoot
        open={composerKey !== null}
        onOpenChange={(open) => {
          if (!open) closeComposer();
        }}
      >
        {/* 既定のDialogContentは幅min(90vw,28rem)・高さ内容依存だが、AxisComposerは可変長のリストを
            持つ大きなフォームなので、幅と最大の高さ・縦スクロールを広げる（cn()のtwMergeが既定の幅を
            上書きする）。 */}
        <DialogContent title={composerTitle} className="w-[min(94vw,42rem)] max-h-[85vh] overflow-y-auto">
          <AxisComposer
            key={composerKey ?? "new"}
            editing={editingDefinition}
            duplicateFrom={duplicateFrom}
            otherAxes={definitions ?? []}
            mapBandColors={mapBandColors}
            mapValueUnit={mapValueUnit}
            republishing={republishing}
            onCancelEdit={() => closeComposer()}
            onSave={handleSave}
          />
        </DialogContent>
      </DialogRoot>

      <ConfirmDialog
        open={confirmingDelete !== null}
        title={`「${confirmingDelete?.label ?? ""}」を削除します`}
        confirmLabel="削除する"
        onCancel={() => setConfirmingDelete(null)}
        onConfirm={() => {
          if (confirmingDelete === null) return;
          setConfirmingDelete(null);
          void handleDelete(confirmingDelete.axis_id);
        }}
      >
        削除した軸は元に戻せません。
      </ConfirmDialog>
    </div>
  );
}
