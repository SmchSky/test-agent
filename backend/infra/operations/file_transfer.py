"""
FTP 文件传输操作

通过设备 FTP 客户端从 FTP 服务器下载文件到设备。
使用 transport.send_interactive() 处理 FTP 交互式会话。
"""

import re

from loguru import logger

from infra.exceptions import DeviceError
from infra.transport.protocol import DeviceTransport


async def ftp_file_to_device(
    transport: DeviceTransport,
    filename: str,
    ftp_username: str,
    ftp_password: str,
    *,
    timeout: float = 60.0,
) -> str:
    """通过 FTP 将文件传输到设备。

    前提：服务器已开启 FTP 服务，且文件已放到 FTP 目录下

    华为 VRP FTP 交互序列示例：

        <DUT> ftp 125.65.11.94
        ...
        User(125.65.11.94:(none)): admin
        ...
        Enter password:
        ...
        [ftp] get license_xxx.xml
        ...
        [ftp] quit
        ...
        <DUT>

    Args:
        transport: 已连接的传输层对象
        filename: 要传输的文件名称
        ftp_username: FTP 用户名
        ftp_password: FTP 密码
        timeout: 交互超时时间（秒），默认 60s，传大文件时可适当增加

    Returns:
        FTP 交互过程完整回显字符串

    Raises:
        DeviceError: FTP 传输失败
    """
    # 1. 确定 FTP 服务器 IP
    ftp_server_ip = await _detect_management_ip(transport)

    # 2. 构建 FTP 交互序列
    #    提示符匹配基于华为 VRP 实际输出格式:
    #    - "User(" 匹配 "User(x.x.x.x:(none)):"
    #    - "Enter password:" 匹配密码提示
    #    - "[ftp]" 匹配 FTP 命令行提示符
    interact_events: list[tuple[str, str] | tuple[str, str, bool]] = [
        (f"ftp {ftp_server_ip}", "User(", False),
        (ftp_username, "password:", False),
        (ftp_password, "[ftp]", True),
        (f"get {filename}", "[ftp]", False),
        ("quit", "", False),  # 空字符串 = 等待设备标准提示符
    ]

    logger.info(
        "开始 FTP 传输: server={}, file={}", ftp_server_ip, filename
    )

    # 3. 执行交互
    result = await transport.send_interactive(
        interact_events=interact_events,
        timeout=timeout,
    )

    if not result.success:
        raise DeviceError(f"FTP 传输失败: {result.error}")

    logger.info(
        "FTP 传输完成: server={}, file={}, elapsed={:.1f}s",
        ftp_server_ip,
        filename,
        result.elapsed_seconds,
    )

    return result.output


async def _detect_management_ip(transport: DeviceTransport) -> str:
    """从 display users 回显中解析管理 IP（从设备视角看到的 FTP 服务器 IP）

    逻辑：查找包含 "+" 标记的行（当前 SSH 会话），提取其中的 IP 地址
    """
    users_result = await transport.execute("display users | no-more")
    if not users_result.success:
        raise DeviceError(f"获取用户列表失败: {users_result.error}")

    for line in users_result.output.splitlines():
        if "+" in line:
            ip_match = re.search(
                r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', line
            )
            if ip_match:
                return ip_match.group(1)

    raise DeviceError("无法从 display users 回显中提取 FTP 服务器 IP")
