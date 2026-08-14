"""実測ベンチマーク集（pytestの通常テストスイートには含まれない）。

`app/`のパフォーマンス上のボトルネックになりうる箇所（Road Graphのルーティング、
標高キャッシュ、ベクタタイル生成等）を、外部依存（実際のOverpass/GSI/PostGIS接続）
無しで実行できる合成データに対して計測する。pytest-benchmark等の追加依存は使わず、
`time.perf_counter`ベースの単純な計測ハーネス（`_harness.py`）のみで完結させている。

実行方法（backend/ディレクトリから、既存の`.venv`を使う場合）:
    .venv/Scripts/python -m benchmarks.run_all       # 全ベンチマーク
    .venv/Scripts/python -m benchmarks.bench_nearest_node  # 個別に1本だけ

詳細は README.md 参照。
"""
