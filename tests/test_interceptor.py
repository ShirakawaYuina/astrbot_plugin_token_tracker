from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot.api.provider import Provider
from astrbot.core.provider.entities import LLMResponse, TokenUsage
from astrbot_plugin_token_tracker.interceptor import (
    _estimate_tokens,
    _extract_usage_from_dict,
    _extract_usage_from_response,
    _resolve_image_gateway_provider_id,
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
        assert call_kwargs["prompt_tokens"] == 30
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


def test_extract_usage_from_dict():
    # 1. OpenAI Responses API 风格
    resp_responses = {
        "output": [{"type": "image_generation_call", "result": "xyz"}],
        "usage": {
            "input_tokens": 50,
            "output_tokens": 1000,
            "total_tokens": 1050,
            "input_tokens_details": {"cached_tokens": 12},
        },
    }
    p, c, k, tot = _extract_usage_from_dict(resp_responses)
    assert p == 50
    assert c == 1000
    assert k == 12
    assert tot == 1050

    # 2. OpenAI standard image generation 风格
    resp_images = {
        "data": [{"b64_json": "abc"}],
        "usage": {
            "prompt_tokens": 25,
            "completion_tokens": 750,
            "total_tokens": 775,
            "prompt_tokens_details": {"cached_tokens": 5},
        },
    }
    p2, c2, k2, tot2 = _extract_usage_from_dict(resp_images)
    assert p2 == 25
    assert c2 == 750
    assert k2 == 5
    assert tot2 == 775

    # 3. 顶层扁平字典
    resp_flat = {
        "data": [{"url": "http://img.jpg"}],
        "input_tokens": 15,
        "output_tokens": 500,
    }
    p3, c3, k3, tot3 = _extract_usage_from_dict(resp_flat)
    assert p3 == 15
    assert c3 == 500
    assert k3 == 0
    assert tot3 == 515

    # 4. 无 usage 数据
    resp_none = {"data": [{"b64_json": "abc"}]}
    p4, c4, k4, tot4 = _extract_usage_from_dict(resp_none)
    assert p4 == 0 and c4 == 0 and k4 == 0 and tot4 == 0


def test_resolve_image_gateway_provider_id():
    class DummyGwWithId:
        provider_id = "my-custom-provider"

    assert _resolve_image_gateway_provider_id(DummyGwWithId()) == "my-custom-provider"

    class DummyGwWithEndpoint:
        _images_generations_endpoint = "https://cdn.jucode.top/v1/images/generations"

    assert _resolve_image_gateway_provider_id(DummyGwWithEndpoint()) == "jucode"

    class DummyGwWithOpenAI:
        _images_generations_endpoint = "https://api.openai.com/v1/images/generations"

    assert _resolve_image_gateway_provider_id(DummyGwWithOpenAI()) == "openai"

    class DummyGwFallback:
        pass

    assert _resolve_image_gateway_provider_id(DummyGwFallback()) == "openai_image"


@pytest.mark.asyncio
async def test_openai_image_gateway_interception():
    import sys
    import types

    class MockOpenAIImageGateway:
        def __init__(self):
            self._images_generations_endpoint = "https://cdn.jucode.top/v1/images/generations"
            self._images_edits_endpoint = "https://cdn.jucode.top/v1/images/edits"
            self._endpoint_candidates = ["https://cdn.jucode.top/v1/responses"]

        async def request_response(self, payload):
            if payload.get("trigger_no_usage"):
                return {"output": [{"type": "image_generation_call", "result": "abc"}]}
            return {
                "model": "gpt-image-2",
                "output": [{"type": "image_generation_call", "result": "abc"}],
                "usage": {
                    "input_tokens": 40,
                    "output_tokens": 1000,
                    "total_tokens": 1040,
                    "input_tokens_details": {"cached_tokens": 8},
                },
            }

        async def request_image_generation(self, payload):
            return {
                "data": [{"b64_json": "def"}],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 800,
                    "total_tokens": 820,
                },
            }

        async def request_image_edit(self, data, files):
            return {
                "data": [{"b64_json": "ghi"}],
                "usage": {
                    "prompt_tokens": 30,
                    "completion_tokens": 900,
                    "total_tokens": 930,
                },
            }

    fake_mod_name = "data.plugins.astrbot_plugin_openai_image.core.gateways.openai_image_gateway"
    fake_mod = types.ModuleType(fake_mod_name)
    fake_mod.OpenAIImageGateway = MockOpenAIImageGateway
    sys.modules[fake_mod_name] = fake_mod

    mock_store = MagicMock()
    mock_store.record_usage = AsyncMock()
    cfg = PluginConfig()

    uninstall_interceptor()
    try:
        install_interceptor(mock_store, lambda: cfg)

        inst = MockOpenAIImageGateway()

        # 1. 测试 request_response
        resp1 = await inst.request_response({"model": "gpt-image-2", "prompt": "a cyberpunk city"})
        assert resp1 is not None
        await asyncio.sleep(0.05)

        assert mock_store.record_usage.called
        call1 = mock_store.record_usage.call_args.kwargs
        assert call1["model"] == "gpt-image-2"
        assert call1["provider_id"] == "jucode"
        assert call1["caller_type"] == "plugin"
        assert call1["caller_name"] == "astrbot_plugin_openai_image"
        assert call1["prompt_tokens"] == 40
        assert call1["completion_tokens"] == 1000
        assert call1["cached_tokens"] == 8
        assert call1["total_tokens"] == 1040

        # 2. 测试 request_image_generation
        mock_store.record_usage.reset_mock()
        resp2 = await inst.request_image_generation({"model": "dall-e-3", "prompt": "a cute kitten"})
        assert resp2 is not None
        await asyncio.sleep(0.05)

        assert mock_store.record_usage.called
        call2 = mock_store.record_usage.call_args.kwargs
        assert call2["model"] == "dall-e-3"
        assert call2["provider_id"] == "jucode"
        assert call2["caller_type"] == "plugin"
        assert call2["caller_name"] == "astrbot_plugin_openai_image"
        assert call2["prompt_tokens"] == 20
        assert call2["completion_tokens"] == 800
        assert call2["total_tokens"] == 820

        # 3. 测试 request_image_edit
        mock_store.record_usage.reset_mock()
        resp3 = await inst.request_image_edit(
            {"model": "gpt-image-edit", "prompt": "change background"},
            [("sample.png", b"123", "image/png")],
        )
        assert resp3 is not None
        await asyncio.sleep(0.05)

        assert mock_store.record_usage.called
        call3 = mock_store.record_usage.call_args.kwargs
        assert call3["model"] == "gpt-image-edit"
        assert call3["provider_id"] == "jucode"
        assert call3["caller_type"] == "plugin"
        assert call3["caller_name"] == "astrbot_plugin_openai_image"
        assert call3["prompt_tokens"] == 30
        assert call3["completion_tokens"] == 900
        assert call3["total_tokens"] == 930

        # 4. 无 token 用量返回时跳过记录
        mock_store.record_usage.reset_mock()
        resp4 = await inst.request_response({"trigger_no_usage": True})
        assert resp4 is not None
        await asyncio.sleep(0.05)
        assert not mock_store.record_usage.called

    finally:
        uninstall_interceptor()
        sys.modules.pop(fake_mod_name, None)


@pytest.mark.asyncio
async def test_openai_image_gateway_disabled_config():
    import sys
    import types
    from astrbot_plugin_token_tracker.plugin_config import TrackerSettingsConfig

    class MockOpenAIImageGatewayDisabled:
        async def request_image_generation(self, payload):
            return {
                "data": [{"b64_json": "def"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60},
            }

    fake_mod_name = "data.plugins.astrbot_plugin_openai_image.core.gateways.openai_image_gateway"
    fake_mod = types.ModuleType(fake_mod_name)
    fake_mod.OpenAIImageGateway = MockOpenAIImageGatewayDisabled
    sys.modules[fake_mod_name] = fake_mod

    mock_store = MagicMock()
    mock_store.record_usage = AsyncMock()
    cfg = PluginConfig(tracker=TrackerSettingsConfig(record_image=False))

    uninstall_interceptor()
    try:
        install_interceptor(mock_store, lambda: cfg)
        inst = MockOpenAIImageGatewayDisabled()
        resp = await inst.request_image_generation({"model": "dall-e-3"})
        assert resp is not None
        await asyncio.sleep(0.05)
        # record_image=False 时不应记录
        assert not mock_store.record_usage.called
    finally:
        uninstall_interceptor()
        sys.modules.pop(fake_mod_name, None)

