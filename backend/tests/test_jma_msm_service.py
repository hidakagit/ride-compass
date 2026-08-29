"""jma_msm_service.py（改善計画T387、スケルトン）のテスト。"""

import pytest

from app.domain.jma_msm import MsmMeshRecord
from app.services import jma_msm_service


class FakeRedis:
    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}

    def pipeline(self, transaction=False):
        return FakePipeline(self)

    async def hgetall(self, key):
        return self.hashes.get(key, {})


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops = []

    def hset(self, key, mapping):
        self._ops.append(("hset", key, mapping))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))
        return self

    async def execute(self):
        for op in self._ops:
            if op[0] == "hset":
                _, key, mapping = op
                self._redis.hashes.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jma_msm_service, "get_redis_client", lambda: fake)
    return fake


async def test_save_batch_then_get_mesh_roundtrip():
    record = MsmMeshRecord(mesh_id="5339-24", u_wind=1.2, v_wind=-0.5, temp=22.3, precip_1h=0.0, valid_time="2026-08-29T12:00:00+09:00")
    await jma_msm_service.save_batch([record])

    result = await jma_msm_service.get_mesh("5339-24")

    assert result == record


async def test_get_mesh_returns_none_when_absent():
    assert await jma_msm_service.get_mesh("unknown") is None


def test_parse_grib2_stub_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        jma_msm_service.parse_grib2_stub(b"")
