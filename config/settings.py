"""统一读取环境变量并提供类型化配置。"""

from dataclasses import dataclass
import os

from dotenv import load_dotenv


# 在程序启动时加载 .env，避免在各模块重复调用。
load_dotenv()


@dataclass(frozen=True)
class Settings:
    """全局配置对象。

    设计说明：
    - 使用 dataclass 让配置字段集中、可读、可扩展；
    - 使用 frozen=True 防止运行中被意外修改。
    """

    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    parent_model: str
    child_model: str
    amap_api_key: str
    tavily_api_key: str
    mcp_config_path: str


def get_settings() -> Settings:
    """读取环境变量并返回配置对象。"""
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ValueError("缺少环境变量 DEEPSEEK_API_KEY，请先在 .env 中配置。")

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
    parent_model = os.getenv("PARENT_MODEL", model or "deepseek-reasoner").strip()
    child_model = os.getenv("CHILD_MODEL", "deepseek-chat").strip()
    amap_api_key = os.getenv("AMAP_API_KEY", "").strip()
    if not amap_api_key:
        raise ValueError("缺少环境变量 AMAP_API_KEY，请先在 .env 中配置。")
    tavily_api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not tavily_api_key:
        raise ValueError("缺少环境变量 TAVILY_API_KEY，请先在 .env 中配置。")
    mcp_config_path = os.getenv("MCP_CONFIG_PATH", "workspace/mcp/servers.json").strip()

    return Settings(
        deepseek_api_key=api_key,
        deepseek_base_url=base_url,
        deepseek_model=model,
        parent_model=parent_model,
        child_model=child_model,
        amap_api_key=amap_api_key,
        tavily_api_key=tavily_api_key,
        mcp_config_path=mcp_config_path,
    )
