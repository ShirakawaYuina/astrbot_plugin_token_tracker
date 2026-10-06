from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot.api.provider import Provider
from astrbot.core.provider.entities import LLMResponse, TokenUsage
from astrbot_plugin_token_tracker.interceptor import (
    _estimate_tokens,
    _extract_usage_from_response,
    install_interceptor,
    uninstall_interceptor,
)
from astrbot_plugin_token_tracker.plugin_config import PluginConfig


def test_estimate_tokens():
    assert _estimate_tokens("") == 0
    # 中文 10 字
    zh_text = "这是一段用于测试分词的中文文本"
    tok_zh = _estimate_tokens(zh_text)
    assert tok_zh >= 10

    # 英文
    en_text = "hello world quick brown fox"
    tok_en = _estimate_tokens(en_text)
    assert tok_en > 0


def test_extract_usage_from_object():
    class DummyUsage:
        prompt_tokens = 120
        completion_tokens = 60
        total_tokens = 180
        prompt_tokens_details = None

    class DummyResponse:
        usage = DummyUsage()

    resp = DummyResponse()
    prompt_tok, comp_tok, cache_tok, tot_tok, is_est = _extract_usage_from_response(
        resp,
        prompt="hello",
        contexts=None,
        estimate_fallback=False,
    )
    assert prompt_tok == 120
    assert comp_tok == 60
    assert tot_tok == 180
    assert is_est is False


def test_extract_usage_with_cached():
    class DummyDetails:
        cached_tokens = 45

    class DummyUsage:
        prompt_tokens = 100
        completion_tokens = 50
        total_tokens = 150
        prompt_tokens_details = DummyDetails()

    class DummyResponse:
        usage = DummyUsage()

    resp = DummyResponse()
    prompt_tok, comp_tok, cache_tok, tot_tok, is_est = _extract_usage_from_response(
        resp,
        prompt="hello",
        contexts=None,
        estimate_fallback=False,
    )
    assert prompt_tok == 100
    assert comp_tok == 50
    assert cache_tok == 45
    assert tot_tok == 150


def test_extract_usage_anthropic_and_gemini():
    # Anthropic style raw_completion
    class DummyAnthropicUsage:
        input_tokens = 80
        output_tokens = 40
        cache_read_input_tokens = 20

    class DummyAnthropicRaw:
        usage = DummyAnthropicUsage()

    class DummyAnthropicResp:
        usage = None
        raw_completion = DummyAnthropicRaw()

    p, c, k, tot, is_est = _extract_usage_from_response(DummyAnthropicResp())
    assert p == 80
    assert c == 40
    assert k == 20
    assert tot == 140
    assert is_est is False

    # Gemini style usage_metadata
    class DummyGeminiMeta:
        prompt_token_count = 50
        candidates_token_count = 30
        cached_content_token_count = 10
        total_token_count = 90

    class DummyGeminiRaw:
        usage = None
        usage_metadata = DummyGeminiMeta()

    class DummyGeminiResp:
        usage = None
        raw_completion = DummyGeminiRaw()

    gp, gc, gk, gtot, g_est = _extract_usage_from_response(DummyGeminiResp())
    assert gp == 50
    assert gc == 30
    assert gk == 10
    assert gtot == 90
    assert g_est is False


@pytest.mark.asyncio
async def test_subclass_interception():
    # 创建模拟的 Provider 子类（类似于 ProviderOpenAIOfficial）
    class MockCustomProvider(Provider):
        def __init__(self):
            self.model_name = "test-model-v1"
            self.provider_config = {"id": "test-prov-id", "type": "openai"}

        def get_current_key(self):
            return "dummy-key"

        def get_models(self):
            return ["test-model-v1"]

        def set_key(self, key):
            pass

        async def text_chat(self, *args, **kwargs):
            resp = LLMResponse("assistant")
            resp.usage = TokenUsage(input_other=25, input_cached=5, output=15)
            return resp

    mock_store = MagicMock()
    mock_store.record_usage = AsyncMock()

    cfg = PluginConfig()
    uninstall_interceptor()
    try:
        install_interceptor(mock_store, lambda: cfg)

        inst = MockCustomProvider()
        resp = await inst.text_chat(prompt="Hi")
        assert resp is not None

        # 给异步 task 轮询机会
        await asyncio.sleep(0.05)

        assert mock_store.record_usage.called
        call_kwargs = mock_store.record_usage.call_args.kwargs
        assert call_kwargs["model"] == "test-model-v1"
        assert call_kwargs["provider_id"] == "test-prov-id"
        assert call_kwargs["prompt_tokens"] == 25
        assert call_kwargs["cached_tokens"] == 5
        assert call_kwargs["completion_tokens"] == 15
        assert call_kwargs["total_tokens"] == 45
    finally:
        uninstall_interceptor()


@pytest.mark.asyncio
async def test_embedding_interception():
    from astrbot.core.provider.provider import EmbeddingProvider

    class MockEmbeddingProvider(EmbeddingProvider):
        def __init__(self):
            self.model = "text-embedding-v3-small"
            self.provider_config = {"id": "test-embed-id", "embedding_model": "text-embedding-v3-small"}

        def get_dim(self):
            return 1536

        async def get_embeddings(self, text: list[str]) -> list[list[float]]:
            return [[0.1] * 1536 for _ in text]

        async def get_embedding(self, text: str) -> list[float]:
            # 常见子类实现：get_embedding 内部调用 get_embeddings
            res = await self.get_embeddings([text])
            return res[0]

    mock_store = MagicMock()
    mock_store.record_usage = AsyncMock()

    cfg = PluginConfig()
    uninstall_interceptor()
    try:
        install_interceptor(mock_store, lambda: cfg)

        inst = MockEmbeddingProvider()
        
        # 1. 单条向量化
        vec = await inst.get_embedding("这是一段测试嵌入的文本内容")
        assert len(vec) == 1536
        await asyncio.sleep(0.05)

        # 验证防重入：只记录 1 次
        assert mock_store.record_usage.call_count == 1
        call_kwargs = mock_store.record_usage.call_args.kwargs
        assert call_kwargs["model"] == "text-embedding-v3-small"
        assert call_kwargs["provider_id"] == "test-embed-id"
        assert call_kwargs["prompt_tokens"] >= 10
        assert call_kwargs["completion_tokens"] == 0
        assert call_kwargs["total_tokens"] == call_kwargs["prompt_tokens"]
        assert call_kwargs["is_estimated"] is True

        # 2. 批量向量化
        mock_store.record_usage.reset_mock()
        vecs = await inst.get_embeddings(["apple", "banana", "cherry"])
        assert len(vecs) == 3
        await asyncio.sleep(0.05)

        assert mock_store.record_usage.call_count == 1
        call_kwargs2 = mock_store.record_usage.call_args.kwargs
        assert call_kwargs2["model"] == "text-embedding-v3-small"
        assert call_kwargs2["prompt_tokens"] > 0
        assert call_kwargs2["completion_tokens"] == 0
    finally:
        uninstall_interceptor()

