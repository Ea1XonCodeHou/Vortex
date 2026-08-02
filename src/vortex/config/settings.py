"""从环境变量和本地 .env 文件加载运行配置。"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Vortex 无法从本地环境获得有效配置。"""


class VortexSettings(BaseSettings):
    """首期对话能力所需的最小配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    vortex_model: str = "deepseek-v4-flash"
    request_timeout_seconds: float = 180.0

    def require_api_key(self) -> str:
        """返回 API Key，缺失时提供不泄露敏感信息的错误。"""
        if self.deepseek_api_key is None:
            raise ConfigurationError(
                "DeepSeek API key is not configured. Add DEEPSEEK_API_KEY to .env."
            )

        value = self.deepseek_api_key.get_secret_value().strip()
        if not value:
            raise ConfigurationError("DeepSeek API key is empty. Add DEEPSEEK_API_KEY to .env.")
        return value

    def system_prompt(self) -> str:
        """根据当前配置生成真实且最小的身份说明。"""
        return (
            "You are Vortex, a local AI assistant. "
            f"You are currently powered by DeepSeek using the model {self.vortex_model}. "
            "If asked about your identity or underlying model, answer accurately. "
            "Do not claim to be Claude, ChatGPT, or another assistant."
        )
