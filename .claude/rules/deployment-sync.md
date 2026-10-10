---
paths:
  - "backend/app/**"
  - "frontend/src/types/generated/**"
  - "backend/scripts/export_openapi.py"
---

# デプロイ・DB同期の決まり

backend のコードの変更を、本番（DB・デプロイ）と文書からずらさないための決まり。括弧の番号は、導く CLAUDE.md「原則」。

## コミットと同時に揃えるもの

- **API・ドメイン概念・レイヤー種を新設するタスクは、docs/architecture/・docs/modules/ の追従を完了の条件に既定で含め、
  コードと同じコミットで書く**（書き分けは docs/architecture/README.md「書き分け」）。（原則4・3）
- **評価軸（`axis_definitions`テーブルの行）の追加・削除・調整は、コミットで入れない**。本番の管理APIへ入れる
  （.claude/skills/production-data/SKILL.md「本番へ効かせたい軸定義の変更は、本番の管理APIへ入れる」）。（原則3）
- **新しいコードが読む前提（表・列・行データの形）を本番DBに揃えてから、その`backend/**`の変更をmasterへマージする**
  （マージから本番へ出る仕組みは docs/architecture/tech-stack.md「デプロイの反映確認」）。（原則5）
  - 表・列を足す: 新しいコードが読む表・列は、マージの前に本番に作る（作り方は .claude/skills/production-data/SKILL.md
    「本番に空の表を足す」）。宣言を足すだけで読まない表は、出したあとに作ってよい。
  - 既存の行データを新しいコードが読めなくなる変更（Pydanticモデルの破壊的変更等）: 新旧どちらの形の行も読めるコードを先に出し、
    本番の行を新しい形へ移してから、旧の形を読む口を消す。本番で動くコードが読めない行が残る間を作らない。旧の口を消すことは、
    そのタスクの完了の条件に残す。
