"""match_designations.pyのDELETE/INSERT安全策(改善計画T73)の統合テスト。

ridecompass_test DB(conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ)への
実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

import logging

import asyncpg
import pytest
import pytest_asyncio

from app.batch._common import asyncpg_dsn
from app.batch.match_designations import _write_matches, run_match
from app.domain.designation import DESIGNATION_MATCH_MIN_RATIO
from app.domain.graph import WaySpec
from tests.conftest import TEST_DATABASE_URL

# road_graph_session/road_graph_repository（conftest.py）はDB接続確立コスト削減のため
# ファイル単位で1本のエンジン・イベントループを使い回す設計。ファイル内の全テストの
# イベントループスコープをそれに合わせる必要がある。
# xdist_group="postgis": 改善計画T233フォローアップ。同じridecompass_test DBを使う
# 全PostGIS統合テストファイルを同一workerへ固定し直列実行させる（本ファイルはasyncpgで
# 追加の直接接続も張るため特に重要、docs/testing.mdパターン2）。
pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis")]

NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)
OSM_WAY_ID = 100


@pytest_asyncio.fixture(loop_scope="module")
async def designation_conn(road_graph_session):
    # road_graph_sessionはテーブル作成・後始末のためだけに依存する(接続不可時のskipも
    # このフィクスチャ経由で効く)。実際の読み書きはbatch側と同じasyncpg直結で行う。
    conn = await asyncpg.connect(asyncpg_dsn(TEST_DATABASE_URL))
    try:
        yield conn
    finally:
        await conn.close()


async def _seed_designation_attribute(
    conn: asyncpg.Connection, osm_way_id: int, kind: str, ratio: float = 0.8
) -> None:
    await conn.execute(
        "INSERT INTO designation_attributes (osm_way_id, kind, matched_ratio, data_version, calculated_at) "
        "VALUES ($1, $2, $3, 'seed', now())",
        osm_way_id, kind, ratio,
    )


class TestWriteMatches:
    async def test_skips_delete_when_candidates_are_empty(
        self, designation_conn, road_graph_repository, road_graph_session, caplog
    ):
        # 改善計画T73: route_designationsが空(import未実行・取込失敗後)等でcandidatesが
        # 0件のとき、従来はDELETEだけ実行され既存designation_attributesが静かに全消しされていた。
        # 改善計画T74: designation_attributesはosm_raw_ways基準のため、FK制約を満たすため
        # save_raw_waysでosm_raw_ways行を用意する(road_edgesは不要)。
        way = WaySpec(osm_way_id=OSM_WAY_ID, node_ids=[1, 2], highway="residential")
        await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})
        await road_graph_session.commit()
        await _seed_designation_attribute(designation_conn, OSM_WAY_ID, "emergency_transport")

        with caplog.at_level(logging.WARNING, logger="app.batch.match_designations"):
            elapsed = await _write_matches(designation_conn, candidates=[], matched=[], data_version="test")

        assert elapsed == 0.0
        assert any("候補が0件" in r.message for r in caplog.records)
        remaining = await designation_conn.fetchval(
            "SELECT count(*) FROM designation_attributes WHERE osm_way_id = $1", OSM_WAY_ID
        )
        assert remaining == 1

    async def test_replaces_existing_rows_when_candidates_present(
        self, designation_conn, road_graph_repository, road_graph_session
    ):
        way = WaySpec(osm_way_id=OSM_WAY_ID, node_ids=[1, 2], highway="residential")
        await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})
        await road_graph_session.commit()
        await _seed_designation_attribute(designation_conn, OSM_WAY_ID, "emergency_transport", ratio=0.5)

        elapsed = await _write_matches(
            designation_conn,
            candidates=[(OSM_WAY_ID, "emergency_transport", 0.9)],
            matched=[(OSM_WAY_ID, "emergency_transport", 0.9)],
            data_version="buffer20m",
        )

        assert elapsed >= 0.0
        row = await designation_conn.fetchrow(
            "SELECT matched_ratio, data_version FROM designation_attributes WHERE osm_way_id = $1", OSM_WAY_ID
        )
        assert row["matched_ratio"] == pytest.approx(0.9)
        assert row["data_version"] == "buffer20m"

    async def test_rolls_back_delete_when_insert_fails_midway(
        self, designation_conn, road_graph_repository, road_graph_session, monkeypatch
    ):
        # T71と同じ観点: DELETE+executemanyの原子性が崩れていないことを確認する。
        way = WaySpec(osm_way_id=OSM_WAY_ID, node_ids=[1, 2], highway="residential")
        await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})
        await road_graph_session.commit()
        await _seed_designation_attribute(designation_conn, OSM_WAY_ID, "emergency_transport", ratio=0.5)

        async def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(asyncpg.Connection, "executemany", _boom)

        with pytest.raises(RuntimeError):
            await _write_matches(
                designation_conn,
                candidates=[(OSM_WAY_ID, "emergency_transport", 0.9)],
                matched=[(OSM_WAY_ID, "emergency_transport", 0.9)],
                data_version="buffer20m",
            )

        row = await designation_conn.fetchrow(
            "SELECT matched_ratio, data_version FROM designation_attributes WHERE osm_way_id = $1", OSM_WAY_ID
        )
        assert row["matched_ratio"] == pytest.approx(0.5)
        assert row["data_version"] == "seed"


# --- run_match経由の_MATCH_SQL統合テスト（バッファ交差率計算そのものの検証） ---
# match_designations.py:44-50のコメントにある通り、_MATCH_SQL（ST_Buffer/ST_Intersects/
# ST_Union）は過去にgeographyキャストでGiST索引を認識できず30分超無応答になった実績のある
# 核心ロジックだが、上のTestWriteMatchesは候補・matchedを手組みで渡すだけで_MATCH_SQL自体は
# 一度も実行していなかった。ここではrun_matchを直接実行し、既知の座標のroute_designations・
# osm_raw_waysをseedしてSQLそのもの（交差率計算・閾値フィルタ・複数指定路線の重なり）を検証する。

DESIG_KIND = "emergency_transport"
# 東西方向の指定路線（緯度35.7000固定、経度139.6990→139.7010、長さ約180m）。
DESIG_LINE = [(35.7000, 139.6990), (35.7000, 139.7010)]

WAY_MATCH_ID = 400  # 指定路線とほぼ重なる（matched_ratio ~= 1.0 を期待）
WAY_PARTIAL_ID = 401  # 指定路線を直交して横切るだけの長いWay（matched_ratio << 0.5 を期待）
WAY_FAR_ID = 402  # 指定路線から遠く離れたWay（バッファに一切交差しない）


async def _seed_route_designation(
    conn: asyncpg.Connection, kind: str, coords: list[tuple[float, float]]
) -> None:
    """route_designationsへ1行INSERTする（app/batch/import_designations.py: _INSERT_SQLと
    同じ列構成。座標は(lat, lon)のリストでLINESTRINGを組み立てる）。"""
    wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lat, lon in coords) + ")"
    await conn.execute(
        "INSERT INTO route_designations (kind, name, pref_code, attrs, source, geom, updated_at) "
        "VALUES ($1, NULL, NULL, '{}'::jsonb, 'test', ST_SetSRID(ST_GeomFromText($2), 4326), now())",
        kind, wkt,
    )


class TestRunMatch:
    async def test_intersecting_way_gets_matched_ratio(
        self, designation_conn, road_graph_repository, road_graph_session
    ):
        """指定路線とほぼ重なるWayが、正しいmatched_ratio（閾値以上）でdesignation_attributes
        へ反映されることを確認する（_MATCH_SQLの交差率計算そのもの）。"""
        way = WaySpec(osm_way_id=WAY_MATCH_ID, node_ids=[1, 2], highway="residential")
        node_coords = {1: DESIG_LINE[0], 2: DESIG_LINE[1]}
        await road_graph_repository.save_raw_ways([way], node_coords)
        await road_graph_session.commit()
        await _seed_route_designation(designation_conn, DESIG_KIND, DESIG_LINE)

        result = await run_match(TEST_DATABASE_URL, dry_run=False)

        assert result == 0
        row = await designation_conn.fetchrow(
            "SELECT matched_ratio, data_version FROM designation_attributes WHERE osm_way_id = $1 AND kind = $2",
            WAY_MATCH_ID, DESIG_KIND,
        )
        assert row is not None
        assert row["matched_ratio"] >= DESIGNATION_MATCH_MIN_RATIO
        assert row["matched_ratio"] == pytest.approx(1.0, abs=0.05)
        assert row["data_version"] == "buffer20m"

    async def test_non_intersecting_and_below_threshold_ways_are_excluded(
        self, designation_conn, road_graph_repository, road_graph_session
    ):
        """交差率が閾値未満のWay・完全に交差しないWayはdesignation_attributesへ
        反映されないことを確認する。"""
        node_coords = {
            1: DESIG_LINE[0], 2: DESIG_LINE[1],
            # 閾値未満: 指定路線をほぼ直交して横切るだけの長いWay（約2.2km）。
            # バッファ幅20mによる交差はその中の約40mのみでratio ~= 0.018。
            3: (35.690, 139.7000), 4: (35.710, 139.7000),
            # 完全に交差しない: 指定路線から遠く離れたWay。
            5: (35.750, 139.750), 6: (35.751, 139.751),
        }
        ways = [
            WaySpec(osm_way_id=WAY_PARTIAL_ID, node_ids=[3, 4], highway="residential"),
            WaySpec(osm_way_id=WAY_FAR_ID, node_ids=[5, 6], highway="residential"),
        ]
        await road_graph_repository.save_raw_ways(ways, node_coords)
        await road_graph_session.commit()
        await _seed_route_designation(designation_conn, DESIG_KIND, DESIG_LINE)

        result = await run_match(TEST_DATABASE_URL, dry_run=False)

        assert result == 0
        rows = await designation_conn.fetch(
            "SELECT osm_way_id FROM designation_attributes WHERE osm_way_id = ANY($1)",
            [WAY_PARTIAL_ID, WAY_FAR_ID],
        )
        assert rows == []

    async def test_overlapping_designations_complete_without_error(
        self, designation_conn, road_graph_repository, road_graph_session
    ):
        """複数の指定路線が重なる/隣接するケースでも例外なく完了し、ST_Unionにより
        同一(osm_way_id, kind)への交差長が二重計上されない（matched_ratioが1.0を
        超えない）ことを確認する。異なるkindは別行として独立に反映されることも確認する。"""
        way = WaySpec(osm_way_id=WAY_MATCH_ID, node_ids=[1, 2], highway="residential")
        node_coords = {1: DESIG_LINE[0], 2: DESIG_LINE[1]}
        await road_graph_repository.save_raw_ways([way], node_coords)
        await road_graph_session.commit()

        # 同一kindで完全に重複する指定路線を2本（ST_Unionによる二重計上防止の確認）。
        await _seed_route_designation(designation_conn, DESIG_KIND, DESIG_LINE)
        await _seed_route_designation(designation_conn, DESIG_KIND, DESIG_LINE)
        # 隣接する前半だけをカバーする指定路線をさらに1本（同一kind、部分重複）。
        await _seed_route_designation(
            designation_conn, DESIG_KIND, [DESIG_LINE[0], (35.7000, 139.7000)]
        )
        # 別kindの指定路線も同じWay区間に重ねる（kindごとに別行になることの確認）。
        await _seed_route_designation(designation_conn, "critical_logistics", DESIG_LINE)

        result = await run_match(TEST_DATABASE_URL, dry_run=False)

        assert result == 0
        rows = await designation_conn.fetch(
            "SELECT kind, matched_ratio FROM designation_attributes WHERE osm_way_id = $1", WAY_MATCH_ID
        )
        by_kind = {r["kind"]: r["matched_ratio"] for r in rows}
        assert set(by_kind) == {"emergency_transport", "critical_logistics"}
        for ratio in by_kind.values():
            assert ratio <= 1.0 + 1e-6
            assert ratio >= DESIGNATION_MATCH_MIN_RATIO
