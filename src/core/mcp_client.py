"""MCP 客户端管理器 - QTranslator

集成开源的官方 MCP Python SDK（github.com/modelcontextprotocol/python-sdk，
包名 mcp），为 AI 对话提供 MCP 工具调用能力。

服务器配置位于 AppData/Local/QTranslator/mcp_servers.json，
兼容 Claude Desktop 格式：

    {
      "mcpServers": {
        "filesystem": {
          "command": "cmd",
          "args": ["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", "C:\\\\Users"],
          "env": {}
        }
      }
    }

注意：Windows 下运行 npx / npm / uvx 等 .cmd 程序时，
请用 "cmd" + "/c" 包裹（本模块也会自动做这层兼容）。
"""
import asyncio
import json
import sys
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ..config import get_config
    from ..utils.logger import log_info, log_error, log_debug
except ImportError:
    from src.config import get_config
    from src.utils.logger import log_info, log_error, log_debug

# 官方 MCP SDK（未安装时优雅降级，仅 MCP 能力不可用）
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

_DEFAULT_CONFIG = {"mcpServers": {}}

# Windows 下需要 cmd /c 包裹才能启动的 .cmd 包装命令
_WIN_CMD_TOOLS = {"npx", "npm", "uvx", "pipx"}


@dataclass
class MCPToolInfo:
    """一个 MCP 工具的描述"""
    server: str
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)

    def to_openai_tool(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 的 tools 项"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"[{self.server}] {self.description}"[:1024],
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }


@dataclass
class MCPServerStatus:
    """一个 MCP 服务器的连接状态"""
    name: str
    connected: bool
    tool_count: int = 0
    error: str = ""


class _ServerConnection:
    """单个 MCP 服务器的连接（运行在后台 asyncio 循环中）"""

    def __init__(self, name: str, params: "StdioServerParameters"):
        self.name = name
        self.params = params
        self.session: Optional["ClientSession"] = None
        self._stack: Optional[AsyncExitStack] = None
        self.tools: List[MCPToolInfo] = []
        self.error: str = ""

    async def connect(self):
        self._stack = AsyncExitStack()
        try:
            read, write = await self._stack.enter_async_context(stdio_client(self.params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(session.initialize(), timeout=30)
            self.session = session

            result = await asyncio.wait_for(session.list_tools(), timeout=30)
            self.tools = [
                MCPToolInfo(
                    server=self.name,
                    name=t.name,
                    description=(t.description or "").strip(),
                    input_schema=getattr(t, 'inputSchema', None) or {},
                )
                for t in (result.tools or [])
            ]
            log_info(f"MCP 服务器已连接: {self.name}（{len(self.tools)} 个工具）")
        except Exception as e:
            self.error = str(e)
            log_error(f"MCP 服务器连接失败 {self.name}: {e}")
            await self.close()
            raise

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        if not self.session:
            raise RuntimeError(f"MCP 服务器 {self.name} 未连接")
        result = await asyncio.wait_for(
            self.session.call_tool(tool_name, arguments or {}), timeout=120
        )
        # 提取文本内容
        parts = []
        for item in (getattr(result, 'content', None) or []):
            text = getattr(item, 'text', None)
            if text:
                parts.append(text)
        if not parts and getattr(result, 'isError', False):
            return "[MCP 工具执行出错]"
        return "\n".join(parts) if parts else "(无文本输出)"

    async def close(self):
        stack, self._stack = self._stack, None
        self.session = None
        if stack:
            try:
                await stack.aclose()
            except Exception:
                pass


class MCPClientManager:
    """MCP 客户端管理器（后台 asyncio 线程 + 同步调用接口）"""

    def __init__(self):
        self._config_path: Path = get_config().app_dir / "mcp_servers.json"
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._connections: Dict[str, _ServerConnection] = {}
        self._lock = threading.RLock()
        self._started = False
        self._ensure_config_file()

    # ------------------------------------------------------------------
    # 配置文件
    # ------------------------------------------------------------------
    def _ensure_config_file(self):
        try:
            if not self._config_path.exists():
                self._config_path.write_text(
                    json.dumps(_DEFAULT_CONFIG, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
        except Exception as e:
            log_error(f"创建 mcp_servers.json 失败: {e}")

    @property
    def config_path(self) -> Path:
        return self._config_path

    def _load_server_configs(self) -> Dict[str, Dict[str, Any]]:
        try:
            data = json.loads(self._config_path.read_text(encoding='utf-8'))
            servers = data.get('mcpServers', {})
            return servers if isinstance(servers, dict) else {}
        except Exception as e:
            log_error(f"读取 mcp_servers.json 失败: {e}")
            return {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return _MCP_AVAILABLE

    def start(self):
        """启动后台 asyncio 线程并连接所有已配置的 MCP 服务器"""
        if not _MCP_AVAILABLE:
            log_error("未安装 mcp 包，MCP 能力不可用（pip install mcp）")
            return
        with self._lock:
            if self._started:
                return
            self._started = True

        ready = threading.Event()

        def _run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready.set()
            try:
                self._loop.run_forever()
            finally:
                try:
                    self._loop.run_until_complete(self._close_all())
                except Exception:
                    pass
                self._loop.close()

        self._thread = threading.Thread(target=_run_loop, name="MCPClientLoop", daemon=True)
        self._thread.start()
        ready.wait(5)

        # 连接所有服务器（在后台循环中执行，不阻塞 UI 线程）
        self._submit(self._connect_all(), timeout=None)
        log_info("MCP 客户端管理器已启动")

    def _submit(self, coro, timeout: Optional[float] = 60.0):
        """把协程提交到后台循环执行；timeout=None 时只提交不等待结果"""
        if not self._loop:
            raise RuntimeError("MCP 后台循环未启动")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        if timeout is None:
            return None
        return future.result(timeout=timeout)

    async def _connect_all(self):
        configs = self._load_server_configs()
        if not configs:
            log_debug("mcp_servers.json 中没有配置任何 MCP 服务器")
            return
        tasks = [self._connect_one(name, cfg) for name, cfg in configs.items()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _connect_one(self, name: str, cfg: Dict[str, Any]):
        try:
            command = str(cfg.get('command', '')).strip()
            args = [str(a) for a in (cfg.get('args') or [])]
            env = cfg.get('env') or None
            if not command:
                return
            # Windows 兼容：npx/npm/uvx 是 .cmd，需要 cmd /c 包裹
            if sys.platform == 'win32' and command.lower() in _WIN_CMD_TOOLS:
                args = ["/c", command] + args
                command = "cmd"
            params = StdioServerParameters(command=command, args=args, env=env)
            conn = _ServerConnection(name, params)
            await conn.connect()
            with self._lock:
                old = self._connections.get(name)
                if old:
                    await old.close()
                self._connections[name] = conn
        except Exception as e:
            log_error(f"MCP 服务器 {name} 启动失败: {e}")
            with self._lock:
                failed = _ServerConnection(name, StdioServerParameters(command="", args=[]))
                failed.error = str(e)
                self._connections[name] = failed

    def reconnect(self):
        """重新读取配置并连接（供设置界面/聊天窗口刷新用）"""
        if not self._started:
            self.start()
            return
        self._submit(self._reconnect_async(), timeout=None)

    async def _reconnect_async(self):
        await self._close_all()
        await self._connect_all()

    async def _close_all(self):
        with self._lock:
            conns = list(self._connections.values())
            self._connections.clear()
        for conn in conns:
            await conn.close()

    def shutdown(self):
        """应用退出时调用"""
        if not self._started or not self._loop:
            return
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._started = False
        log_info("MCP 客户端管理器已关闭")

    # ------------------------------------------------------------------
    # 对外同步接口（供聊天窗口使用）
    # ------------------------------------------------------------------
    def list_tools(self) -> List[MCPToolInfo]:
        """所有已连接服务器的工具列表"""
        with self._lock:
            tools: List[MCPToolInfo] = []
            for conn in self._connections.values():
                tools.extend(conn.tools)
            return tools

    def server_statuses(self) -> List[MCPServerStatus]:
        with self._lock:
            statuses = []
            for name, conn in self._connections.items():
                statuses.append(MCPServerStatus(
                    name=name,
                    connected=conn.session is not None,
                    tool_count=len(conn.tools),
                    error=conn.error,
                ))
            return statuses

    def call_tool(self, server: str, tool_name: str, arguments: Dict[str, Any]) -> str:
        """同步调用 MCP 工具（阻塞，需在后台线程中使用）"""
        with self._lock:
            conn = self._connections.get(server)
        if not conn or not conn.session:
            raise RuntimeError(f"MCP 服务器 {server} 未连接")
        return self._submit(conn.call_tool(tool_name, arguments), timeout=130)


# 全局实例
_manager_instance: Optional[MCPClientManager] = None


def get_mcp_manager() -> MCPClientManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = MCPClientManager()
    return _manager_instance
