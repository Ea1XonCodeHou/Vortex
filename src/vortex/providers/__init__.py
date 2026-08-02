"""模型供应商适配层。"""

from vortex.providers.base import ModelProvider
from vortex.providers.deepseek import DeepSeekProvider

__all__ = ["DeepSeekProvider", "ModelProvider"]
