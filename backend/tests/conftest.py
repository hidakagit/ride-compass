import asyncio
import functools
import hashlib
import logging
import os
import re
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from app.infrastructure.proj_data import pin_bundled_proj_data

# rasterioをimportする前に呼ぶ必要があるため、他のimportより先に置く。
pin_bundled_proj_data()

import asyncpg
import fakeredis
import freezegun
import pytest
import pytest_asyncio
import redis.asyncio
from hypothesis import settings as hypothesis_settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.batch.common import asyncpg_dsn
from app.infrastructure import (
    debug_log,
    jma_area_boundaries,
    rate_limiter,
    redis_client,
    road_network_store,
    tile_cache,
    tile_persistent_cache,
)
from app.infrastructure.derived_data_freshness import derived_tables
from app.infrastructure.derived_data_meta import DerivedStageRow
from app.infrastructure.orm_base import declared_metadata
from app.infrastructure.road_graph_repository import (
    REQUIRED_EXTENSIONS,
    RoadGraphRepository,
    create_tables,
)
from app.config import settings
from app.services import derived_data_revision_service
from scripts.schema_gap import collect_gaps
from tests.admin_auth import ADMIN_PASSWORD, ADMIN_USERNAME

# hypothesisは1例ごとに壁時計の締め切り（既定200ms）を持ち、超えると落とす。共有のランナーでは同じ例の所要時間が
# 実行ごとに揺れて別のテストが落ちるため外す。止まったテストはpytest-timeoutが落とす。
hypothesis_settings.register_profile("ridecompass", deadline=None)
hypothesis_settings.load_profile("ridecompass")


@pytest.fixture
def admin_credentials(monkeypatch, request):
    """管理画面APIのBasic認証を、テスト用の固定の認証情報で通るようにする。

    `indirect`で`(ユーザー名, パスワード)`を渡すと、その値を置く（`("", "")`なら認証情報が無い本番の状態）。
    """
    username, password = getattr(request, "param", (ADMIN_USERNAME, ADMIN_PASSWORD))
    monkeypatch.setattr(settings, "admin_basic_auth_username", username)
    monkeypatch.setattr(settings, "admin_basic_auth_password", password)


@pytest.fixture
def road_network_root(monkeypatch, tmp_path) -> Path:
    """道路網の置き場（`road_network_store.ROOT`）を、テストごとの空の一時ディレクトリへ移したパス。

    前のテストが読み込んだ道路網は置き場の場所が違うので使われない。
    """
    root = tmp_path / "road_network"
    monkeypatch.setattr(road_network_store, "ROOT", root)
    return root


@pytest.fixture
def boundary_path(monkeypatch, tmp_path) -> Path:
    """区域の境界の置き場（`jma_area_boundaries.BOUNDARY_PATH`）を、テストごとの一時ディレクトリの下へ移したパス。
    ファイルはまだ無い（読めない置き場）。"""
    path = tmp_path / "jma_area" / "boundaries.json"
    monkeypatch.setattr(jma_area_boundaries, "BOUNDARY_PATH", path)
    return path


@pytest.fixture
def restore_debug_mode():
    """debug_modeの切替の口を叩いたテストのあとで、debug_modeとルートロガーのレベルを元に戻す。

    どちらもプロセス全体で共有される可変状態で、残すと後のテストのログの拾い方が変わる
    （ルートロガーがINFOのままだと、`caplog.at_level`の外で出たINFOまで拾われる）。
    """
    original_debug_mode = settings.debug_mode
    original_level = logging.getLogger().level
    yield
    settings.debug_mode = original_debug_mode
    logging.getLogger().setLevel(original_level)


@pytest.fixture(autouse=True)
def _closed_redis_circuit_breaker():
    """redis_client.pyのサーキットブレーカーは閉じた状態から始める。

    状態はプロセス内のモジュール変数に残るため、Redis疎通不能をシミュレートするテストが
    1つでも実行されると、無関係な後続テスト（正常系のフェイクRedisを使うテスト）まで
    「クールダウン中」と誤判定されてしまう。
    """
    redis_client.record_redis_success()


@pytest.fixture
def clock():
    """時計を止める（freezegun）。`tick(秒)`で進めたぶんだけ進み、`move_to`でその時刻へ飛ぶ。

    `time.time`・`time.monotonic`・`datetime.now`をまとめて止めるので、読む口がどれでも同じ時刻になる。
    イベントループは実時間のまま（`real_asyncio`）——止めると`asyncio.sleep`が永遠に明けない。
    止める時刻は秒の端数を持たせない。大きな時刻どうしの差で境界を見るテストが、端数の丸めで1刻み
    ずれないため。

    `ignore`はpytest自身の計時（`--durations`）を実時間に保つ。freezegunは呼び出し元から数段の
    フレームのモジュール名で除外を判定するため、`_pytest`全体を除外すると、テスト関数から直接読んだ
    時計まで（数段上にpytestのフレームがあるので）実時間になる。除外は計時を呼ぶ`_pytest.runner`だけにする。
    """
    with freezegun.freeze_time("2026-01-01 00:00:00", real_asyncio=True, ignore=["_pytest.runner"]) as frozen:
        yield frozen


@pytest.fixture
def redis_server():
    """Redisの代役（fakeredis）のサーバ。`connected = False`にすると、以後のコマンドが接続の失敗になる。

    テストごとに作る——サーバを渡さずに作ったfakeredisのクライアントは同じ接続先どうしで中身を共有し、
    前のテストが書いたキーが残る。
    """
    return fakeredis.FakeServer()


@pytest.fixture
async def fake_redis(monkeypatch, redis_server):
    """空のRedis。接続を作る所（`redis.asyncio.from_url`）を同じサーバのfakeredisへ差し、共有クライアントを
    閉じる口（`redis_client.py: close_redis_client`）で作る前に戻すので、`get_redis_client_or_none`を読むどの
    モジュールからも同じものが見える。返すのはその共有クライアントで、値は生のバイト列で返る。"""
    monkeypatch.setattr(redis.asyncio, "from_url", functools.partial(fakeredis.FakeAsyncRedis.from_url, server=redis_server))
    await redis_client.close_redis_client()
    yield redis_client.get_redis_client_or_none()
    await redis_client.close_redis_client()


class MonotonicClock:
    """回数制限・外部I/Oの記録・データの世代の読み直しが読む単調時計。止まっていて、進めたぶんだけ進む。"""

    def __init__(self) -> None:
        self._now = 0.0

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture(autouse=True, scope="session")
def _monotonic_clock_for_the_session():
    """回数制限・外部I/Oの記録・データの世代の読み直しが読む時計を、テストが進める時計へ替える。

    戻すのはセッションの終わりだけ。途中で実時計へ戻すと、進めた時計で数えた回数・窓の始まり・TTLが
    未来の時刻として残り、後のテストに食い込む。freezegun（`clock`）はこの時計を動かさない——止めた時刻は
    2026年の暦の秒で、実時計の単調時計より大きいので、戻った後の窓・TTLが明けなくなる。
    """
    clock = MonotonicClock()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rate_limiter, "time", clock)
        patch.setattr(debug_log, "time", clock)
        patch.setattr(derived_data_revision_service, "time", clock)
        yield clock


@pytest.fixture(autouse=True)
def monotonic_clock(_monotonic_clock_for_the_session) -> MonotonicClock:
    """テストごとに、回数制限の窓・警告の抑制の窓・データの世代のTTLのどれよりも長く進める。

    どれもプロセス大域の記録で、進めないと前のテストの回数が今のテストの上限に食い込み、前のテストの
    窓の中で警告が抑えられ、前のテストが読んだ世代のままTTLの内側でリポジトリが世代を聞かれない。
    記録そのものには触らない。
    """
    clock = _monotonic_clock_for_the_session
    clock.advance(
        max(
            rate_limiter.WINDOW_SECONDS,
            debug_log.WARN_WINDOW_SECONDS,
            settings.derived_data_revision_check_interval_seconds,
        )
    )
    return clock


_DISK_CACHES = {"tile_persistent_cache": tile_persistent_cache, "tile_cache": tile_cache}


@contextmanager
def _disk_caches_in(patch: pytest.MonkeyPatch, directory_of):
    """ディスクのキャッシュの置き場を差し替え、差し替える前と抜けるときに開いたキャッシュを閉じる。

    キャッシュは最初に使われたときに開かれ、置き場を差し替えても開き直さない。閉じずに置き場を変えると、
    開いたままのSQLiteが次の置き場を使うはずの呼び出しへそのまま渡る。
    """
    for name, module in _DISK_CACHES.items():
        module.close()
        patch.setattr(module, "CACHE_DIR", directory_of(name))
    try:
        yield
    finally:
        for module in _DISK_CACHES.values():
            module.close()


@pytest.fixture(autouse=True, scope="session")
def _keep_disk_caches_out_of_the_checkout(tmp_path_factory):
    """ディスクのキャッシュ（infrastructure/tile_persistent_cache.py・tile_cache.py）の置き場を、
    ワーカーごとの一時ディレクトリへ差し替える。

    キャッシュを消す・書くフィクスチャはテストファイル側にも多数あり、関数スコープの
    差し替えより前後に動くものが1つでもあると共有の`backend/data/`の置き場を
    開く——pytest-xdistのワーカー同士がそこで同じSQLiteを開き合うと`database is locked`で
    落ちる。セッションスコープは関数スコープより必ず先にセットアップされ後に片付くため、
    ここで差し替えれば順序に関わらず共有の置き場へは届かない。
    """
    with pytest.MonkeyPatch.context() as patch, _disk_caches_in(patch, tmp_path_factory.mktemp):
        yield


@pytest.fixture(autouse=True)
def _use_temp_disk_cache_dirs(tmp_path, monkeypatch, _keep_disk_caches_out_of_the_checkout):
    """テストごとに空の置き場を渡す。キャッシュを消す・書くフィクスチャは、
    これを引数に取ってから動く（同じスコープのautouseは宣言順ではなく名前順に
    セットアップされるため、順序は依存で書く）。
    """
    with _disk_caches_in(monkeypatch, lambda name: tmp_path / name):
        yield


# road_graph_repository.pyのPostGIS統合テスト専用の接続先。開発機で稼働中の実DB
# (ridecompass, backend/.envのDATABASE_URLが指す先)とは別のテスト専用DBを使う
# (取り込んだ実データに触れないため)。ローカルでのみ実行する
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
#: 拡張が持ち込んだ表（`spatial_ref_sys`等）以外の、アプリ側の表（パーティションの親を含む）。落とす対象を名前で
#: 並べずに依存関係から導く（表が増えてもこの問い合わせは追従する）。
APP_TABLES_SQL = """
SELECT c.relname FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
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

    テストは自分でテーブルを作る（`declared_metadata().create_all`）ので、複製元に残っていた
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


#: この実行の接続先。`pytest_collection_finish`が1回だけ決める。
_RESOLVED_DATABASE_URL: str | None = None


def postgis_database_url() -> str:
    """PostGIS統合テストの接続先。

    定数ではないのは、**用意を試みるまで行き先が決まらない**ため（作業ツリー専用のDBを
    作れない環境では共有DBへ退避する）。名前を`test_`で始めないのは、pytestが
    テスト関数として収集してしまうため。
    """
    if _RUNNING_ITEM is not None and _RUNNING_ITEM.get_closest_marker("postgis") is None:
        pytest.fail(
            f"{_RUNNING_ITEM.nodeid} がDBの印の無いままテストDBへつなごうとした。"
            f"{DATABASE_FIXTURE}（を使うフィクスチャ）を取れば印が付く",
            pytrace=False,
        )
    if _RESOLVED_DATABASE_URL is not None:
        return _RESOLVED_DATABASE_URL
    # フックを経ていない呼び出し（pytest外からのimport等）。DBを作らずに行き先だけ答える。
    return os.environ.get("TEST_DATABASE_URL") or (
        f"{TEST_DATABASE_SERVER}/{default_test_database_name(WORKTREE_ROOT)}"
    )


@asynccontextmanager
async def raw_connection():
    """テストDBへの生の接続（asyncpg）。取込の入口と派生の段は、SQLAlchemyのセッションではなく
    トランザクションの外のこの接続を受ける。抜けるときに閉じる。"""
    conn = await asyncpg.connect(asyncpg_dsn(postgis_database_url()))
    try:
        yield conn
    finally:
        await conn.close()


#: 生データと、派生の段が書く表（表の印から導く）と段の指紋の記録。派生の段を生の接続で回すテストは、これを空にしてから
#: 取り込む——記録が残ると、空にした表を作り直さずに段を飛ばしうる。
INGESTED_TABLES = (*(table.name for table in derived_tables()), DerivedStageRow.__tablename__, "source_features",
                   "source_runs")


async def empty_ingested_tables(conn) -> None:
    await conn.execute("TRUNCATE " + ", ".join(INGESTED_TABLES) + " CASCADE")


def _prepare_worktree_database() -> str:
    name = default_test_database_name(WORKTREE_ROOT)
    try:
        created = asyncio.run(_create_database_if_absent(name, str(WORKTREE_ROOT)))
    except Exception as exc:  # 作れない理由はそのまま伝える
        print(
            f"作業ツリー専用のテストDBを用意できないため、共有の{SHARED_TEST_DATABASE}を使います"
            f"（並行セッションと衝突しうる）: {exc}\n"
            f"  分けるには: psql -U postgres -c \"ALTER ROLE ridecompass CREATEDB;\""
        )
        return f"{TEST_DATABASE_SERVER}/{SHARED_TEST_DATABASE}"
    if created:
        print(f"テストDB {name} を作成しました（この作業ツリー専用）")
    return f"{TEST_DATABASE_SERVER}/{name}"


#: テストDBへつなぐ足場の根。これを（フィクスチャを経て間接にでも）使うテストに、DBの印を付ける。
DATABASE_FIXTURE = "road_graph_engine"

#: 準備か本体を走らせているテスト。DBの印の無いテストがテストDBへつなぐのを`postgis_database_url`で止める。
_RUNNING_ITEM: pytest.Item | None = None


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """テストDBへつなぐテストに、DBの印（`-m`で選ぶ`postgis`と、1つのワーカーへ寄せる`xdist_group`）を付ける。

    先に動くのは、`-m`の選り分けとpytest-xdistの`--dist loadgroup`が同じフックで印を読むから。
    """
    for item in items:
        if DATABASE_FIXTURE in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.postgis)
            item.add_marker(pytest.mark.xdist_group(name="postgis"))


@contextmanager
def _running(item):
    global _RUNNING_ITEM
    _RUNNING_ITEM = item
    try:
        yield
    finally:
        _RUNNING_ITEM = None


# 後片付けは見ない。ファイル単位のフィクスチャは、印の無いテストの後片付けの中で片付くことがある。
@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    with _running(item):
        return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    with _running(item):
        return (yield)


def pytest_collection_finish(session):
    """PostGISテストが1件でも選ばれていれば、この実行の接続先を決めて用意する。

    ここで済ませるのは、**同期のまま・イベントループの外で・1回だけ**行える唯一の場所だから
    （`asyncio.run`は実行中のループの中からは呼べず、フィクスチャの中では遅い）。
    `-m`の選り分けのあとに動くので、`-m "not postgis"`の実行には接続を1本も足さない。
    """
    global _RESOLVED_DATABASE_URL
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        _RESOLVED_DATABASE_URL = explicit
        return
    if not any(item.get_closest_marker("postgis") for item in session.items):
        return
    _RESOLVED_DATABASE_URL = _prepare_worktree_database()


# ローカル環境では新規DB接続の確立自体に1〜2秒かかり（asyncpgの接続確立のコストで、
# DNS起因ではない）、テスト関数ごとにエンジンを作るとテストの多いファイルで分単位になる。
# asyncpgの接続はイベントループに束縛されテスト関数ごとの
# イベントループをまたいで使い回せないため、エンジンと（それが乗る）イベントループを
# ファイル（モジュール）単位に広げ、ファイル内の全テストで1本の接続を使い回す。
# これを使うテストファイル側は `pytestmark = pytest.mark.asyncio(loop_scope="module")`
# を付けてイベントループのスコープを合わせる必要がある。


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def road_graph_engine():
    """テストファイル単位で使い回すエンジン。PostGIS拡張の有効化とテーブル一式
    （空間インデックス込み）の作成もこの中で1回だけ行う。

    **接続できないときも落とす（スキップにしない）**。スキップにすると、そのファイルの
    テストが1件も走らないまま緑になる。DBを使わない実行は`-m "not postgis"`で選ぶ。
    """
    engine = create_async_engine(postgis_database_url())
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # 接続できない理由はそのまま伝える
        await engine.dispose()
        # URLはそのまま出さない（パスワードを含む）。行き先はDB名で足りる。
        database = postgis_database_url().rsplit("/", 1)[-1]
        pytest.fail(
            f"テストDB {database} へ接続できない: {exc}（DBを使わない実行は -m \"not postgis\"）", pytrace=False
        )

    # 拡張はアプリと同じ一覧から入れる（テスト側で書き写すと、スキーマが新しい拡張を
    # 要求し始めたときにここだけ古いまま「型が存在しません」で落ちる）。入れられない
    # 権限のときは握って進み、何が足りないかはcreate_tables()に言わせる。
    for extension in REQUIRED_EXTENSIONS:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
        except Exception:
            pass
    await create_tables(engine)
    # create_tables()は在る表を直さないので、前の実行が宣言と違う形で残した表（表を入れ替える実装を壊して回した・
    # ORMの宣言を一時に壊して回した）のまま走ってしまう。宣言と差があれば、表を消して今の宣言から作り直す。
    async with engine.connect() as conn:
        gaps = await conn.run_sync(collect_gaps)
    if gaps:
        await _clear_app_tables(postgis_database_url())
        await create_tables(engine)
    # 前の実行が片付けの前に殺されると（時間切れ・中断）、その行がDBに残る。残った行は
    # 次の実行で最初に走るテストだけを落とし、そのテストの片付けで消える——単独で回すと
    # 通る失敗になる。ファイルの最初に消しておけば、どの実行も空から始まる。
    await _delete_app_rows(engine)

    yield engine
    await engine.dispose()


async def _delete_app_rows(engine) -> None:
    async with engine.begin() as conn:
        for table in reversed(declared_metadata().sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def derive_conn(road_graph_engine):
    """テストファイル単位で使い回す生の接続（`raw_connection`）。ファイルの前後で`INGESTED_TABLES`を空にする。

    `road_graph_engine`に依存するのは接続のためではなく、**スキーマを作らせるため**。生の接続は
    テーブルを作る経路を通らないので、まっさらなDB（CI）では最初の文から落ちる。
    """
    async with raw_connection() as conn:
        await empty_ingested_tables(conn)
        try:
            yield conn
        finally:
            await empty_ingested_tables(conn)


@pytest_asyncio.fixture(loop_scope="module")
async def road_graph_session(road_graph_engine) -> AsyncSession:
    """空の状態から始まり、テストの後で全行を消すセッションを提供する。"""
    async with AsyncSession(road_graph_engine, expire_on_commit=False) as session:
        yield session
        await session.rollback()

    await _delete_app_rows(road_graph_engine)


@pytest_asyncio.fixture(loop_scope="module")
async def road_graph_repository(road_graph_session: AsyncSession) -> RoadGraphRepository:
    return RoadGraphRepository(road_graph_session)
