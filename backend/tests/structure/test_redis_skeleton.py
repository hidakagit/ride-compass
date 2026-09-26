"""Redisキャッシュの骨格が、各所へ写経されていないことの検査。

cache-asideの骨格（可用性チェック→クライアント取得→計測→fail-open→成否記録）は
`infrastructure/redis_json_cache.py`の`get_json`/`set_json`が内包している。自前で書き直すと、
写経ミス（`record_redis_failure`の呼び忘れ等）でRedis障害の検知だけが静かに欠ける
——アプリはfail-openのまま動き続けるため表に出ない。

母集団はソースから導く（`backend/app`配下の全`.py`）。骨格を自前で持ってよいファイルは
下に列挙し、**列挙が古くなったらこのテスト自身が落ちる**ようにしてある
（載っているのに使っていない＝寄せ終わったのに列挙が残っている、も違反）。
"""

from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent.parent / "app"

SKELETON_SYMBOLS = (
    "get_redis_client_or_none",
    "record_redis_failure",
    "record_redis_success",
    "redis_available",
)

# 骨格を自前で持ってよいファイルと、その理由。
ALLOWED = {
    "infrastructure/redis_client.py": "骨格が使う接続・サーキットブレーカー本体",
    "infrastructure/redis_json_cache.py": "骨格そのもの",
    "services/jma_amedas_service.py": "全観測所をpipelineでHashへ一括読み書きする（単一キーのJSON読み書きでは表現できない）",
}


def files_using_skeleton(root: Path) -> set[str]:
    out = set()
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if any(symbol in text for symbol in SKELETON_SYMBOLS):
            out.add(path.relative_to(root).as_posix())
    return out


def test_redis_skeleton_is_not_copied() -> None:
    users = files_using_skeleton(APP_ROOT)

    unexpected = sorted(users - ALLOWED.keys())
    assert unexpected == [], (
        "Redisキャッシュの骨格を自前で書いているファイルがある"
        "（`redis_json_cache.py`の`get_json`/`set_json`を使うこと。寄せられない事情があるなら"
        "このテストのALLOWEDへ理由とともに足す）:\n  " + "\n  ".join(unexpected)
    )


def test_allowlist_has_no_stale_entries() -> None:
    """寄せ終わったファイルが列挙に残り続けないこと。"""
    users = files_using_skeleton(APP_ROOT)

    stale = sorted(ALLOWED.keys() - users)
    assert stale == [], "骨格を使っていないのにALLOWEDへ残っている:\n  " + "\n  ".join(stale)


def test_detects_a_copied_skeleton(tmp_path: Path) -> None:
    """検査が効いていること（わざと1件置いて捕まえる）。"""
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "sample.py").write_text(
        "from app.infrastructure.redis_client import get_redis_client_or_none\n",
        encoding="utf-8",
    )

    assert files_using_skeleton(tmp_path) - ALLOWED.keys() == {"services/sample.py"}
