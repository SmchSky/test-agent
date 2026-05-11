"""
设备命令执行引擎

三个执行引擎 (execute_configure, execute_query, execute_operate) 的底层执行逻辑。

设计原则：
  - 工具负责可靠执行，Agent 负责语义判断
  - 错误检测为启发式字符串匹配，仅用于触发内部流程（如事务回滚），不对外暴露
  - 确认提示自动回答 y，完整回显保留在 output 中供审计

位于 infra/operations/ 下，供 MCP Server 和 Service 层共同复用。
"""

import asyncio
import re
from app.infra.exceptions import DeviceConnectionError, DeviceError
from app.infra.transport.protocol import DeviceTransport
from loguru import logger

from .parser import parse_output
from .schemas import CommandOutput, ConfigureResult, OperateResult, QueryResult

# ---------------------------------------------------------------------------
# 命令输出正则检测
# ---------------------------------------------------------------------------

_ERROR_PATTERN: re.Pattern[str] = re.compile(r"^\s*Error:", re.MULTILINE | re.IGNORECASE)

_CONFIRM_PATTERN: re.Pattern[str] = re.compile(r"\[Y[^]*/N[^]]*]:")


def _detect_error(output: str) -> bool:
    """检测命令输出是否包含错误信息"""
    return bool(_ERROR_PATTERN.search(output))


def _detect_confirm_prompt(output: str) -> bool:
    """检测命令输出是否包含确认提示"""
    return bool(_CONFIRM_PATTERN.search(output))


# ---------------------------------------------------------------------------
# configure_device 执行逻辑
# ---------------------------------------------------------------------------


async def execute_configure(
    transport: DeviceTransport,
    device_ip: str,
    commands: list[str],
    *,
    start_from_system_view: bool = True,
    timeout: float = 60.0,
) -> ConfigureResult:
    """事务性配置下发执行引擎

    在候选配置区串行执行命令列表，任何命令出错时自动丢弃未提交的修改。

    流程：
    1. 可选：自动插入 system-view 进入系统视图
    2. 串行执行每条命令
       - 正常提示符返回 → 记录 output，检测错误
       - 检测到 [Y/N] 确认提示 → 自动回答 y
       - 错误检测触发 → 进入丢弃流程
    3. 出错丢弃流程：发送 return 回到用户视图 → 有确认提示则回答 no 丢弃修改
    """
    results: list[CommandOutput] = []
    rolled_back = False

    # 计算每条命令的超时（总超时均分，至少 5 秒）
    total_commands = len(commands) + (1 if start_from_system_view else 0)
    per_command_timeout = max(timeout / max(total_commands, 1), 5.0)

    try:
        # --- 进入系统视图 ---
        if start_from_system_view:
            logger.info("configure_device: 进入系统视图 → {}", device_ip)
            sys_result = await transport.execute("system-view", timeout=per_command_timeout)
            # system-view 的输出不计入 results（因为它是自动插入的，不属于原始输入的命令）
            if not sys_result.success:
                raise DeviceError(
                    f"进入系统视图失败: {sys_result.output}"
                )

        # --- 串行执行命令 ---
        for i, cmd in enumerate(commands, start=1):
            logger.info(
                "configure_device [{}/{}]: {!r} → {}",
                i, len(commands), cmd, device_ip,
            )

            cmd_result = await transport.execute(cmd, timeout=per_command_timeout)
            output_text = cmd_result.output.strip()

            # 检查是否需要处理确认提示
            # TODO: 当前 execute() 会等待标准提示符返回，如果设备在等 [Y/N] 输入，
            #       execute() 可能会超时。实际部署时可能需要使用 send_interactive 来
            #       预先处理可能触发确认的命令，或者在传输层增加确认提示自动检测能力。
            if _detect_confirm_prompt(output_text):
                logger.info("configure_device: 检测到确认提示，自动回答 y → {}", cmd)
                confirm_result = await transport.execute("y", timeout=per_command_timeout)
                output_text = f"{output_text}\ny\n{confirm_result.output.strip()}"

            results.append(CommandOutput(command=cmd, output=output_text))

            # 错误检测
            if _detect_error(output_text):
                logger.warning(
                    "configure_device: 命令 {!r} 检测到错误，启动丢弃流程 → {}",
                    cmd, device_ip,
                )
                rolled_back = True
                await _discard_candidate_config(transport, per_command_timeout)
                break

    except DeviceError:
        # 已知的设备异常直接冒泡
        raise
    except Exception as e:
        logger.error("configure_device: 意外异常 → {}: {}", device_ip, e)
        raise DeviceError(f"配置下发失败: {e}") from e

    return ConfigureResult(
        device_ip=device_ip,
        rolled_back=rolled_back,
        results=results,
    )


async def _discard_candidate_config(
    transport: DeviceTransport,
    timeout: float = 10.0,
) -> None:
    """丢弃未提交的候选配置

    流程：
    1. 发送 return — 从任意视图直接返回用户视图
    2. 若有回显（确认提示） → 回答 no，丢弃未提交的修改
       若无回显 → 说明没有修改过配置，无需额外操作

    若回退过程中连接中断，工具抛出异常
    （未提交的候选修改会在设备会话超时后自动丢弃）。
    """
    try:
        logger.info("丢弃候选配置: 发送 return 返回用户视图")
        return_result = await transport.execute("return", timeout=timeout)

        # 有回显说明设备在询问是否保存，回答 no 丢弃修改
        if return_result.output.strip():
            logger.info("丢弃候选配置: 检测到确认提示，回答 no")
            await transport.execute("no", timeout=timeout)

    except DeviceConnectionError:
        # 连接中断 — 候选修改会在设备会话超时后自动丢弃
        logger.warning(
            "丢弃候选配置: 连接中断，候选修改将在设备会话超时后自动丢弃"
        )
        raise
    except Exception as e:
        logger.error("丢弃候选配置失败: {}", e)
        raise DeviceError(f"丢弃候选配置失败: {e}") from e


# ---------------------------------------------------------------------------
# query_device 执行逻辑
# ---------------------------------------------------------------------------


async def execute_query(
    transport: DeviceTransport,
    device_ip: str,
    command: str,
    *,
    parse: bool = True,
    timeout: float = 30.0,
) -> QueryResult:
    """查询命令执行引擎

    在用户视图下执行一条只读查询命令。
    当 parse=True 时，尝试用 TextFSM 模板进行结构化解析。
    """
    logger.info("query_device: {!r} → {}", command, device_ip)

    cmd_result = await transport.execute(command, timeout=timeout)
    raw_output = cmd_result.output

    # TextFSM 结构化解析
    if parse:
        result = parse_output(command, raw_output)
        if result is not None:
            return QueryResult(
                device_ip=device_ip,
                command=command,
                output=result,
            )

    # 否则返回原始文本
    return QueryResult(
        device_ip=device_ip,
        command=command,
        output=raw_output,
    )


# ---------------------------------------------------------------------------
# operate_device 执行逻辑
# ---------------------------------------------------------------------------


async def execute_operate(
    transport: DeviceTransport,
    device_ip: str,
    command: str,
    *,
    timeout: float = 60.0,
) -> OperateResult:
    """操作性命令执行引擎

    在用户视图下执行一条操作性命令。
    自动处理 [Y/N] 确认提示，对断连保持韧性。

    断连韧性：命令发送后如果在等待回显过程中连接中断，
    工具捕获该异常，将已收到的部分回显放入 output，正常返回而非抛出异常。
    """
    logger.info("operate_device: {!r} → {}", command, device_ip)

    try:
        cmd_result = await transport.execute(command, timeout=timeout)
        output_text = cmd_result.output.strip()

        # 处理确认提示
        # TODO: 同 configure_device，execute() 在设备等待 [Y/N] 输入时可能超时。
        #       实际部署时可能需要针对已知会触发确认的命令（reboot, save, reset 等）
        #       使用 send_interactive 预处理。
        if _detect_confirm_prompt(output_text):
            logger.info("operate_device: 检测到确认提示，自动回答 y → {}", command)
            try:
                confirm_result = await transport.execute("y", timeout=timeout)
                output_text = f"{output_text}\ny\n{confirm_result.output.strip()}"
            except (DeviceConnectionError, asyncio.TimeoutError):
                # 确认后断连是预期行为（如 reboot）
                output_text = f"{output_text}\ny"
                logger.info(
                    "operate_device: 确认后断连（预期行为） → {}", command,
                )

        return OperateResult(
            device_ip=device_ip,
            command=command,
            output=output_text,
        )

    except DeviceConnectionError:
        # 断连韧性：命令发送后连接中断，返回已收到的部分回显
        logger.info(
            "operate_device: 执行后断连，返回部分回显 → {} {!r}",
            device_ip, command,
        )
        return OperateResult(
            device_ip=device_ip,
            command=command,
            output="(设备连接在命令执行后中断)",
        )
    except asyncio.TimeoutError:
        # 超时也可能是因为命令执行时间较长（如 ping -c 100），正常返回
        logger.warning(
            "operate_device: 命令超时 → {} {!r} (timeout={}s)",
            device_ip, command, timeout,
        )
        raise DeviceError(
            f"命令超时: {command!r} (timeout={timeout}s)"
        )
