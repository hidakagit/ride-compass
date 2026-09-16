"""app/batch/refresh_derived.py（改善計画T281段階2）の単体テスト。

各段（既存バッチのrun/run_match/run_default）を呼ぶ薄いオーケストレーションのため、実DBは
使わず各段をモックして呼び出し順序・引数の伝播・失敗時の停止・--skip-landcoverの挙動だけを
検証する。
"""

from pathlib import Path

import pytest

from app.batch import refresh_derived


def _record_calls(monkeypatch, calls: list[str], *, fail_at: str | None = None, exit_code_at: str | None = None):
    async def _fake(label: str, database_url, dry_run):
        calls.append(label)
        if label == fail_at:
            raise RuntimeError(f"{label} failed")
        if label == exit_code_at:
            return 1
        return 0

    # **差し替える段は`_STAGES`から導く**。ここへ段を並べると、`_STAGES`へ足した段が
    # 差し替えられないまま**実DBへ本物のSQLを投げる**——CIのテストDBにテーブルが
    # 出来ているかは他のワーカーの進み方次第で、同じコードが通ったり落ちたりする
    # （⑭が並べ忘れられており、実際にそうなっていた。docs/tasks/T900.md）。
    for label, module, attr in refresh_derived._STAGES:
        monkeypatch.setattr(module, attr, lambda db, dr, _label=label: _fake(_label, db, dr))


async def test_run_calls_all_stages_in_dependency_order(monkeypatch):
    calls: list[str] = []
    _record_calls(monkeypatch, calls)

    result = await refresh_derived.run(database_url=None, dry_run=False)

    assert result == 0
    # 期待する並びも`_STAGES`から導く（ここへ並べると、段を足したときに期待値の側だけが
    # 古くなる。登録漏れは下のファイル一覧との突き合わせが見る）。
    assert calls == [label for label, _, _ in refresh_derived._STAGES]


async def test_run_propagates_database_url_and_dry_run_to_every_stage(monkeypatch):
    """全段へdatabase_url・dry_runがそのまま渡り、_STAGESの順に呼ばれる。

    差し替える段は`_STAGES`から導く——手で並べると、段を足したときにその段だけ本物が
    走り（テスト用のダミーURLへ接続しにいく）、渡し漏れも検出できないまま緑になる。
    """
    seen: list[tuple[str, object, bool]] = []

    async def _fake(label: str, database_url, dry_run):
        seen.append((label, database_url, dry_run))
        return 0

    for label, module, attr in refresh_derived._STAGES:
        monkeypatch.setattr(
            module, attr, lambda db, dr, _label=label: _fake(_label, db, dr)
        )

    await refresh_derived.run(database_url="postgresql://example", dry_run=True)

    assert seen == [
        (label, "postgresql://example", True) for label, _, _ in refresh_derived._STAGES
    ]
    # 段の数そのものは書かない（増減のたびに古くなる）。全段が呼ばれたことと、
    # 母集団が空でないことだけを見る（登録漏れは下のファイル一覧との突き合わせが見る）。
    assert len(seen) == len(refresh_derived._STAGES) > 0


async def test_run_stops_immediately_when_a_stage_fails(monkeypatch):
    calls: list[str] = []
    _record_calls(monkeypatch, calls, fail_at="⑥precompute_edge_attribute_counts")

    with pytest.raises(RuntimeError, match="⑥precompute_edge_attribute_counts failed"):
        await refresh_derived.run(database_url=None, dry_run=False)

    # ④⑤⑥までは呼ばれ、⑥の失敗で⑦⑧⑨⑩は呼ばれない（fail-fast、部分的に古いデータの
    # まま後続段が進むのを避ける設計）。
    assert calls == ["④presplit_road_graph", "⑤precompute_road_node_degrees", "⑥precompute_edge_attribute_counts"]


async def test_run_stops_and_propagates_when_a_stage_returns_nonzero(monkeypatch):
    """段が例外ではなく非0の終了コードを返した場合も後続を実行せず、そのコードを返す。

    戻り値を捨てていると「派生データ再構築が完了しました」と出して終了コード0を返し、
    disaster recovery手順が欠損した派生データのまま次工程へ進む。
    """
    calls: list[str] = []
    _record_calls(monkeypatch, calls, exit_code_at="⑥precompute_edge_attribute_counts")

    result = await refresh_derived.run(database_url=None, dry_run=False)

    assert result == 1
    assert calls == ["④presplit_road_graph", "⑤precompute_road_node_degrees", "⑥precompute_edge_attribute_counts"]


async def test_run_skip_landcover_omits_only_that_stage(monkeypatch):
    calls: list[str] = []
    _record_calls(monkeypatch, calls)

    result = await refresh_derived.run(database_url=None, dry_run=False, skip_landcover=True)

    assert result == 0
    # 「土地被覆の段**だけ**が抜ける」ことを見る。抜ける段を名指しし、残りは`_STAGES`から
    # 導く（残りを並べると、段を足したときにこの期待値の側だけが古くなる）。
    skipped = [label for label, _, _ in refresh_derived._STAGES if "landcover" in label]
    assert len(skipped) == 1
    assert calls == [label for label, _, _ in refresh_derived._STAGES if label not in skipped]


def test_every_precompute_batch_module_is_registered_as_a_stage():
    """`app/batch/precompute_*.py`の全ファイルが`_STAGES`に登録されていること。

    段を手書きで列挙するテストだけだと、新しいprecomputeバッチを足したときに
    `_STAGES`への登録漏れとテストの列挙漏れが同時に起き、「派生データ再構築の単一
    エントリポイント」が黙ってそのバッチを飛ばす（列は埋まらないまま完了ログが出る）。
    ファイル一覧を正としてつき合わせ、登録し忘れをその場で落とす。
    """
    batch_dir = Path(refresh_derived.__file__).parent
    on_disk = {path.stem for path in batch_dir.glob("precompute_*.py")}
    registered = {module.__name__.rsplit(".", 1)[-1] for _, module, _ in refresh_derived._STAGES}

    assert on_disk - registered == set()


def test_every_stage_names_an_existing_callable():
    """`_STAGES`は関数名を文字列で持つ（monkeypatchを効かせるため）ので、綴りの誤りは
    実行時までエラーにならない。全段について実行前に解決できることを確かめる。"""
    for label, module, attr_name in refresh_derived._STAGES:
        assert callable(getattr(module, attr_name, None)), f"{label}: {attr_name}が無い"
