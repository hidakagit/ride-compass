"""本番の調査の道具（`scripts/run_probe.py`）が手元実行のプローブへ渡す接続情報で、本物のDBへ繋がるか。

差し替えるのは接続情報の置き場（ディスクの`.env.oracle.local`）と、チェックアウトの遅れの確かめ（網と
このチェックアウトの履歴を読む。`test_checkout_freshness.py`が見る）だけで、接続先はテストDB、
プローブは別プロセスのPythonとして本当に走らせる。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import _prod_env  # noqa: E402
import run_probe  # noqa: E402
from tests.conftest import postgis_database_url  # noqa: E402

pytestmark = [pytest.mark.postgis, pytest.mark.xdist_group(name="postgis")]


@pytest.fixture(autouse=True)
def _checkout_is_current(monkeypatch):
    monkeypatch.setattr(_prod_env, "require_current_checkout", lambda: None)

_PROBE = """
import asyncio
import os

import asyncpg


async def main():
    connection = await asyncpg.connect(os.environ["PROBE_ASYNCPG_DSN"])
    try:
        print(await connection.fetchval("SELECT 1"))
    finally:
        await connection.close()


asyncio.run(main())
"""


def test_a_probe_connects_with_plain_asyncpg_when_the_url_carries_the_sqlalchemy_ssl_query(
    tmp_path, monkeypatch, capfd
):
    env_file = tmp_path / ".env.oracle.local"
    # 本番の接続文字列と同じく`ssl=`をクエリに持つ形。`prefer`はSSLの無いテストDBへも繋がる。
    env_file.write_text(f"DATABASE_URL={postgis_database_url()}?ssl=prefer\n", encoding="utf-8")
    monkeypatch.setattr(_prod_env, "prod_env_file", lambda: env_file)
    probe = tmp_path / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")

    assert run_probe.main([str(probe)]) == 0
    assert capfd.readouterr().out.strip() == "1"


def test_arguments_after_the_probe_reach_the_probe(tmp_path, monkeypatch, capfd):
    env_file = tmp_path / ".env.oracle.local"
    env_file.write_text(f"DATABASE_URL={postgis_database_url()}\n", encoding="utf-8")
    monkeypatch.setattr(_prod_env, "prod_env_file", lambda: env_file)
    probe = tmp_path / "probe.py"
    probe.write_text("import sys\nprint(sys.argv[1:])\n", encoding="utf-8")

    assert run_probe.main([str(probe), "--column", "edge_materials.accident_count"]) == 0
    assert capfd.readouterr().out.strip() == "['--column', 'edge_materials.accident_count']"
