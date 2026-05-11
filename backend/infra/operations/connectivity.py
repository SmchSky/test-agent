from dataclasses import dataclass

from infra.transport.protocol import DeviceTransport
from .parser import parse_output


@dataclass
class DeviceBasicInfo:
    """设备基本信息（连通性检查时顺带采集）"""

    product_name: str
    software_version: str
    patch_version: str
    uptime: str


async def check_device_connectivity(
    transport: DeviceTransport,
    timeout: float = 10.0,
) -> DeviceBasicInfo:
    """检查设备连通性，返回设备基本信息。

    执行 display version 验证设备可响应命令，同时采集设备基本信息。

    成功: 返回 DeviceBasicInfo
    失败: 抛出 CommandTimeoutError 或 CommandExecutionError
    """
    cmd_result = await transport.execute("display version", timeout=timeout)
    result = parse_output("display version", cmd_result.output)

    if result is not None:
        row, *_ = result  # 只关心第一条记录
        return DeviceBasicInfo(
            product_name=row.get("product_name", "Unknown"),
            software_version=row.get("software_version", "Unknown"),
            patch_version=row.get("patch_version", "Unknown"),
            uptime=row.get("uptime", "Unknown"),
        )

    return DeviceBasicInfo(
        product_name="Unknown",
        software_version="Unknown",
        patch_version="Unknown",
        uptime="Unknown",
    )
