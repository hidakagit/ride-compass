"""axis_definitionsのfresh bootstrap用スナップショット読み書き。

`axis_definitions`テーブルの**行データ**（軸の新規追加・既存軸の変更）はaxis_admin API
経由でのみ行い、`backend/migrations/`は0023以降テーブル構造（DDL）のみを管理する
（0014〜0022は行データを含む過去のmigrationとしてそのまま残す。既存migrationの内容を
書き換えない、というこのプロジェクトの標準運用に従う）。「まっさらなDBへ全migrationを
適用する」fresh bootstrap経路（CI・新規開発環境・disaster recovery）は、この行データを
migrationからは得られないため、代わりにこのモジュールが読み書きする**スナップショット
ファイル**（`backend/fixtures/axis_definitions_snapshot.json`、現在の実DBの内容を
`backend/scripts/dump_axis_definitions_snapshot.py`でダンプしたもの）から用意する。

**`load_axis_definitions_snapshot`はテーブルを丸ごと空にしてから投入する（無条件、
空チェックはしない）**。これはfresh bootstrap専用ツール（`backend/scripts/
bootstrap_ci_db.py`・`backend/scripts/bootstrap_fresh_db.py`）からのみ呼ぶ設計だからで、
通常のアプリ起動経路（`main.py`のlifespan・`services/axis_registry_service.py:
refresh_axis_definitions`）や、稼働中のDBに対して繰り返し実行される`app/batch/
import_pbf.py`等からは**呼ばない**——呼ぶと、デプロイやバッチ実行のたびに本番の
生きた軸データ（API経由でチューニング済みかもしれない）がスナップショットの内容で
黙って上書きされる事故になる。`refresh_axis_definitions`の「テーブルが空なら
`AxisDefinitionSyncError`で起動自体を失敗させる」というfail-fast方針は
この経路でも維持する——fresh bootstrapツールを踏まずにアプリを起動しようとした場合は、
自動修復せず起動が落ちるのが正しい挙動とする。

スナップショットの更新は手動運用とする（本番/devでAPI経由の軸変更を行った後、
`dump_axis_definitions_snapshot.py`を都度手動実行してリフレッシュする）。頻度が低い
操作のためデプロイパイプラインへ自動で組み込まず、手動フローのままにしてある。
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
