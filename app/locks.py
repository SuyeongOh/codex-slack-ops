from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional
from uuid import uuid4

from redis.asyncio import Redis


LOCK_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
end
return 0
"""


@dataclass
class RedisLock:
    redis: Redis
    key: str
    token: str
    acquired: bool

    async def release(self) -> None:
        if not self.acquired:
            return
        await self.redis.eval(LOCK_RELEASE_SCRIPT, 1, self.key, self.token)
        self.acquired = False


class RedisLockManager:
    def __init__(self, redis: Redis, default_ttl: int) -> None:
        self.redis = redis
        self.default_ttl = default_ttl

    async def acquire(self, key: str, ttl: Optional[int] = None) -> RedisLock:
        token = uuid4().hex
        acquired = bool(
            await self.redis.set(
                name=key,
                value=token,
                nx=True,
                ex=ttl or self.default_ttl,
            )
        )
        return RedisLock(redis=self.redis, key=key, token=token, acquired=acquired)


@dataclass
class MemoryLock:
    manager: "MemoryLockManager"
    key: str
    acquired: bool

    async def release(self) -> None:
        if not self.acquired:
            return
        await self.manager.release(self.key)
        self.acquired = False


class MemoryLockManager:
    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def acquire(self, key: str, ttl: Optional[int] = None) -> MemoryLock:
        del ttl
        async with self._guard:
            lock = self._locks.setdefault(key, asyncio.Lock())
            if lock.locked():
                return MemoryLock(manager=self, key=key, acquired=False)
            await lock.acquire()
            return MemoryLock(manager=self, key=key, acquired=True)

    async def release(self, key: str) -> None:
        async with self._guard:
            lock = self._locks.get(key)
            if lock and lock.locked():
                lock.release()
