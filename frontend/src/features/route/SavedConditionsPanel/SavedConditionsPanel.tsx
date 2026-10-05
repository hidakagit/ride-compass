"use client";

import { useState } from "react";

import Disclosure from "@/components/Disclosure/Disclosure";
import { Button } from "@/components/ui/Button/Button";
import { Card } from "@/components/ui/Card/Card";
import { ConfirmDialog } from "@/components/ui/Dialog/Dialog";
import { Input } from "@/components/ui/Input/Input";
import { textVariants } from "@/components/ui/Text/Text";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup/ToggleGroup";
import {
  describeConditions,
  originDescription,
  type GenerationConditionsSnapshot,
  type SavedCondition,
} from "@/features/route/savedConditions";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { cn } from "@/lib/cn";

interface SavedConditionsPanelProps {
  saved: SavedCondition[];
  /** いまの設定（出発地を除く）。保存の前に、何が保存されるかを並べる。 */
  current: Omit<GenerationConditionsSnapshot, "origin">;
  /** 名前の欄に最初から入れておく仮の名前（いまの条件から作る）。 */
  suggestedName: string;
  /** 出発地を地図で置いたか（置いていれば、出発地を固定して保存するのが既定）。 */
  originManual: boolean;
  /** 出発地が分かっているか（分からない間は固定できない）。 */
  originKnown: boolean;
  onSave: (name: string, fixOrigin: boolean) => void;
  onRecall: (entry: SavedCondition) => void;
  onRemove: (name: string) => void;
}

function DescriptionRows({ rows }: { rows: [term: string, detail: React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[length:var(--font-size-sm)]">
      {rows.map(([term, detail]) => (
        <div key={term} className="contents">
          <dt className="text-[var(--color-muted)]">{term}</dt>
          <dd className="m-0 min-w-0">{detail}</dd>
        </div>
      ))}
    </dl>
  );
}

// 「ルート設定」区分の「保存」タブ。保存の前に、何が保存され出発地をどう扱うかを並べる。呼び出すと各タブの値と
// 地図のピンが入れ替わり、生成はいつもの「ルート生成」で行う（入れ替えたあとに値を確かめたり少し変えたりできる）。
export default function SavedConditionsPanel({
  saved,
  current,
  suggestedName,
  originManual,
  originKnown,
  onSave,
  onRecall,
  onRemove,
}: SavedConditionsPanelProps) {
  const catalog = useAxisCatalog();
  // 手で書き換えるまでは、いまの条件から作る仮の名前を出す（条件を変えると名前の案も変わる）。
  const [nameDraft, setNameDraft] = useState<string | null>(null);
  const name = nameDraft ?? suggestedName;
  const overwriting = saved.some((entry) => entry.name === (name.trim() || suggestedName));
  // 選ぶまでは、出発地を地図で置いたかで決める（触らなければ、地図で置いた地点は固定・現在地は呼び出した時の現在地）。
  const [fixOriginDraft, setFixOriginDraft] = useState<boolean | null>(null);
  const fixOrigin = originKnown && (fixOriginDraft ?? originManual);
  const [recalled, setRecalled] = useState<SavedCondition | null>(null);
  // ✕を押した設定の名前。確認の窓で「消す」を押すまで消さない。
  const [removing, setRemoving] = useState<string | null>(null);
  const currentDescription = describeConditions(current, catalog);

  return (
    <div className="flex flex-col gap-3">
      <Card variant="outline" className="flex flex-col gap-2">
        <h3 className={textVariants({ variant: "heading" })}>いまの設定を保存</h3>
        <DescriptionRows
          rows={[
            ["条件", currentDescription.route],
            [
              "出発地",
              <div key="origin" className="flex flex-col gap-1">
                <ToggleGroup
                  aria-label="保存する出発地"
                  value={fixOrigin ? "fixed" : "current"}
                  onValueChange={(value) => setFixOriginDraft(value === "fixed")}
                  className="self-start"
                >
                  <ToggleGroupItem value="current" usage="呼び出すたびに、その時いる場所から作ります。">
                    呼び出した時の現在地
                  </ToggleGroupItem>
                  <ToggleGroupItem
                    value="fixed"
                    disabled={!originKnown}
                    usage="いまの出発地を保存して、いつもそこから作ります。"
                  >
                    今の出発地に固定
                  </ToggleGroupItem>
                </ToggleGroup>
                <span className={textVariants({ variant: "hint" })}>
                  {fixOrigin
                    ? "いまの出発地を保存し、どこで呼び出してもその地点から作ります"
                    : "どこで呼び出しても、その時いる場所から作ります"}
                </span>
              </div>,
            ],
            ["重み", currentDescription.weights],
            ["除外", currentDescription.exclusions],
          ]}
        />
        <p className={textVariants({ variant: "hint" })}>
          出発時刻・想定速度・走行方位は保存しません（その日に決めます）
        </p>
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            onSave(name, fixOrigin);
            setNameDraft(null);
            setFixOriginDraft(null);
          }}
        >
          <Input
            aria-label="保存する名前"
            className="min-w-0 flex-auto"
            value={name}
            onChange={(event) => setNameDraft(event.target.value)}
            data-usage="いまの設定に付ける名前です。そのまま保存もできます。"
          />
          <Button
            type="submit"
            size="sm"
            className="flex-none"
            usage="上に並べた設定を、この名前でこの端末に保存します。同じ名前があれば上書きします。"
          >
            {overwriting ? "上書き保存" : "保存"}
          </Button>
        </form>
      </Card>

      <p role="status" className={textVariants({ variant: "hint" })}>
        {recalled !== null && saved.some((entry) => entry.name === recalled.name)
          ? `「${recalled.name}」の条件・重み・除外にしました。出発地は${
              recalled.origin === null ? "今いる場所" : "保存した地点"
            }です。「ルート生成」で作れます。`
          : ""}
      </p>

      <h3 className={textVariants({ variant: "heading" })}>保存した設定</h3>
      {saved.length === 0 ? (
        <p className={textVariants({ variant: "hint" })}>まだありません。</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {saved.map((entry) => {
            const description = describeConditions(entry, catalog);
            return (
              <li key={entry.name} className="rounded-sm border border-[var(--color-border)] px-1.5 py-1">
                <Disclosure
                  headerClassName="flex items-center gap-1"
                  triggerClassName="group flex min-w-0 items-center gap-1.5"
                  bodyClassName="pt-1"
                  usage="押すと、この設定に保存した出発地・重み・除外を開きます。"
                  summary={
                    <>
                      <span
                        aria-hidden="true"
                        className="size-1.5 flex-none -rotate-45 border-r-2 border-b-2 border-[var(--color-neutral)] transition-transform duration-150 group-data-[state=open]:rotate-45"
                      />
                      <span className="flex min-w-0 flex-col">
                        <span className="truncate font-semibold">{entry.name}</span>
                        <span className={cn(textVariants({ variant: "hint" }), "truncate")}>{description.route}</span>
                      </span>
                    </>
                  }
                  trailing={
                    <>
                      <Button
                        size="sm"
                        className="ml-auto flex-none"
                        aria-label={`「${entry.name}」を呼び出す`}
                        usage="この設定で各タブの値と地図の地点を入れ替えます。作るのはいつもの「ルート生成」です。"
                        onClick={() => {
                          onRecall(entry);
                          setRecalled(entry);
                        }}
                      >
                        呼び出す
                      </Button>
                      <Button
                        variant="ghost"
                        size="bare"
                        className="flex-none p-1 text-xs"
                        aria-label={`「${entry.name}」を消す`}
                        onClick={() => setRemoving(entry.name)}
                      >
                        ✕
                      </Button>
                    </>
                  }
                >
                  <DescriptionRows
                    rows={[
                      ["出発地", originDescription(entry.origin !== null)],
                      ["重み", description.weights],
                      ["除外", description.exclusions],
                    ]}
                  />
                </Disclosure>
              </li>
            );
          })}
        </ul>
      )}
      <ConfirmDialog
        open={removing !== null}
        title={`「${removing ?? ""}」を消します`}
        confirmLabel="消す"
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          if (removing === null) return;
          setRemoving(null);
          onRemove(removing);
        }}
      >
        消した設定は元に戻せません。
      </ConfirmDialog>
    </div>
  );
}
