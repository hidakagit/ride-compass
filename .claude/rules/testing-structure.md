---
paths:
  - "backend/tests/structure/**"
  - "frontend/src/structure/**"
---

# ソースを読む検査と、空のループ

## ソースを読む検査は、専用ディレクトリへ置く

置き場を決める軸は**そのテストが何を読むか**である。

- **リポジトリのソースをデータとして読む**（ASTやテキストとして走査し、コードは動かさない）
  ——下の専用ディレクトリへ置く
- **コードを動かして確かめる**——横断的な不変条件を守るものでも、普通のテストとして**対象の隣へ置く**

前者のうち、CIが既に流している静的な検査（backendの`ruff.toml`・`.importlinter`・`mypy.ini`、frontendのESLint・knip）の
設定で表せて、許可リストが要らないものは、テストにせずその設定へ置く（例: web層が`app.batch`をモジュール直下で
importしない → `backend/ruff.toml`の`TID253`）。テストにするのは、自前でソースを読む（ASTの走査・一覧からの母集団）ことが
要るものと、許可リストが要るもの（ruffの`per-file-ignores`は、古くなっても落ちない）だけである。行ごとの`# noqa`で許せば
足りるものは、古くなった`# noqa`を落とす`RUF100`も`select`へ入れて、設定の側に置く。
`scripts/review_checks.py`の検知器へは置かない（[fixing.md](fixing.md)「検知器を足す条件は厳しい」）。

テストにするものの置き場は次の2か所。普通のテストと混ぜない。

| 対象 | 置き場 |
|---|---|
| backend | `backend/tests/structure/` |
| frontend | `frontend/src/structure/` |

許可リストが要るなら、**その列挙が古くなったときにテスト自身が落ちる**ようにする
（載っているのに実態が無い側も違反にする。`test_redis_skeleton.py`参照）。

## わざと壊すのは、テストの中で

検知器・ガードが効いていることは、わざと壊した入力で落ちることを見て確かめる（[fixing.md](fixing.md)「直し方」）。
**壊すのはテストの中の入力で、ソースやビルドを書き換えない。** テストの効きを実装を一時に変えて測るのは
[testing-review.md](testing-review.md)の側で、変えた行を戻すのは`scripts/break_tests.py`が持つ。

- **画面の検知器**は、壊れた状態をテストの中で作る: playwrightなら`page.addStyleTag`で崩れたスタイルを足す・
  モックの応答を差し替える、vitestなら渡す入力（props・フェイクの応答）を差し替える。ソースを書き換えて
  本番ビルドし直さない。
- **道具（`scripts/`）の仕組み**は、一時的なgitリポジトリと入力の差し替え（網・時計・書き出したファイル）で、
  入口から確かめる。
- **数分かかる本物の処理**（本番ビルド・本物の`npm ci`・E2Eの一式）は、最終確認の1回までにする。

## パターン6: 絞り込んだ母集団をループするテストは、空でないことを確かめる

実データ・生成物・定数表から条件で絞った一覧をループして要素ごとに検査するときは、絞り込んだ一覧を名前へ束ね、
空でないことを主張してから検査する。

```python
picked = [m for m, s in SPECS.items() if isinstance(s, WayMaterialCoverageSpec)]
assert picked, "way材料のカバレッジ仕様が1件も無い"
row = await fetch_values(conn, edge_id)                # 組み立てたSQLを実行した結果
for material_id in picked:
    assert row[material_id] is not None
```

```ts
const expressionColors = COLOR_EXPRESSION.filter((i) => typeof i === "string" && i.startsWith("#"));
expect(expressionColors.length).toBeGreaterThan(0);
for (const color of expressionColors) { expect(legendColors.has(color)).toBe(true); }
```

空でないことの主張は**同じテストの中**に置く。

**要素ごとの検査は、ループより`parametrize`で書く。** ループで書くのは、上の例のように1回の実I/Oの結果を要素ごとに見るときである（testing.md「ループで実I/Oを繰り返さない」）。
宣言から導いた母集団を`parametrize`へ渡す。

落とす規則は`backend/tests/structure/test_vacuous_loops.py`と`frontend/src/structure/vacuousLoops.test.ts`が持つ。
