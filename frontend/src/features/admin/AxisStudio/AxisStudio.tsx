"use client";

import { useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs/Tabs";
import { DialogContent, DialogRoot } from "@/components/ui/Dialog/Dialog";
import { MATERIAL_CATALOG, materialCatalogLabel } from "@/lib/axisMaterialsCatalog";
import {
  createAxisDefinition,
  deleteAxisDefinition,
  listAxisDefinitions,
  unpublishAxisDefinition,
  updateAxisDefinition,
} from "@/features/admin/adminApi";
import { bandColorsFor, RAMP_AXIS_VALUE_KIND } from "@/lib/mapDisplay/valueScale";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import type { AxisDefinitionPayload, AxisDefinitionResponse, AxisShape } from "@/types/route";
import AxisComposer from "./AxisComposer";
import { Button } from "@/components/ui/Button/Button";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import { cardVariants } from "@/components/ui/Card/Card";

// shapeが参照する材料id一覧（`kind`ごとにフィールド名が異なるため統一する）。この中には
// 材料カタログの材料idだけでなく、他axis_idを指すもの（他axis_idを材料として参照する
// 内部軸階層）も混在しうる。
function materialIdsOf(shape: AxisShape): string[] {
  if (shape.kind === "categorical") return [shape.material];
  return shape.terms.map((t) => t.material);
}

// shapeのtermは材料idと他の軸idのどちらも指しうる。軸として見つかればその表示名を、
// 見つからなければ材料カタログから引く。
function labelForMaterialOrAxis(id: string, definitions: readonly AxisDefinitionResponse[]): string {
  return definitions.find((d) => d.axis_id === id)?.label ?? materialCatalogLabel(id, MATERIAL_CATALOG);
}

// 「この軸を削除しようとしたら、他の軸から材料として参照されていた」という事実が
// 見えないまま削除できてしまう問題への対応。削除の可否は制限せず、削除前に参照元と
// その影響をユーザーへ明示する。
function axesReferencing(axisId: string, definitions: readonly AxisDefinitionResponse[]): AxisDefinitionResponse[] {
  return definitions.filter((d) => d.axis_id !== axisId && materialIdsOf(d.shape).includes(axisId));
}

// 軸スタジオのトップレベルコンポーネント。一覧取得・作成・更新・削除の状態管理をここに
// 集約し、フォーム自体はAxisComposerへ委ねる。認証・route handler経由の詳細は
// docs/modules/frontend/axis-studio.md「AxisStudio.tsx（一覧・状態管理）」節参照。
export default function AxisStudio() {
  const [definitions, setDefinitions] = useState<AxisDefinitionResponse[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [editingAxisId, setEditingAxisId] = useState<string | null>(null);
  const [deletingAxisId, setDeletingAxisId] = useState<string | null>(null);
  const [unpublishingAxisId, setUnpublishingAxisId] = useState<string | null>(null);
  // 「調整する」で一時的に下書きへ戻した軸。保存時に公開へ戻す。編集を中断した場合は
  // 下書きのまま残るため、その事実を`notice`で必ず知らせる（黙って非公開になると
  // 一般ユーザー向けの軸カタログから消えたことに気づけない）。
  const [republishAxisId, setRepublishAxisId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // 複製元。nullでなければAxisComposerを「新規作成」モードのままduplicateFromの内容で
  // 初期化する（axis_idは空のまま、is_publishedは常にfalseへ落とす——公開済み軸を
  // 複製しても複製先は下書きから始まる）。
  const [duplicateFrom, setDuplicateFrom] = useState<AxisDefinitionResponse | null>(null);
  // 「新しい軸を作る」ボタンを押したときだけtrueになる。編集・複製・新規作成のいずれかを
  // 選んだときだけモーダル（components/ui/Dialog）でAxisComposerを開く（一覧を隠さない・
  // 目的の操作を選んでから開く導線）。
  const [creatingNew, setCreatingNew] = useState(false);
  const composerOpen = editingAxisId !== null || duplicateFrom !== null || creatingNew;

  async function reload() {
    setListError(null);
    try {
      const list = await listAxisDefinitions();
      setDefinitions(list);
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    }
  }

  // effect本体からの直接同期setState呼び出しを避け、マイクロタスク経由で実行する
  // （react-hooks/set-state-in-effect対策、SystemStatusPanel.tsxと同じ流儀）。
  // マウント時に一度だけ読み込む。
  useEffect(() => {
    Promise.resolve().then(() => reload());
  }, []);

  /** モーダルを閉じる。`republished`は「保存で公開へ戻したか」で、**呼び出し側が渡す**
   * ——`setRepublishAxisId(null)`の直後に呼んでも、この関数が読む`republishAxisId`は
   * そのレンダーのクロージャのままで、再公開に成功した直後に「下書きのまま残った」と
   * 通知してしまう（Reactのstate更新は次のレンダーまで反映されない）。 */
  function closeComposer(republished = false) {
    if (republishAxisId !== null && !republished) {
      setNotice(
        `「調整する」で下書きへ戻したまま編集を終えました。この軸は一般ユーザーには表示されません。` +
          `下書きタブで編集を保存すると公開へ戻ります。`,
      );
    }
    setRepublishAxisId(null);
    setEditingAxisId(null);
    setDuplicateFrom(null);
    setCreatingNew(false);
  }

  async function handleSave(payload: AxisDefinitionPayload, isNew: boolean) {
    let republished = false;
    if (isNew) {
      await createAxisDefinition(payload);
    } else {
      // 「調整する」で一時的に下書きへ戻した軸は、保存と同時に公開へ戻す
      // （公開済み軸は不変という原則は保ったまま、unpublish→更新→再公開という
      // 正規の手順をボタン1つに畳んだもの）。
      republished = republishAxisId === payload.axis_id;
      await updateAxisDefinition(payload.axis_id, republished ? { ...payload, is_published: true } : payload);
    }
    await reload();
    closeComposer(republished);
  }

  async function handleAdjustPublished(def: AxisDefinitionResponse) {
    // 公開済み軸の材料・計算式・折れ点を変えるには一度下書きへ戻す必要がある
    // （backendの`check_publish_immutability`）。その手順をここで畳む。
    setNotice(null);
    setUnpublishingAxisId(def.axis_id);
    try {
      await unpublishAxisDefinition(def.axis_id);
      await reload();
      setRepublishAxisId(def.axis_id);
      setEditingAxisId(def.axis_id);
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    } finally {
      setUnpublishingAxisId(null);
    }
  }

  function handleDuplicate(def: AxisDefinitionResponse) {
    setEditingAxisId(null);
    setCreatingNew(false);
    setDuplicateFrom(def);
  }

  async function handleUnpublish(axisId: string) {
    // 公開済み軸を下書きへ戻す。一般ユーザー向けの軸カタログから即座に消えるが、利用者の画面は保存した
    // 重みのキーをカタログへ合わせ直す（features/route/routePreferenceSync.ts）ので、消えた軸の重みは残らない。
    setUnpublishingAxisId(axisId);
    try {
      await unpublishAxisDefinition(axisId);
      await reload();
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    } finally {
      setUnpublishingAxisId(null);
    }
  }

  async function handleDelete(axisId: string) {
    // 削除しようとしている軸が他の軸から材料として参照されている場合、その事実と
    // 影響を確認ダイアログで明示する（一律拒否はしない——内部軸を整理・再設計するために
    // 意図的に削除したい場面もありうるため、最終判断はユーザーに委ねる）。
    const referencing = definitions ? axesReferencing(axisId, definitions) : [];
    if (referencing.length > 0) {
      const names = referencing.map((d) => d.label).join("・");
      const confirmed = window.confirm(
        `この軸は次の軸から材料として参照されています: ${names}\n削除すると、それらの軸が正しく評価できなくなります（評価対象外になります）。\n本当に削除しますか？`,
      );
      if (!confirmed) return;
    }
    setDeletingAxisId(axisId);
    try {
      await deleteAxisDefinition(axisId);
      await reload();
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingAxisId(null);
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
  const previewIsRamp = catalog.rampAxes.some((axis) => axis.axisId === previewAxisId);
  const previewMapValueKind = previewIsRamp ? RAMP_AXIS_VALUE_KIND : previewCatalogAxis?.mapValueKind;
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

  function renderRowMain(def: AxisDefinitionResponse) {
    return (
      <div className="flex min-w-0 flex-col">
        <span className={textVariants({ variant: "heading" })} title={`axis_id: ${def.axis_id}`}>
          {def.label}
        </span>
        <span className={cn(textVariants({ variant: "hint" }), "[overflow-wrap:anywhere]")}>
          {def.category} ・ 重み{def.default_weight.toFixed(2)} ・{" "}
          {materialIdsOf(def.shape)
            .map((id) => labelForMaterialOrAxis(id, definitions ?? []))
            .join("・")}
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {listError && <p className={textVariants({ variant: "error" })}>{listError}</p>}
      {notice && <p className={textVariants({ variant: "error" })}>{notice}</p>}

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
          {draftDefs.map((def) => (
            <div
              key={def.axis_id}
              className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border)] pb-2 last:border-b-0 last:pb-0"
            >
              {renderRowMain(def)}
              <div className="flex flex-wrap gap-1">
                <Button size="sm" onClick={() => setEditingAxisId(def.axis_id)}>
                  編集
                </Button>
                <Button size="sm" onClick={() => handleDuplicate(def)}>
                  複製して新規作成
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => handleDelete(def.axis_id)}
                  disabled={deletingAxisId === def.axis_id || (definitions?.length ?? 0) <= 1}
                  title={(definitions?.length ?? 0) <= 1 ? "最後の1軸は削除できません" : undefined}
                >
                  削除
                </Button>
              </div>
            </div>
          ))}
        </TabsContent>

        <TabsContent className={cn(cardVariants({ variant: "outline" }), "flex flex-col gap-2")} value="published">
          {publishedDefs.length === 0 && (
            <p className={textVariants({ variant: "hint" })}>公開済みの軸はありません。</p>
          )}
          {publishedDefs.map((def) => (
            <div
              key={def.axis_id}
              className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border)] pb-2 last:border-b-0 last:pb-0"
            >
              {renderRowMain(def)}
              <div className="flex flex-wrap gap-1">
                <Button
                  size="sm"
                  onClick={() => setEditingAxisId(def.axis_id)}
                  title="材料・計算式・重みは変更できません。地図チップ・色分けしきい値等の表示専用フィールドのみ編集できます"
                >
                  表示だけ編集
                </Button>
                <Button
                  size="sm"
                  onClick={() => handleAdjustPublished(def)}
                  disabled={unpublishingAxisId === def.axis_id}
                  title="材料・計算式・折れ点を変更します。編集中は一時的に下書きへ戻り、保存すると公開へ戻ります"
                >
                  調整する
                </Button>
                <Button size="sm" onClick={() => handleDuplicate(def)}>
                  複製して新規作成
                </Button>
                <Button
                  size="sm"
                  onClick={() => handleUnpublish(def.axis_id)}
                  disabled={unpublishingAxisId === def.axis_id}
                  title="一般ユーザー向けの軸カタログから外し、下書きへ戻します（削除するにはこの後もう一度「削除」を押します）"
                >
                  非公開に戻す
                </Button>
              </div>
            </div>
          ))}
        </TabsContent>
      </Tabs>

      <Button
        size="sm"
        className="self-start font-bold"
        onClick={() => {
          setEditingAxisId(null);
          setDuplicateFrom(null);
          setCreatingNew(true);
        }}
      >
        + 新しい軸を作る
      </Button>

      <DialogRoot
        open={composerOpen}
        onOpenChange={(open) => {
          if (!open) closeComposer();
        }}
      >
        {/* 既定のDialogContentは幅min(90vw,28rem)・高さ内容依存だが、AxisComposerは可変長のリストを
            持つ大きなフォームなので、幅と最大の高さ・縦スクロールを広げる（cn()のtwMergeが既定の幅を
            上書きする）。 */}
        <DialogContent title={composerTitle} className="w-[min(94vw,42rem)] max-h-[85vh] overflow-y-auto">
          <AxisComposer
            key={editingAxisId ?? (duplicateFrom ? `duplicate-${duplicateFrom.axis_id}` : "new")}
            editing={editingDefinition}
            duplicateFrom={duplicateFrom}
            otherAxes={definitions ?? []}
            mapBandColors={mapBandColors}
            mapValueUnit={mapValueUnit}
            republishing={republishAxisId !== null && republishAxisId === editingAxisId}
            onCancelEdit={() => closeComposer()}
            onSave={handleSave}
          />
        </DialogContent>
      </DialogRoot>
    </div>
  );
}
