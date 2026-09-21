# パフォーマンスベンチマーク

**1回の実行で判断に足るだけ測る。** 所要時間・段ごとの内訳・資源の推移を同じ実行から
取り、後から測り直さなくて済むようにする。

```
.venv/Scripts/python -m benchmarks.bench_route_generation
```

`pytest`は収集しない（ファイル名が`test_*.py`でないため）。

## 何を出すか

- **冷（初回）と温（2回目以降）を分ける。** キャッシュが空の初回は利用者が実際に待つ
  時間で、暖機として捨ててよい値ではない
- **段の内訳を全部出す。** 実装が`key=value`で出す所要をログから構造化して拾う。
  同じ段が何度も出るときは足し合わせる（上書きすると全体で使った時間が消える）
- **資源の推移**（`_resources.py`）。Python側がCPUを使い切っているのか、DBを待って
  いるのか、どちらでもなく取り合っているのかを、同じ実行から言えるようにする

## 構成を並べて比べる

**同じ引数で`DATABASE_URL`だけ変えて2回走らせる。** 揃えるべきものが揃っていない
比較は、速い遅いを言えない。

```
DATABASE_URL=...旧 BENCH_LABEL=旧構成 python -m benchmarks.bench_route_generation
DATABASE_URL=...新 BENCH_LABEL=新構成 python -m benchmarks.bench_route_generation
```

引数は環境変数で渡す（`BENCH_ORIGIN`・`BENCH_DISTANCE_KM`・`BENCH_RUNS`・
`BENCH_LABEL`・`BENCH_JSON`）。`BENCH_JSON=1`で最後に1行のJSONも出すので、構成間の
差分を機械で取れる。

## どのコードを測ったか

`_revision.py`が実行時に作業コピーの素性（HEAD・`origin/master`との一致・未コミットの
変更）を出す。数字だけが残ると、古いコードのもっともらしい値と見分けが付かない。
