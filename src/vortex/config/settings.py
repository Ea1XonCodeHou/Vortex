"""从 Vortex 项目私有配置加载运行设置。"""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from vortex.config.paths import VORTEX_ENV_FILE


class ConfigurationError(RuntimeError):
    """Vortex 无法从本地环境获得有效配置。"""


class VortexSettings(BaseSettings):
    """当前单 Agent Runtime 所需的最小配置。"""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    vortex_model: str = "deepseek-v4-flash"
    request_timeout_seconds: float = 180.0
    max_agent_iterations: int = Field(default=24, ge=1, le=80)
    max_agent_tool_calls: int = Field(default=64, ge=1, le=240)
    tool_timeout_seconds: float = Field(default=15.0, gt=0, le=300)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """仅接受显式参数与 Vortex 私有配置，不读取用户工作区环境。"""
        del cls, settings_cls, env_settings, file_secret_settings
        return init_settings, dotenv_settings

    def require_api_key(self) -> str:
        """返回 API Key，缺失时提供不泄露敏感信息的错误。"""
        if self.deepseek_api_key is None:
            raise ConfigurationError(
                "Vortex model credentials are unavailable. "
                "The private Vortex configuration is missing DEEPSEEK_API_KEY."
            )

        value = self.deepseek_api_key.get_secret_value().strip()
        if not value:
            raise ConfigurationError(
                "Vortex model credentials are unavailable. "
                "DEEPSEEK_API_KEY is empty in the private Vortex configuration."
            )
        return value

    def system_prompt(self) -> str:
        """根据当前配置生成真实且最小的身份说明。"""
        return (
            "You are Vortex, a local AI agent. "
            f"You are currently powered by DeepSeek using the model {self.vortex_model}. "
            "If asked about your identity or underlying model, answer accurately. "
            "Do not claim to be Claude, ChatGPT, or another assistant. "
            "Use the available workspace tools whenever a request depends on local files. "
            "Never invent file contents or claim to have inspected a path without using a tool. "
            "For broad repository tasks, use workspace_overview first, inspect instructions and "
            "manifests, then use targeted directory listing and search instead of reading every "
            "dependency or generated file. Read large text files in consecutive chunks when "
            "their complete contents are genuinely required. "
            "When the user's goal is complete, answer with a clear final response and stop "
            "calling tools."
        )


def load_vortex_settings(env_file: Path = VORTEX_ENV_FILE) -> VortexSettings:
    """加载与 Vortex 源码项目绑定、且不受当前工作区影响的配置。"""

    class ProjectVortexSettings(VortexSettings):
        model_config = SettingsConfigDict(
            env_file=env_file,
            env_file_encoding="utf-8",
            extra="ignore",
            case_sensitive=False,
        )

    return ProjectVortexSettings()
