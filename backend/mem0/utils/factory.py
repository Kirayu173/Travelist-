import importlib
from typing import Dict, Optional, Union

from mem0.configs.embeddings.base import BaseEmbedderConfig
from mem0.configs.llms.base import BaseLlmConfig
from mem0.configs.llms.ollama import OllamaConfig
from mem0.configs.rerankers.base import BaseRerankerConfig


def load_class(class_type):
    module_path, class_name = class_type.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


class LlmFactory:
    """
    Factory for creating LLM instances with appropriate configurations.
    Supports both old-style BaseLlmConfig and new provider-specific configs.
    """

    # Provider mappings with their config classes
    provider_to_class = {
        "ollama": ("mem0.llms.ollama.OllamaLLM", OllamaConfig),
    }

    @classmethod
    def create(
        cls,
        provider_name: str,
        config: Optional[Union[BaseLlmConfig, Dict]] = None,
        **kwargs,
    ):
        """
        Create an LLM instance with the appropriate configuration.

        Args:
            provider_name (str): The provider name (e.g., 'openai', 'anthropic')
            config: Configuration object or dict. If None, will create default config
            **kwargs: Additional configuration parameters

        Returns:
            Configured LLM instance

        Raises:
            ValueError: If provider is not supported
        """
        if provider_name not in cls.provider_to_class:
            raise ValueError(f"Unsupported Llm provider: {provider_name}")

        class_type, config_class = cls.provider_to_class[provider_name]
        llm_class = load_class(class_type)

        # Handle configuration
        if config is None:
            # Create default config with kwargs
            config = config_class(**kwargs)
        elif isinstance(config, dict):
            # Merge dict config with kwargs
            config.update(kwargs)
            config = config_class(**config)
        elif isinstance(config, BaseLlmConfig):
            # Convert base config to provider-specific config if needed
            if config_class != BaseLlmConfig:
                # Convert to provider-specific config
                config_dict = {
                    "model": config.model,
                    "temperature": config.temperature,
                    "api_key": config.api_key,
                    "max_tokens": config.max_tokens,
                    "top_p": config.top_p,
                    "top_k": config.top_k,
                    "enable_vision": config.enable_vision,
                    "vision_details": config.vision_details,
                    "http_client_proxies": config.http_client,
                }
                config_dict.update(kwargs)
                config = config_class(**config_dict)
            else:
                # Use base config as-is
                pass
        else:
            # Assume it's already the correct config type
            pass

        return llm_class(config)

    @classmethod
    def register_provider(cls, name: str, class_path: str, config_class=None):
        """
        Register a new provider.

        Args:
            name (str): Provider name
            class_path (str): Full path to LLM class
            config_class: Configuration class for the provider (defaults to BaseLlmConfig)
        """
        if config_class is None:
            config_class = BaseLlmConfig
        cls.provider_to_class[name] = (class_path, config_class)

    @classmethod
    def get_supported_providers(cls) -> list:
        """
        Get list of supported providers.

        Returns:
            list: List of supported provider names
        """
        return list(cls.provider_to_class.keys())


class EmbedderFactory:
    provider_to_class = {
        "ollama": "mem0.embeddings.ollama.OllamaEmbedding",
    }

    @classmethod
    def create(cls, provider_name, config, vector_config: Optional[dict]):
        class_type = cls.provider_to_class.get(provider_name)
        if class_type:
            embedder_instance = load_class(class_type)
            base_config = BaseEmbedderConfig(**config)
            return embedder_instance(base_config)
        else:
            raise ValueError(f"Unsupported Embedder provider: {provider_name}")


class VectorStoreFactory:
    provider_to_class = {
        "pgvector": "mem0.vector_stores.pgvector.PGVector",
        "pgarray": "mem0.vector_stores.pgarray.PGArray",
    }

    @classmethod
    def create(cls, provider_name, config):
        class_type = cls.provider_to_class.get(provider_name)
        if class_type:
            if not isinstance(config, dict):
                config = config.model_dump()
            vector_store_instance = load_class(class_type)
            return vector_store_instance(**config)
        else:
            raise ValueError(f"Unsupported VectorStore provider: {provider_name}")

    @classmethod
    def reset(cls, instance):
        instance.reset()
        return instance


class GraphStoreFactory:
    """
    Factory for creating MemoryGraph instances for different graph store providers.
    Usage: GraphStoreFactory.create(provider_name, config)
    """

    provider_to_class = {
        "default": "mem0.memory.graph_memory.MemoryGraph",
    }

    @classmethod
    def create(cls, provider_name, config):
        class_type = cls.provider_to_class.get(
            provider_name, cls.provider_to_class["default"]
        )
        try:
            GraphClass = load_class(class_type)
        except (ImportError, AttributeError) as e:
            raise ImportError(
                f"Could not import MemoryGraph for provider '{provider_name}': {e}"
            )
        return GraphClass(config)


class RerankerFactory:
    """
    Factory for creating reranker instances with appropriate configurations.
    Supports provider-specific configs following the same pattern as other factories.
    """

    # Provider mappings with their config classes - only base config is kept
    provider_to_class = {}

    @classmethod
    def create(
        cls,
        provider_name: str,
        config: Optional[Union[BaseRerankerConfig, Dict]] = None,
        **kwargs,
    ):
        """
        Create a reranker instance based on the provider and configuration.

        Args:
            provider_name: The reranker provider
            config: Configuration object or dictionary
            **kwargs: Additional configuration parameters

        Returns:
            Reranker instance configured for the specified provider

        Raises:
            ValueError: If the provider is not supported
        """
        raise ValueError(f"Unsupported reranker provider: {provider_name}")
        # Reranker implementations have been removed to reduce dependencies
