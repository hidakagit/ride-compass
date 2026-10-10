---
paths:
  - "backend/app/**"
  - "frontend/src/types/generated/**"
  - "backend/scripts/export_openapi.py"
---

# デプロイ・DB同期の作業標準

コード変更と本番環境（DB・デプロイ）の同期について、「作業として何を完了条件に含めるか」の運用ルールだけを書く。
個々のモジュールの設計・実装事実は`docs/modules/*.md`が持つ。

## コミットと同時に揃えるもの

次は**同一コミットで**実施する。

- **宣言（backend側のAPIルーター・Pydanticモデル・レジストリ・domain定数、MVT焼き込み値（CASE式・材料タグ・domain純関数））を
  変えたら、生成物（`frontend/src/types/generated/`）を同一コミットで作り直す**（タイル世代は手で上げない。`app/infrastructure/cache_identity.py`参照）。
- **API・ドメイン概念・レイヤー種を新設するタスクは、完了条件へ
  docs/architecture/・docs/modules/の追従を既定で含める**（書き分けはdocs/architecture/README.md「書き分け」）。
  どちらもコード変更と同一コミットで更新する。
- **評価軸（`axis_definitions`テーブル）の追加・削除・調整はコミットではなく、
  `.claude/skills/production-data/SKILL.md`の「本番へ効かせたい軸定義の変更は、本番の管理APIへ入れる」で行う。**
- **新しいコードが読む前提（表・列・行データの形）を本番DBに揃えてから、その`backend/**`の変更をmasterへ入れる（マージする）**。
  masterに入ってCI（`.github/workflows/ci.yml`）が通ると、backendは本番へ自動デプロイされ、止める仕組みは無い。
  - 表・列を足す: 本番に無い表を読むコードが出ると、その表を読む口がデプロイのあと失敗し、派生の作り直しも本番の今の表を写して
    作業用のスキーマを作るので動かない。読まずに宣言だけ足す表は、出したあとに作ってよい。空の表の作り方は
    `.claude/skills/production-data/SKILL.md`の「本番に空の表を足す」。
  - 既存の行データを新しいコードが読めなくなる変更（Pydanticモデルの破壊的変更等）: 新旧どちらの形の行も読めるコードを先に出し、
    本番の行を新しい形へ移してから、旧の形を読む口を消す（本番で動くコードが読めない行が残る間を作らない）。旧の口を消すことは、
    そのタスクの完了の条件に残す。
