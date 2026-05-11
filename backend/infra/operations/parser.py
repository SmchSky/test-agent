"""
TextFSM 命令输出解析器
"""

from pathlib import Path
from typing import Any

import textfsm
from loguru import logger

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_COMMAND_TEMPLATE_MAP: dict[str, str] = {
    "display version": "display_version.textfsm",
    "display ip interface brief": "display_ip_interface_brief.textfsm",
    "display interface brief": "display_interface_brief.textfsm",
    "display cpu-usage": "display_cpu_usage.textfsm",
    "display memory-usage": "display_memory_usage.textfsm",
    "display ip routing-table": "display_ip_routing_table.textfsm",
}


def get_supported_commands() -> list[str]:
    """返回所有支持结构化解析的命令列表"""
    return list(_COMMAND_TEMPLATE_MAP.keys())


def parse_output(command: str, raw_output: str) -> list[dict[str, Any]] | None:
    """解析命令输出

    根据命令名匹配 TextFSM 模板进行结构化解析。

    Args:
        command: 执行的命令（用于匹配模板，大小写无关）
        raw_output: 原始回显文本

    Returns:
        解析成功返回 list[dict]，失败/无模板/空结果返回 None
    """

    # 根据命令匹配模板文件
    template_name = _COMMAND_TEMPLATE_MAP.get(command.strip().lower())
    if template_name is None:
        return None

    template_path = _TEMPLATES_DIR / template_name
    if not template_path.exists():
        logger.warning("模板文件不存在: {}", template_path)
        return None

    try:
        assert textfsm is not None

        with template_path.open(encoding="utf-8") as f:
            fsm = textfsm.TextFSM(f)

        clean_output = raw_output.replace("\r\n", "\n").replace("\r", "\n")
        result = fsm.ParseText(clean_output)

        headers = [h.lower() for h in fsm.header]
        parsed_data = [dict(zip(headers, row)) for row in result]

        if not parsed_data:
            logger.debug("TextFSM 解析结果为空: command={}", command)
            return None

        logger.debug(
            "TextFSM 解析成功: command={}, records={}",
            command,
            len(parsed_data),
        )
        return parsed_data

    except Exception as e:
        logger.warning("TextFSM 解析失败: command={}, error={}", command, e)
        return None
