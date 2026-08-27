"""axis_definitionsのfresh bootstrap用スナップショット読み書き（改善計画T361）。

背景: T350で`axis_definitions`テーブルをDBが唯一の正本になるよう単純化したが、
「まっさらなDBへ全migrationを適用する」fresh bootstrap経路（CI・新規開発環境・
disaster recovery）は、`backend/migrations/`配下のmigration（0014・0017・0021・0022等）
が持つ行データのINSERT/DELETEに依存したままだった。T353が軸定義の変更をmigrationでは
なくaxis_admin APIの直接操作で行った結果、fresh bootstrapが再現する内容と実際の
DB（本番/dev）の内容が乖離する不整合が発生した（T360で発覚・個別migration 0022で対症療法）。
「軸定義の変更経路がmigrationとAPIの2つ存在する限り、両者の同期漏れは構造的に再発し続ける」
（T360）というのが根本原因のため、T361でaxis_definitionsの**行データ**を管理する経路を
axis_admin APIへ一本化する。migrationは今後（0023以降）`axis_definitions`/
`axis_registry_meta`の**テーブル構造（DDL）のみ**を管理し、行データを挿入・変更する
migrationは追加しない（0014〜0022は過去の履歴としてそのまま残す。既存migrationの内容を
書き換えない、というこのプロジェクトの標準運用に従う）。

fresh bootstrap時の実データは、このモジュールが読み書きする**スナップショットファイル**
（`backend/fixtures/axis_definitions_snapshot.json`、現在の実DBの内容を
`backend/scripts/dump_axis_definitions_snapshot.py`でダンプしたもの）から用意する。

**`load_axis_definitions_snapshot`はテーブルを丸ごと空にしてから投入する（無条件、
空チェックはしない）**。これはfresh bootstrap専用ツール（`backend/scripts/
bootstrap_ci_db.py`・`backend/scripts/bootstrap_fresh_db.py`）からのみ呼ぶ設計だからで、
通常のアプリ起動経路（`main.py`のlifespan・`services/axis_registry_service.py:
refresh_axis_definitions`）や、稼働中のDBに対して繰り返し実行される`app/batch/
import_pbf.py`等からは**呼ばない**——呼ぶと、デプロイやバッチ実行のたびに本番の
生きた軸データ（API経由でチューニング済みかもしれない）がスナップショットの内容で
黙って上書きされる事故になる。`refresh_axis_definitions`の「テーブルが空なら
`AxisDefinitionSyncError`で起動自体を失敗させる」というfail-fast方針（T349/T350）は
この変更後も維持する——fresh bootstrapツールを踏まずにアプリを起動しようとした場合は、
自動修復せず起動が落ちるのが正しい挙動という判断を引き続き踏襲する。

スナップショットの更新は手動運用とする（本番/devでAPI経由の軸変更を行った後、
`dump_axis_definitions_snapshot.py`を都度手動実行してリフレッシュする）。デプロイの
たびに自動でダンプする方式も検討したが、頻度が低い操作のためデプロイパイプラインへ
組み込む複雑さ・リスクの方が上回ると判断した（軸のshape_params調整自体が「本番反映は
別途」という手動運用のため、スナップショット更新もその手動フローの延長に置くのが自然）。
"""

import json
import logging
from pathlib import Path

from app.domain.axis_definitions import AxisDefinition
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository

logger = logging.getLogger("ridecompass.axis_definitions_snapshot")

# backend/app/infrastructure/axis_definitions_snapshot.py から見て backend/fixtures/
SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "axis_definitions_snapshot.json"


async def dump_axis_definitions_snapshot(repository: AxisDefinitionRepository, path: Path = SNAPSHOT_PATH) -> int:
    """現在のDBのaxis_definitions全行＋revisionをスナップショットファイルへ書き出す。

    `scripts/dump_axis_definitions_snapshot.py`から呼ばれる。戻り値は書き出した軸数。
    """
    definitions_by_id = await repository.list_all_with_sort_order()
    revision = await repository.get_revision()
    axes = [
        {"sort_order": sort_order, "definition": definition.model_dump(mode="json")}
        for definition, sort_order in sorted(definitions_by_id.values(), key=lambda pair: pair[1])
    ]
    payload = {"revision": revision, "axes": axes}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(axes)


async def load_axis_definitions_snapshot(repository: AxisDefinitionRepository, path: Path = SNAPSHOT_PATH) -> int:
    """axis_definitionsをスナップショットファイルの内容で丸ごと置き換える（無条件）。

    fresh bootstrap専用（モジュールdocstring参照）。呼び出し側でcommit不要——このタスク
    自体で完結させる（`services/axis_registry_service.py`の各操作と同じ「サービス層関数が
    自分でcommitする」規約に揃える）。戻り値は投入した軸数。
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    await repository.delete_all()
    for entry in payload["axes"]:
        definition = AxisDefinition.model_validate(entry["definition"])
        await repository.upsert(definition, entry["sort_order"])
    # upsert()は書き込みごとにrevisionを+1するため、投入後にダンプ時点の値へ上書きする
    # （実施した書き込み回数とは無関係な、スナップショット時点の値をそのまま復元する）。
    if payload.get("revision") is not None:
        await repository.set_revision(payload["revision"])
    await repository.commit()
    logger.info("axis_definitions snapshot loaded: axes=%d path=%s", len(payload["axes"]), path)
    return len(payload["axes"])
