"""
TransportPool — 带 TTL 自动回收的设备连接池

按 device_ip 缓存已连接的 transport 实例。
后台 reaper 任务定期关闭空闲超时的连接。
服务器关闭时 shutdown() 清理所有连接。
"""

import asyncio
import time
from app.infra.transport.factory import create_transport
from app.infra.transport.protocol import DeviceTransport
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class PoolEntry:
    """连接池条目"""

    transport: DeviceTransport
    last_used: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.last_used = time.monotonic()

    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used


class TransportPool:
    """带 TTL 自动回收的设备连接池

    按 device_ip 缓存已连接的 transport 实例。
    后台 reaper 任务定期关闭空闲超时的连接。
    服务器关闭时 shutdown() 清理所有连接。

    Pool key = device_ip 的设计思想：
        Agent 的运行环境只会为其提供一套设备的登录凭据（用户名、密码），Agent 会在整个流程中复用该凭据，故不会出现同一 Agent 在同一流程中用不同凭据访问同一设备的情况。
        如果后续业务需求打破了这一前提，此时应将 pool key 改为 (device_ip, username) 的组合。
    """

    def __init__(self, idle_ttl: float = 300.0, reap_interval: float = 60.0):
        self._pool: dict[str, PoolEntry] = {}  # key = device_ip
        self._idle_ttl = idle_ttl  # 空闲多久算过期（秒）
        self._reap_interval = reap_interval  # 多久检查一次过期（秒）
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None

    async def acquire(
        self,
        device_ip: str,
        *,
        username: str | None = None,
        password: str | None = None,
        port: int | None = None,
    ) -> DeviceTransport:
        """获取到指定设备的 transport（复用或新建）

        - 池中有存活连接 → 复用，更新 last_used
        - 池中有死连接 → 关闭后重建
        - 池中无连接 → 新建
        - connect() 失败 → 异常冒泡，不缓存
        """
        async with self._lock:
            entry = self._pool.get(device_ip)

            if entry and await entry.transport.is_alive():
                entry.touch()
                logger.debug("连接池复用: {}", device_ip)
                return entry.transport

            if entry:
                logger.info("连接池清理死连接: {}", device_ip)
                await entry.transport.close()
                del self._pool[device_ip]

            transport = create_transport(
                host=device_ip, username=username, password=password, port=port,
            )
            await transport.connect()
            self._pool[device_ip] = PoolEntry(transport)
            logger.info("连接池新建: {} (池大小: {})", device_ip, len(self._pool))
            return transport

    async def _reap_idle(self) -> None:
        """后台任务：定期关闭空闲超时的连接"""
        while True:
            await asyncio.sleep(self._reap_interval)
            async with self._lock:
                expired = [
                    ip for ip, entry in self._pool.items()
                    if entry.idle_seconds() > self._idle_ttl
                ]
                for ip in expired:
                    entry = self._pool.pop(ip)
                    await entry.transport.close()
                    logger.info("连接池回收空闲连接: {} (已空闲 {:.0f}s)", ip, entry.idle_seconds())

    async def startup(self) -> None:
        """启动后台 reaper 任务"""
        self._reaper_task = asyncio.create_task(self._reap_idle())
        logger.info("TransportPool 已启动 (TTL={}s, reap_interval={}s)", self._idle_ttl, self._reap_interval)

    async def shutdown(self) -> None:
        """关闭所有连接 + 停止 reaper"""
        if self._reaper_task:
            self._reaper_task.cancel()
            self._reaper_task = None
        async with self._lock:
            for ip, entry in self._pool.items():
                await entry.transport.close()
                logger.info("TransportPool shutdown: 关闭 {}", ip)
            self._pool.clear()
        logger.info("TransportPool 已关闭")
