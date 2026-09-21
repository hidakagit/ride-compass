import asyncio
import hashlib
import os
import re
from pathlib import Path

from app.infrastructure.proj_data import pin_bundled_proj_data

# rasterioをimportする前に呼ぶ必要があるため、他のimportより先に置く。
pin_bundled_proj_data()

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.batch._common import asyncpg_dsn
from app.infrastructure import redis_client, tile_persistent_cache, tile_score_matrix_cache
from app.infrastructure.orm_base import Base
from app.infrastructure.road_graph_repository import (
    REQUIRED_EXTENSIONS,
    RoadGraphRepository,
    create_tables,
)
from app.config import settings
from tests.axis_system_fixture import fixture_axis_definitions
from tests.admin_auth import ADMIN_PASSWORD, ADMIN_USERNAME


@pytest.fixture
def admin_credentials(monkeypatch):
    """管理画面APIのBasic認証を、テスト用の固定の認証情報で通るようにする。"""
    monkeypatch.setattr(settings, "admin_basic_auth_username", ADMIN_USERNAME)
    monkeypatch.setattr(settings, "admin_basic_auth_password", ADMIN_PASSWORD)

@pytest.fixture(autouse=True)
def _reset_redis_circuit_breaker():
    """redis_client.pyのサーキットブレーカー状態をテスト間でリセットする（改善計画T387）。

    グローバル状態（プロセス内モジュール変数）のため、Redis疎通不能をシミュレートする
    テストが1つでも実行されると、リセットせずに残る限り無関係な後続テスト（正常系の
    フェイクRedisを使うテスト）まで「クールダウン中」と誤判定されてしまう。
    """
    redis_client.reset_circuit_breaker()
    yield
    redis_client.reset_circuit_breaker()


@pytest.fixture(autouse=True)
def _use_temp_tile_persistent_cache_dir(tmp_path, monkeypatch):
    """ディスク永続化キャッシュ（改善計画T538、infrastructure/tile_persistent_cache.py）の
    保存先をテストごとの一時ディレクトリへ差し替える。

    `graph_material_cache.clear()`・`tile_score_matrix_cache.clear()`（本ファイル・
    test_graph_service.py・test_graph_material_cache.py等の多数のautouse/個別フィクスチャが
    setup/teardownの両方で呼ぶ）は改善計画T538でディスク側（`tile_persistent_cache.
    clear_namespace`、`shutil.rmtree`相当）も削除するようになった。差し替えないと実際の
    `backend/data/tile_persistent_cache`配下を毎テストで削除・書き込みしてしまい、
    並行テスト実行（pytest-xdist）間の競合や、本体の作業ツリーへの意図しない副作用を招く
    （test_tile_cache.py: use_temp_cache_dirと同じ理由・同じパターン）。他のクリア系
    フィクスチャより先に反映される必要があるため、モジュールの先頭側に置く（pytestは
    同scope・同conftest内で宣言順に近い順序でautouseフィクスチャをセットアップする）。
    """
    original = tile_persistent_cache.CACHE_DIR
    tile_persistent_cache.use_directory(tmp_path / "tile_persistent_cache")
    yield
    tile_persistent_cache.use_directory(original)


@pytest.fixture(autouse=True)
def _clear_tile_score_matrix_cache():
    """tile_score_matrix_cache（タイル単位の静的Edge×公開軸スコア行列、改善計画T536。
    旧axis_score_cache[T534]の後継）もプロセス内グローバル状態のため、
    _reset_redis_circuit_breakerと同じ理由でテスト間の汚染を防ぐ。

    多くのテストが"e1"・"e-ab"のような慣用的なedge_idを、テストごとに異なる材料
    （way_tags・elevation_attribute等）で使い回す。本番のタイル座標は実データ由来で
    そのタイル内のEdge材料と一意に対応するため、風以外の軸別スコアをタイル単位で
    キャッシュしてよい設計が成立するが、テストの慣用edge_id・タイル座標はその前提を
    満たさないため、クリアしないと別テストが積んだキャッシュを誤って再利用してしまう
    （旧axis_score_cache時代にtest_prepare_applies_precomputed_gradient_to_search_costで
    実際に発生・発覚した問題と同種）。
    """
    tile_score_matrix_cache.clear()
    yield
    tile_score_matrix_cache.clear()


@pytest.fixture(autouse=True, scope="session")
def _fixture_axis_definitions():
    """全テストへ一貫した軸システムを用意する（tests/axis_system_fixture.py）。

    **ここを個々のテストファイルへ移さない**——付け忘れたファイルは`AXIS_DEFINITIONS`が
    空のまま、重み空・軸スコアNoneという退化した状態でも例外なく緑になる。

    自前で`AXIS_DEFINITIONS`を書き換えて戻すテストとは独立に動く（あちらは「テスト開始
    時点の中身」を憶えて戻すだけで、その中身がここ由来でも変わらない）。
    """
    with fixture_axis_definitions():
        yield


# road_graph_repository.pyのPostGIS統合テスト専用の接続先。開発機で稼働中の実DB
# (ridecompass, backend/.envのDATABASE_URLが指す先)とは別のテスト専用DBを使う
# (docs/osm-pbf-import.md関連の進行中データに触れないため)。ローカルでのみ実行する
# 前提で、環境変数postgis_database_url()で上書き可能にしておく（CIはこの経路で注入する）。
TEST_DATABASE_SERVER = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432"
#: 作業ツリーの場所を書いておくDB。消してよいかの判断に使う（drop_orphan_test_databases.py）。
TEST_DATABASE_MAINTENANCE = f"{TEST_DATABASE_SERVER}/postgres"
WORKTREE_ROOT = Path(__file__).resolve().parents[2]


def default_test_database_name(root: Path) -> str:
    """その作業ツリー専用のテストDB名。

    同じDBを複数のセッションが同時に書き換えると、変更と無関係なテストが落ちる
    （落ちたファイルを単独で回すと通るため、毎回切り分けに時間を取られる）。名前は
    チェックアウトの場所から導くので、**同じ作業ツリーでは同じDBを再利用する**
    ——PostGIS拡張とテーブルの作成を毎回払わずに済む。ディレクトリ名だけでは別の場所に
    同名の作業ツリーがあると衝突するため、絶対パスのダイジェストを添える。
    """
    slug = re.sub(r"[^a-z0-9]+", "_", root.name.lower()).strip("_")[:24] or "wt"
    return f"ridecompass_test_{slug}_{hashlib.sha1(str(root).encode('utf-8')).hexdigest()[:8]}"


#: 作業ツリー専用のDBを作れない環境（ロールにCREATEDBが無い等）での退避先。
#: **分離できないことより、PostGISテストが丸ごと走らなくなる方が害が大きい。**
SHARED_TEST_DATABASE = "ridecompass_test"
#: 複製元。`CREATE EXTENSION postgis`はsuperuserを要求する（postgisはtrusted拡張ではない）
#: ため、空のDBを作っても拡張を入れられない。**拡張を持つDBを複製する**ことで、
#: superuserなしで使えるDBを増やせる。
TEMPLATE_TEST_DATABASE = "ridecompass_test_template"
#: 同時に作ろうとして競り負けたときの例外。PostgreSQLは競争の負け側へ、宣言的な
#: 42P04（duplicate_database）ではなく23505（unique_violation、pg_databaseの一意索引違反）を
#: 返すことがある。**片方だけを捕まえると、並行実行のときだけ退避してしまう。**
ALREADY_CREATED = (asyncpg.DuplicateDatabaseError, asyncpg.UniqueViolationError)
#: 拡張が持ち込んだ表（`spatial_ref_sys`等）以外の、アプリ側の表。落とす対象を名前で
#: 並べずに依存関係から導く（表が増えてもこの問い合わせは追従する）。
APP_TABLES_SQL = """
SELECT c.relname FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
  AND NOT EXISTS (
    SELECT 1 FROM pg_depend d JOIN pg_extension e ON e.oid = d.refobjid
    WHERE d.objid = c.oid AND d.deptype = 'e')
"""


async def _ensure_template_database(conn) -> None:
    """拡張を持つ複製元を用意する（既にあれば何もしない）。

    中身の掃除は複製した側で行う。ここで掃除すると、**掃除の途中の姿を別のセッションが
    複製しうる**——並行セッションを前提にする以上、順序に依存する形にしない。
    """
    if await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEMPLATE_TEST_DATABASE):
        return
    try:
        await conn.execute(
            f'CREATE DATABASE "{TEMPLATE_TEST_DATABASE}" TEMPLATE "{SHARED_TEST_DATABASE}"')
    except ALREADY_CREATED:
        return  # 別のセッションが同時に作った。それを使う
    await conn.execute(f"COMMENT ON DATABASE \"{TEMPLATE_TEST_DATABASE}\" IS $rc$(template)$rc$")


async def _clear_app_tables(url: str) -> None:
    """複製に引き継がれたアプリ側の表を落とす。

    テストは自分でテーブルを作る（`Base.metadata.create_all`）ので、複製元に残っていた
    表と行が初期状態に混ざらないようにする。落とす対象は名前で並べず、**拡張が持ち込んだ
    表（`spatial_ref_sys`等）ではないこと**から導く。
    """
    conn = await asyncpg.connect(asyncpg_dsn(url))
    try:
        for row in await conn.fetch(APP_TABLES_SQL):
            await conn.execute(f'DROP TABLE IF EXISTS public."{row["relname"]}" CASCADE')
    finally:
        await conn.close()


async def _create_database_if_absent(name: str, owner_path: str) -> bool:
    conn = await asyncpg.connect(asyncpg_dsn(TEST_DATABASE_MAINTENANCE))
    try:
        if await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            return False
        await _ensure_template_database(conn)
        for _ in range(10):
            try:
                # CREATE DATABASEはトランザクションの中で実行できないため、asyncpgの
                # 暗黙のトランザクションに入らない単発のexecuteで発行する。
                await conn.execute(f'CREATE DATABASE "{name}" TEMPLATE "{TEMPLATE_TEST_DATABASE}"')
                break
            except ALREADY_CREATED:
                return False  # 別のセッションが同時に作った。それを使う
            except asyncpg.ObjectInUseError:
                # 複製元へ誰かが繋いでいる間は複製できない。掴んでいるのは作った直後の
                # 掃除だけで、すぐ離れる。
                await asyncio.sleep(0.5)
        else:
            raise RuntimeError(f"複製元 {TEMPLATE_TEST_DATABASE} が使用中のままで複製できません")
        # **なぜこのDBがあるのかをDB自身に持たせる**。作業ツリーが消えたら、この記録だけを
        # 見て捨ててよいと判断できる（残骸を名前から推測しない）。
        await conn.execute(f"COMMENT ON DATABASE \"{name}\" IS $rc${owner_path}$rc$")
    finally:
        await conn.close()
    await _clear_app_tables(f"{TEST_DATABASE_SERVER}/{name}")
    return True


#: この実行の接続先。`pytest_collection_modifyitems`が1回だけ決める。
_RESOLVED_DATABASE_URL: str | None = None


def postgis_database_url() -> str:
    """PostGIS統合テストの接続先。

    定数ではないのは、**用意を試みるまで行き先が決まらない**ため（作業ツリー専用のDBを
    作れない環境では共有DBへ退避する）。名前を`test_`で始めないのは、pytestが
    テスト関数として収集してしまうため。
    """
    if _RESOLVED_DATABASE_URL is not None:
        return _RESOLVED_DATABASE_URL
    # フックを経ていない呼び出し（pytest外からのimport等）。DBを作らずに行き先だけ答える。
    return os.environ.get("TEST_DATABASE_URL") or (
        f"{TEST_DATABASE_SERVER}/{default_test_database_name(WORKTREE_ROOT)}"
    )


def _prepare_worktree_database() -> str:
    name = default_test_database_name(WORKTREE_ROOT)
    try:
        created = asyncio.run(_create_database_if_absent(name, str(WORKTREE_ROOT)))
    except Exception as exc:  # noqa: BLE001 作れない理由はそのまま伝える
        print(
            f"作業ツリー専用のテストDBを用意できないため、共有の{SHARED_TEST_DATABASE}を使います"
            f"（並行セッションと衝突しうる）: {exc}\n"
            f"  分けるには: psql -U postgres -c \"ALTER ROLE ridecompass CREATEDB;\""
        )
        return f"{TEST_DATABASE_SERVER}/{SHARED_TEST_DATABASE}"
    if created:
        print(f"テストDB {name} を作成しました（この作業ツリー専用）")
    return f"{TEST_DATABASE_SERVER}/{name}"


def pytest_collection_modifyitems(config, items):
    """PostGISテストが1件でも選ばれていれば、この実行の接続先を決めて用意する。

    ここで済ませるのは、**同期のまま・イベントループの外で・1回だけ**行える唯一の場所だから
    （`asyncio.run`は実行中のループの中からは呼べず、フィクスチャの中では遅い）。
    `-m "not postgis"`の実行には接続を1本も足さない。
    """
    global _RESOLVED_DATABASE_URL
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        _RESOLVED_DATABASE_URL = explicit
        return
    if not any(item.get_closest_marker("postgis") for item in items):
        return
    _RESOLVED_DATABASE_URL = _prepare_worktree_database()


# ローカル環境では新規DB接続の確立自体に1〜2秒かかる（実測、asyncpg接続確立コスト。
# localhost/127.0.0.1どちらでも同程度でDNS起因ではない）。以前はテスト関数ごとに
# エンジンを新規作成しており、規模の大きいtest_road_graph_repository.py（約80件）
# だけで2分近く溶けていた。asyncpgの接続はイベントループに束縛されテスト関数ごとの
# イベントループをまたいで使い回せないため、エンジンと（それが乗る）イベントループを
# ファイル（モジュール）単位に広げ、ファイル内の全テストで1本の接続を使い回す。
# これを使うテストファイル側は `pytestmark = pytest.mark.asyncio(loop_scope="module")`
# を付けてイベントループのスコープを合わせる必要がある。


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def road_graph_engine():
    """テストファイル単位で使い回すエンジン。PostGIS拡張の有効化とテーブル一式
    （空間インデックス込み）の作成もこの中で1回だけ行う。

    **スキップしてよいのは接続できないときだけ**。用意そのものの失敗——拡張の不足、
    ORM宣言とDBの食い違い——をスキップにすると、そのファイルのテストが1件も走らないまま
    緑になり、「DBが無い環境」と見分けが付かなくなる。そのため接続の確認と用意を分け、
    用意の失敗は例外のまま落とす。
    """
    engine = create_async_engine(postgis_database_url())
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 接続できない理由はそのまま伝える
        await engine.dispose()
        # URLはそのまま出さない（パスワードを含む）。行き先はDB名で足りる。
        database = postgis_database_url().rsplit("/", 1)[-1]
        pytest.skip(f"テストDB {database} へ接続できないためスキップ: {exc}")

    # 拡張はアプリと同じ一覧から入れる（テスト側で書き写すと、スキーマが新しい拡張を
    # 要求し始めたときにここだけ古いまま「型が存在しません」で落ちる）。入れられない
    # 権限のときは握って進み、何が足りないかはcreate_tables()に言わせる。
    for extension in REQUIRED_EXTENSIONS:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
        except Exception:  # noqa: BLE001
            pass
    await create_tables(engine)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="module")
async def road_graph_session(road_graph_engine) -> AsyncSession:
    """テストごとに空の状態から始めて後始末（truncate）するセッションを提供する。"""
    async with AsyncSession(road_graph_engine, expire_on_commit=False) as session:
        yield session
        await session.rollback()

    async with road_graph_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture(loop_scope="module")
async def road_graph_repository(road_graph_session: AsyncSession) -> RoadGraphRepository:
    return RoadGraphRepository(road_graph_session)
