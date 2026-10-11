"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button/Button";
import { DialogContent, DialogRoot } from "@/components/ui/Dialog/Dialog";
import { RecallSavedIcon, SaveConditionsIcon } from "@/components/ui/icons/icons";
import { Input } from "@/components/ui/Input/Input";
import { textVariants } from "@/components/ui/Text/Text";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup/ToggleGroup";
import {
  describeConditions,
  originDescription,
  type GenerationConditionsSnapshot,
  type SavedCondition,
} from "@/features/route/savedConditions";
import SavedList from "@/features/route/SavedList/SavedList";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { cn } from "@/lib/cn";

interface SaveConditionsButtonProps {
  /** 保存した設定（同じ名前があれば上書きと出す）。 */
  saved: SavedCondition[];
  /** いまの設定（出発地を除く）。保存の前に、何が保存されるかを並べる。 */
  current: GenerationConditionsSnapshot;
  /** 名前の欄に最初から入れておく仮の名前（いまの条件から作る）。 */
  suggestedName: string;
  /** 出発地を地図で置いたか（置いていれば、出発地を固定して保存するのが既定）。 */
  originManual: boolean;
  /** 出発地が分かっているか（分からない間は固定できない）。 */
  originKnown: boolean;
  onSave: (name: string, fixOrigin: boolean) => void;
}

interface SavedConditionsPanelProps {
  saved: SavedCondition[];
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

// 「ルート設定」の見出しの、いまの設定を保存するアイコン。押すと窓で、残るもの（条件・出発地の扱い・重みの割合・除外）だけを
// 並べてから名前を付けて保存する（残らないものや重みを変えたかは書かない）。保存は設定を組んだその場で、呼び出しは
// 「保存」タブの「設定」で行う（地点の保存が地点の詳しくの星で、一覧が「保存」タブの「地点」なのと同じ分け方）。
export function SaveConditionsButton({
  saved,
  current,
  suggestedName,
  originManual,
  originKnown,
  onSave,
}: SaveConditionsButtonProps) {
  const catalog = useAxisCatalog();
  // 手で書き換えるまでは、いまの条件から作る仮の名前を出す（条件を変えると名前の案も変わる）。
  const [nameDraft, setNameDraft] = useState<string | null>(null);
  const name = nameDraft ?? suggestedName;
  const overwriting = saved.some((entry) => entry.name === (name.trim() || suggestedName));
  // 選ぶまでは、出発地を地図で置いたかで決める（触らなければ、地図で置いた地点は固定・現在地は呼び出した時の現在地）。
  const [fixOriginDraft, setFixOriginDraft] = useState<boolean | null>(null);
  const fixOrigin = originKnown && (fixOriginDraft ?? originManual);
  // 窓を開いているか。保存すると閉じる。
  const [saving, setSaving] = useState(false);
  // 窓を開くまで読まないが、見出しの行はページと一緒に描き直されるので、条件が変わったときだけ組む。
  const currentDescription = useMemo(() => describeConditions(current, catalog), [current, catalog]);

  return (
    <>
      <Button
        size="panelIcon"
        aria-label="いまの設定を保存"
        aria-haspopup="dialog"
        aria-expanded={saving}
        usage="いまの設定（条件・出発地・重み・除外）を開いて確かめ、名前を付けてこの端末に保存します。保存した設定は「保存」タブの「設定」から呼び出せます。"
        onClick={() => setSaving(true)}
      >
        <SaveConditionsIcon size={18} />
      </Button>
      <DialogRoot open={saving} onOpenChange={setSaving}>
        <DialogContent title="いまの設定を保存">
          <div className="flex flex-col gap-2">
            <DescriptionRows
              rows={[
                ["条件", currentDescription.route],
                [
                  "出発地",
                  <ToggleGroup
                    key="origin"
                    aria-label="保存する出発地"
                    value={fixOrigin ? "fixed" : "current"}
                    onValueChange={(value) => setFixOriginDraft(value === "fixed")}
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
                  </ToggleGroup>,
                ],
                ["重み", currentDescription.weights],
                ["除外", currentDescription.exclusions],
              ]}
            />
            <form
              className="flex items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                onSave(name, fixOrigin);
                setNameDraft(null);
                setFixOriginDraft(null);
                setSaving(false);
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
          </div>
        </DialogContent>
      </DialogRoot>
    </>
  );
}

// 「ルート設定」区分の「保存」タブの「設定」。保存した設定の一覧と、呼び出す・消すだけを置く（保存は見出しのアイコン）。
// 一覧の行は名前とアイコンの操作だけで、呼び出すと窓で中身を見せ、「反映する」で各タブの値と地図のピンが入れ替わる。
// 生成はいつもの「ルート生成」で行う（入れ替えたあとに値を確かめたり少し変えたりできる）。
export default function SavedConditionsPanel({ saved, onRecall, onRemove }: SavedConditionsPanelProps) {
  const catalog = useAxisCatalog();
  // 呼び出すを押した設定。確認の窓で中身を見せ、「反映する」を押すまで入れ替えない。
  const [recalling, setRecalling] = useState<SavedCondition | null>(null);
  const [recalled, setRecalled] = useState<SavedCondition | null>(null);
  const recallingDescription = recalling && describeConditions(recalling, catalog);

  return (
    <div className="flex flex-col gap-3">
      {/* 知らせの行は読み上げが変化を拾えるよう常に置き、空の間は上の隙間ごと畳む。 */}
      <p role="status" className={cn(textVariants({ variant: "hint" }), "empty:-mt-3")}>
        {recalled !== null && saved.some((entry) => entry.name === recalled.name)
          ? `「${recalled.name}」を反映しました。`
          : ""}
      </p>

      <SavedList
        items={saved}
        noun="設定"
        howToSave="「ルート設定」の見出しの「いまの設定を保存」で、いまの設定に名前を付けて保存します。保存した設定はここから呼び出せます。"
        renderMain={(entry) => <span className="min-w-0 flex-auto truncate font-semibold">{entry.name}</span>}
        renderActions={(entry) => (
          <Button
            size="panelIcon"
            aria-label={`「${entry.name}」を呼び出す`}
            aria-haspopup="dialog"
            aria-expanded={recalling?.name === entry.name}
            usage="この設定の中身を窓で見て、「反映する」で各タブの値と地図の地点を入れ替えます。作るのはいつもの「ルート生成」です。"
            onClick={() => setRecalling(entry)}
          >
            <RecallSavedIcon size={18} />
          </Button>
        )}
        onRemove={(entry) => onRemove(entry.name)}
      />
      <DialogRoot
        open={recalling !== null}
        onOpenChange={(open) => {
          if (!open) setRecalling(null);
        }}
      >
        {recalling !== null && recallingDescription !== null && (
          <DialogContent title={`「${recalling.name}」を反映します`}>
            <DescriptionRows
              rows={[
                ["条件", recallingDescription.route],
                ["出発地", originDescription(recalling.origin !== null)],
                ["重み", recallingDescription.weights],
                ["除外", recallingDescription.exclusions],
              ]}
            />
            <div className="mt-3 flex justify-end gap-2">
              <Button size="sm" onClick={() => setRecalling(null)}>
                キャンセル
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => {
                  onRecall(recalling);
                  setRecalled(recalling);
                  setRecalling(null);
                }}
              >
                反映する
              </Button>
            </div>
          </DialogContent>
        )}
      </DialogRoot>
    </div>
  );
}
