"""
设备通信错误分类体系（基础设施层异常）

继承层次:
  DeviceError
  ├── DeviceConnectionError
  ├── AuthenticationError
  ├── CommandTimeoutError
  ├── DeviceUnreachableError
  └── CommandExecutionError
"""


class DeviceError(Exception):
    """设备通信根异常"""


class DeviceConnectionError(DeviceError):
    """TCP/SSH 连接建立失败"""


class AuthenticationError(DeviceError):
    """认证失败，凭据不正确"""


class CommandTimeoutError(DeviceError):
    """命令执行超时"""


class DeviceUnreachableError(DeviceError):
    """设备不可达，通常在重启期间"""


class CommandExecutionError(DeviceError):
    """命令本身执行失败"""
