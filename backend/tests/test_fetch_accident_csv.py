"""警察庁の本票CSVの取得（scripts/fetch_accident_csv.py）。

入口は`fetch`。実ダウンロード（60MB規模）はテストで行わず、配布元の応答と置き場だけを差し替えて、
「既にあるものは触らない」「読めないものを取得済みとして残さない」を確かめる。取得の道具が共有する手順
（`app/batch/common.py: fetch_verified`）の判断は、ここで見る（ほかの取得の道具のテストは寄せていることだけを見る）。
配布元へ応答を与えていない要求は`respx_mock`が落とすので、取りに行かないことは応答を与えないことで見る。

ここで見ないもの:
- 本票の列の読み方 → `test_npa_honhyo.py`
"""

import pytest

from app.batch.source_adapters import npa_honhyo
from app.batch.source_adapters.npa_honhyo import ENCODING
from scripts import fetch_accident_csv


def _honhyo_bytes() -> bytes:
    """本票として読める最小のCSV（見出し＋1行）。"""
    return "資料区分,都道府県コード,本票番号\n1,25,0001\n".encode(ENCODING)


URL_2024 = fetch_accident_csv.HONHYO_URL_TEMPLATE.format(year=2024)


@pytest.fixture
def distributor(monkeypatch, tmp_path, respx_mock):
    """配布元の代役（respx）と、置き場を`tmp_path`へ。応答はテストごとに経路を足して決める。"""
    monkeypatch.setattr(npa_honhyo, "DATA_DIR", tmp_path)
    return respx_mock


def test_downloads_missing_year(tmp_path, distributor):
    distributor.get(URL_2024).respond(content=_honhyo_bytes())

    assert fetch_accident_csv.fetch([2024]) == 0

    assert (tmp_path / "honhyo_2024.csv").read_bytes() == _honhyo_bytes()


def test_keeps_existing_csv_untouched(tmp_path, distributor):
    destination = tmp_path / "honhyo_2024.csv"
    destination.write_bytes(_honhyo_bytes())

    assert fetch_accident_csv.fetch([2024]) == 0

    assert destination.read_bytes() == _honhyo_bytes()


def test_refetches_a_file_that_is_not_readable(tmp_path, distributor):
    """見出しだけ・空といった半端なものは「取得済み」と見なさない。"""
    destination = tmp_path / "honhyo_2024.csv"
    destination.write_bytes("資料区分,都道府県コード\n".encode(ENCODING))
    distributor.get(URL_2024).respond(content=_honhyo_bytes())

    assert fetch_accident_csv.fetch([2024]) == 0

    assert destination.read_bytes() == _honhyo_bytes()


def test_does_not_leave_an_unreadable_file_behind(tmp_path, distributor):
    """CSVとして読めない応答（配布元のエラーページ等）を「取得済み」にしない。

    残すと次の実行が再取得せず、取込がその中身で落ちる。
    """
    distributor.get(URL_2024).respond(content=b"<html><body>404 Not Found</body></html>")

    assert fetch_accident_csv.fetch([2024]) == 1

    assert not (tmp_path / "honhyo_2024.csv").exists()
    assert (tmp_path / "honhyo_2024.csv.broken").exists()
    assert not list(tmp_path.glob("*.part"))
