"""PostGIS統合テストの接続先の決め方（tests/conftest.py）。

DBそのものは要らない——名前を導く規則と、環境変数を優先する契約だけを見る。
"""

from pathlib import Path

from tests.conftest import default_test_database_name, postgis_database_url


def test_different_worktrees_get_different_databases():
    # 同じDBを複数のセッションが同時に書き換えると、変更と無関係なテストが落ちる。
    a = default_test_database_name(Path("/x/worktrees/alpha"))
    b = default_test_database_name(Path("/x/worktrees/beta"))

    assert a != b


def test_the_same_worktree_gets_the_same_database():
    # 毎回違う名前にすると、PostGIS拡張とテーブルの作成を実行のたびに払うことになる。
    root = Path("/x/worktrees/alpha")

    assert default_test_database_name(root) == default_test_database_name(root)


def test_same_directory_name_in_another_place_does_not_collide():
    # ディレクトリ名だけで決めると、別の場所の同名チェックアウトと同じDBを掴む。
    a = default_test_database_name(Path("/x/worktrees/alpha"))
    b = default_test_database_name(Path("/y/worktrees/alpha"))

    assert a != b


def test_name_is_a_valid_unquoted_postgres_identifier():
    # 日本語を含むパスの下でも動く（このリポジトリの標準的な置き場所がそう）。
    name = default_test_database_name(Path("/ドキュメント/Claude/Ride Compass"))

    assert name.replace("_", "").isalnum() and name.islower()
    assert len(name.encode("utf-8")) <= 63


def test_explicit_url_wins(monkeypatch):
    # CIはこの経路で注入する。分離の仕組みが入ってもそこは変わらない。
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/given")
    monkeypatch.setattr("tests.conftest._RESOLVED_DATABASE_URL", None)

    assert postgis_database_url() == "postgresql+asyncpg://u:p@h:5432/given"
