"""PostGIS統合テストの接続先の名前の決め方（tests/conftest.py: default_test_database_name）。

DBそのものは要らない——チェックアウトの場所から名前を導く規則だけを見る。

ここで見ないもの: 接続先の選び方（`TEST_DATABASE_URL`を優先する・作れなければ共有DBへ退避する）は
pytestのフック（`pytest_collection_finish`）が実行の始めに1回決めるもので、テストの中から
その前の状態は作れない。CIの`TEST_DATABASE_URL`で全部のPostGISテストが繋がることが、その結線を通す。
"""

from pathlib import Path

from tests.conftest import default_test_database_name


def test_the_same_worktree_gets_the_same_database():
    # 毎回違う名前にすると、PostGIS拡張とテーブルの作成を実行のたびに払うことになる。
    root = Path("/x/worktrees/alpha")

    assert default_test_database_name(root) == default_test_database_name(root)


def test_same_directory_name_in_another_place_does_not_collide():
    # 同じDBを複数のセッションが同時に書き換えると、変更と無関係なテストが落ちる。
    # ディレクトリ名だけで決めると、別の場所の同名チェックアウトと同じDBを掴む。
    a = default_test_database_name(Path("/x/worktrees/alpha"))
    b = default_test_database_name(Path("/y/worktrees/alpha"))

    assert a != b


def test_name_is_a_valid_unquoted_postgres_identifier():
    # 日本語を含むパスの下でも動く（このリポジトリの標準的な置き場所がそう）。
    name = default_test_database_name(Path("/ドキュメント/Claude/Ride Compass"))

    assert name.replace("_", "").isalnum() and name.islower()
    assert len(name.encode("utf-8")) <= 63
