"""MCP 连接管理：负责多 Server 生命周期与工具调用。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class MCPServerConfig:
    """单个 MCP Server 配置。"""

    name: str
    transport: str = "stdio"
    command: str = ""
    args: List[str] | None = None
    url: str = ""
    headers: Dict[str, str] | None = None
    env: Dict[str, str] | None = None
    enabled: bool = True


class MCPManager:
    """统一管理 MCP Server 连接，并提供前缀命名路由。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self.config_path = (
            Path(config_path)
            if config_path
            else (project_root / "workspace" / "mcp" / "servers.json")
        )
        self._server_configs = self._load_config()
        self._clients: Dict[str, Any] = {}
        self._tool_index: Dict[str, Tuple[str, str]] = {}
        self._tool_schemas: Dict[str, Dict[str, Any]] = {}
        self._tool_meta: Dict[str, Dict[str, str]] = {}
        self._started = False

    def _load_config(self) -> List[MCPServerConfig]:
        if not self.config_path.exists():
            return []
        try:
            raw = self.config_path.read_text(encoding="utf-8").strip()
            if not raw:
                return []
            payload = json.loads(raw)
            rows = payload.get("servers", []) if isinstance(payload, dict) else []
            configs: List[MCPServerConfig] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                configs.append(
                    MCPServerConfig(
                        name=name,
                        transport=str(row.get("transport", "stdio")).strip().lower(),
                        command=str(row.get("command", "")).strip(),
                        args=row.get("args") or [],
                        url=str(row.get("url", "")).strip(),
                        headers=row.get("headers") or {},
                        env=row.get("env") or {},
                        enabled=bool(row.get("enabled", True)),
                    )
                )
            return configs
        except (OSError, json.JSONDecodeError):
            return []

    async def _connect_stdio(self, server: MCPServerConfig) -> Any:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=server.command,
            args=server.args or [],
            env=server.env or None,
        )
        stdio = await stdio_client(params).__aenter__()
        reader, writer = stdio
        session = ClientSession(reader, writer)
        await session.__aenter__()
        await session.initialize()
        return {"session": session}

    async def _connect_sse(self, server: MCPServerConfig) -> Any:
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        sse = await sse_client(url=server.url, headers=server.headers or None).__aenter__()
        reader, writer = sse
        session = ClientSession(reader, writer)
        await session.__aenter__()
        await session.initialize()
        return {"session": session}

    async def _list_tools(self, session: Any) -> List[Any]:
        resp = await session.list_tools()
        if hasattr(resp, "tools"):
            return list(resp.tools or [])
        if isinstance(resp, dict):
            return list(resp.get("tools", []) or [])
        return []

    async def _start_server(self, server: MCPServerConfig) -> None:
        if not server.enabled:
            return
        if server.transport == "stdio":
            if not server.command:
                return
            client = await self._connect_stdio(server)
        elif server.transport == "sse":
            if not server.url:
                return
            client = await self._connect_sse(server)
        else:
            return

        self._clients[server.name] = client
        tools = await self._list_tools(client["session"])
        for item in tools:
            raw_name = str(getattr(item, "name", "") or "").strip()
            if not raw_name and isinstance(item, dict):
                raw_name = str(item.get("name", "")).strip()
            if not raw_name:
                continue
            namespaced = f"mcp_{server.name}_{raw_name}"
            input_schema = getattr(item, "inputSchema", None)
            if input_schema is None and isinstance(item, dict):
                input_schema = item.get("inputSchema")
            description = str(getattr(item, "description", "") or "").strip()
            if not description and isinstance(item, dict):
                description = str(item.get("description", "")).strip()
            self._tool_index[namespaced] = (server.name, raw_name)
            self._tool_schemas[namespaced] = input_schema or {"type": "object", "properties": {}}
            self._tool_meta[namespaced] = {"description": description}

    def start_all(self) -> None:
        """启动全部启用的 MCP Server 并缓存工具清单。"""
        if self._started:
            return
        try:
            import mcp  # noqa: F401
        except ImportError:
            self._started = True
            return
        for server in self._server_configs:
            try:
                asyncio.run(self._start_server(server))
            except Exception:
                continue
        self._started = True

    async def _stop_server(self, client: Any) -> None:
        session = client.get("session")
        if session is not None:
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass

    def stop_all(self) -> None:
        """优雅关闭所有 MCP 连接。"""
        for client in self._clients.values():
            try:
                asyncio.run(self._stop_server(client))
            except Exception:
                continue
        self._clients.clear()
        self._tool_index.clear()
        self._tool_schemas.clear()
        self._tool_meta.clear()
        self._started = False

    def list_prefixed_tools(self) -> List[Dict[str, Any]]:
        """返回命名前缀后的工具定义，供注册层转换 schema。"""
        rows: List[Dict[str, Any]] = []
        for name, schema in self._tool_schemas.items():
            rows.append(
                {
                    "name": name,
                    "description": self._tool_meta.get(name, {}).get("description", ""),
                    "inputSchema": schema,
                }
            )
        return rows

    async def _call_tool_async(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
        client = self._clients.get(server_name)
        if not client:
            raise ValueError(f"MCP server 未连接: {server_name}")
        session = client.get("session")
        return await session.call_tool(tool_name, arguments=arguments)

    def call_tool(self, prefixed_tool_name: str, arguments: Dict[str, Any]) -> str:
        """根据前缀工具名路由到对应 MCP Server 调用。"""
        pair = self._tool_index.get(prefixed_tool_name)
        if not pair:
            raise KeyError(f"未找到 MCP 工具: {prefixed_tool_name}")
        server_name, raw_tool_name = pair
        result = asyncio.run(
            self._call_tool_async(server_name=server_name, tool_name=raw_tool_name, arguments=arguments)
        )
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False)
        content = getattr(result, "content", None)
        if content is not None:
            if isinstance(content, str):
                return content
            return json.dumps(content, ensure_ascii=False)
        return str(result)
