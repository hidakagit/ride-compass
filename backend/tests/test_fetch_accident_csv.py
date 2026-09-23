"""警察庁の本票CSVの取得（scripts/fetch_accident_csv.py）。

実ダウンロード（60MB規模）はテストで行わず、配布元の応答だけを差し替えて、
「既にあるものは触らない」「読めないものを取得済みとして残さない」を確かめる。
"""

import pytest

from app.batch.source_adapters import npa_honhyo
from app.batch.source_adapters.npa_honhyo import ENCODING
from scripts import fetch_accident_csv
from tests.bound_fake import bound


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        pass

    def iter_bytes(self):
        yield self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _honhyo_bytes() -> bytes:
    """本票として読める最小のCSV（見出し＋1行）。"""
    return "資料区分,都道府県コード,本票番号\n1,25,0001\n".encode(ENCODING)


@pytest.fixture
def stub_download(monkeypatch, tmp_path):
    """配布元の応答と置き場を差し替える。返した本文がそのまま保存対象になる。"""

    calls: list[str] = []
    payload = {"body": b""}

    def fake_stream(_method, url, **_kwargs):
        calls.append(url)
        return _FakeResponse(payload["body"])

    monkeypatch.setattr(fetch_accident_csv.httpx, "stream", bound(fetch_accident_csv.httpx.stream, fake_stream))
    monkeypatch.setattr(npa_honhyo, "DATA_DIR", tmp_path)
    return calls, payload


def test_downloads_missing_year(tmp_path, stub_download):
    calls, payload = stub_download
    payload["body"] = _honhyo_bytes()

    assert fetch_accident_csv.fetch([2024]) == 0

    assert (tmp_path / "honhyo_2024.csv").exists()
    assert calls == [fetch_accident_csv.HONHYO_URL_TEMPLATE.format(year=2024)]


def test_keeps_existing_csv_untouched(tmp_path, stub_download):
    calls, _payload = stub_download
    destination = tmp_path / "honhyo_2024.csv"
    destination.write_bytes(_honhyo_bytes())

    assert fetch_accident_csv.fetch([2024]) == 0

    assert destination.read_bytes() == _honhyo_bytes()
    assert calls == []


def test_refetches_a_file_that_is_not_readable(tmp_path, stub_download):
    """見出しだけ・空といった半端なものは「取得済み」と見なさない。"""
    _calls, payload = stub_download
    destination = tmp_path / "honhyo_2024.csv"
    destination.write_bytes("資料区分,都道府県コード\n".encode(ENCODING))
    payload["body"] = _honhyo_bytes()

    assert fetch_accident_csv.fetch([2024]) == 0

    assert destination.read_bytes() == _honhyo_bytes()


def test_does_not_leave_an_unreadable_file_behind(tmp_path, stub_download):
    """CSVとして読めない応答（配布元のエラーページ等）を「取得済み」にしない。

    残すと次の実行が再取得せず、取込がその中身で落ちる。
    """
    _calls, payload = stub_download
    payload["body"] = b"<html><body>404 Not Found</body></html>"

    assert fetch_accident_csv.fetch([2024]) == 1

    assert not (tmp_path / "honhyo_2024.csv").exists()
    assert (tmp_path / "honhyo_2024.csv.broken").exists()
    assert not list(tmp_path.glob("*.part"))
