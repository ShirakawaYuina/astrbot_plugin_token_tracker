from __future__ import annotations

import asyncio
import contextvars
import importlib
import inspect
import pkgutil
import sys
import time
from collections.abc import AsyncGenerator
from typing import Any

from astrbot.api import logger
from astrbot.api.provider import Provider
from astrbot.core.provider.entities import LLMResponse

try:
    from astrbot.core.provider.provider import EmbeddingProvider
except Exception:
    EmbeddingProvider = None

from .plugin_config import PluginConfig
from .tracker_store import TrackerStore

# 用于记录所有被打补丁的 (类, 方法名) -> 原始方法
_PATCHED_METHODS: dict[tuple[type, str], Any] = {}
# 用于防止重入（例如子类方法中调用了父类方法导致的重复统计）
_IS_TRACKING: contextvars.ContextVar[bool] = contextvars.ContextVar("token_tracker_in_progress", default=False)
# 用于捕获底层 Embedding SDK（如 OpenAI/DashScope）回传的真实 usage 字段 (prompt_tokens, model)
_CAPTURED_EMBEDDING_USAGE: contextvars.ContextVar[tuple[int, str] | None] = contextvars.ContextVar("captured_embedding_usage", default=None)


def _identify_caller() -> tuple[str, str]:
    """通过调用栈自动识别调用方是主对话、知识库还是具体某个第三方插件（如 livingmemory）"""
    try:
        stack = inspect.stack()
        for frame_info in stack[2:20]:
            fn = frame_info.filename.replace("\\", "/")
            if "data/plugins/" in fn or "astrbot_plugin_" in fn:
                # 尝试从 data/plugins/<plugin_dir>/ 路径中提取插件名
                if "data/plugins/" in fn:
                    idx = fn.find("data/plugins/") + len("data/plugins/")
                    folder = fn[idx:].split("/")[0]
                    if folder and folder != "astrbot_plugin_token_tracker":
                        return "plugin", folder
                # 或者通过文件名特征
                parts = fn.split("/")
                for p in parts:
                    if p.startswith("astrbot_plugin_") and p != "astrbot_plugin_token_tracker":
                        return "plugin", p
            if any(
                marker in fn
                for marker in [
                    "astrbot/core/agent",
                    "astrbot/core/conversation",
                    "astrbot/core/pipeline",
                    "astrbot/core/star",
                    "knowledge_base",
                ]
            ):
                if "knowledge_base" in fn:
                    return "knowledge_base", "kb_rag"
                return "conversation", "core_chat"
    except Exception:
        pass
    return "conversation", "core_chat"


def _estimate_tokens(text: str) -> int:
    """轻量级 Token 估算：中文字符约 0.7~1.0 token，英文字词约 0.25~0.3 token"""
    if not text:
        return 0
    c_count = 0
    w_count = 0
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            c_count += 1
        else:
            w_count += 1
    return int(c_count * 1.0 + (w_count / 3.5))


def _extract_usage_from_response(
    resp: LLMResponse | Any,
    prompt: str = "",
    contexts: Any = None,
    estimate_fallback: bool = True,
) -> tuple[int, int, int, int, bool]:
    """提取 (prompt_tokens, completion_tokens, cached_tokens, total_tokens, is_estimated)"""
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    total_tokens = 0
    is_estimated = False

    # 1. 优先读取 LLMResponse.usage (TokenUsage)
    usage = getattr(resp, "usage", None)
    if usage:
        cached_tokens = getattr(usage, "input_cached", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details:
            cached_tokens = getattr(details, "cached_tokens", 0) or cached_tokens

        raw_prompt = getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0) or 0
        if raw_prompt > 0:
            prompt_tokens = raw_prompt
        else:
            prompt_tokens = (getattr(usage, "input_other", 0) or 0) + cached_tokens

        completion_tokens = getattr(usage, "output", 0) or getattr(usage, "completion_tokens", 0) or 0
        total_tokens = (
            getattr(usage, "total", 0)
            or getattr(usage, "total_tokens", 0)
            or (prompt_tokens + completion_tokens)
        )

    # 2. 次级检查 raw_completion (OpenAI / Anthropic / Gemini 等原生响应对象)
    if total_tokens <= 0:
        raw = getattr(resp, "raw_completion", None)
        if raw:
            raw_usage = getattr(raw, "usage", None)
            if raw_usage:
                prompt_tokens = (
                    getattr(raw_usage, "prompt_tokens", 0)
                    or getattr(raw_usage, "input_tokens", 0)
                    or 0
                )
                completion_tokens = (
                    getattr(raw_usage, "completion_tokens", 0)
                    or getattr(raw_usage, "output_tokens", 0)
                    or 0
                )
                cached_tokens = (
                    getattr(raw_usage, "cached_tokens", 0)
                    or getattr(raw_usage, "cache_read_input_tokens", 0)
                    or 0
                )
                details = getattr(raw_usage, "prompt_tokens_details", None)
                if details:
                    cached_tokens = getattr(details, "cached_tokens", 0) or cached_tokens
                total_tokens = (
                    getattr(raw_usage, "total_tokens", 0)
                    or (prompt_tokens + cached_tokens + completion_tokens)
                )

            # 兼容 Google GenAI usage_metadata
            usage_meta = getattr(raw, "usage_metadata", None)
            if usage_meta and total_tokens <= 0:
                prompt_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
                completion_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0
                cached_tokens = getattr(usage_meta, "cached_content_token_count", 0) or 0
                total_tokens = (
                    getattr(usage_meta, "total_token_count", 0)
                    or (prompt_tokens + cached_tokens + completion_tokens)
                )

    # 3. 兜底估算
    if total_tokens <= 0 and estimate_fallback:
        is_estimated = True
        context_str = ""
        if isinstance(contexts, list):
            context_str = str(contexts)
        prompt_tokens = _estimate_tokens(str(prompt or "") + context_str)
        comp_text = getattr(resp, "completion_text", "") or ""
        completion_tokens = _estimate_tokens(str(comp_text))
        total_tokens = prompt_tokens + completion_tokens

    if total_tokens <= 0:
        total_tokens = prompt_tokens + cached_tokens + completion_tokens

    return prompt_tokens, completion_tokens, cached_tokens, total_tokens, is_estimated


def _resolve_model_and_provider(
    self: Any, kwargs: dict[str, Any], resp: Any = None
) -> tuple[str, str]:
    """安全解析 LLM 对话模型名称与 Provider ID"""
    model_name = (
        kwargs.get("model")
        or (getattr(self, "get_model", None)() if callable(getattr(self, "get_model", None)) else None)
        or getattr(self, "model_name", None)
        or (
            self.provider_config.get("model")
            if hasattr(self, "provider_config") and isinstance(self.provider_config, dict)
            else None
        )
        or None
    )

    if (not model_name or model_name == "unknown") and resp:
        raw = getattr(resp, "raw_completion", None)
        if raw:
            model_name = getattr(raw, "model", None) or getattr(raw, "model_name", None)

    if not model_name:
        model_name = "unknown"

    provider_id = (
        kwargs.get("provider_id")
        or getattr(self, "provider_id", None)
        or (
            self.provider_config.get("id")
            if hasattr(self, "provider_config") and isinstance(self.provider_config, dict)
            else None
        )
        or (
            self.provider_config.get("type")
            if hasattr(self, "provider_config") and isinstance(self.provider_config, dict)
            else None
        )
        or "default"
    )
    return str(model_name), str(provider_id)


def _resolve_embedding_model_and_provider(self: Any) -> tuple[str, str]:
    """安全解析 Embedding 向量模型的名称与 Provider ID"""
    model_name = (
        getattr(self, "model", None)
        or (getattr(self, "get_model", None)() if callable(getattr(self, "get_model", None)) else None)
        or getattr(self, "model_name", None)
        or (
            self.provider_config.get("embedding_model")
            if hasattr(self, "provider_config") and isinstance(self.provider_config, dict)
            else None
        )
        or (
            self.provider_config.get("model")
            if hasattr(self, "provider_config") and isinstance(self.provider_config, dict)
            else None
        )
        or "unknown_embedding_model"
    )

    provider_id = (
        getattr(self, "provider_id", None)
        or (
            self.provider_config.get("id")
            if hasattr(self, "provider_config") and isinstance(self.provider_config, dict)
            else None
        )
        or (
            self.provider_config.get("type")
            if hasattr(self, "provider_config") and isinstance(self.provider_config, dict)
            else None
        )
        or "default"
    )
    return str(model_name), str(provider_id)


def _extract_session_id_from_stack() -> str:
    """尝试从调用栈帧中解析当前消息事件的会话 ID (session_id)"""
    try:
        stack = inspect.stack()
        for frame_info in stack[2:20]:
            f_locals = frame_info.frame.f_locals
            if "event" in f_locals:
                evt = f_locals["event"]
                sid = getattr(evt, "session_id", None) or getattr(evt, "unified_msg_origin", None)
                if sid:
                    return str(sid)
            if "session_id" in f_locals:
                sid = f_locals["session_id"]
                if sid:
                    return str(sid)
    except Exception:
        pass
    return ""


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        try:
            return int(val.strip())
        except ValueError:
            return default
    return default


def _extract_usage_from_dict(resp_dict: Any) -> tuple[int, int, int, int]:
    """提取生图/改图响应字典中的 (prompt_tokens, completion_tokens, cached_tokens, total_tokens)
    
    兼容:
    1. OpenAI Responses API: output + usage {input_tokens, output_tokens, total_tokens, input_tokens_details: {cached_tokens}}
    2. OpenAI Chat/Completions: usage {prompt_tokens, completion_tokens, total_tokens, prompt_tokens_details: {cached_tokens}}
    3. 代理/三方中转生图: usage {input_tokens/prompt_tokens, output_tokens/completion_tokens, total_tokens}
    4. 扁平顶层字典: {prompt_tokens, completion_tokens, total_tokens}
    """
    if not isinstance(resp_dict, dict):
        return 0, 0, 0, 0

    has_nested_usage = isinstance(resp_dict.get("usage"), dict)
    usage = resp_dict["usage"] if has_nested_usage else resp_dict

    cached_tokens = 0
    in_details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details")
    if isinstance(in_details, dict):
        cached_tokens = _safe_int(in_details.get("cached_tokens"), 0)

    # 1. 提取输入 Token (Prompt)
    raw_prompt = usage.get("input_tokens")
    if raw_prompt is None:
        raw_prompt = usage.get("prompt_tokens")
    if raw_prompt is None and has_nested_usage and ("input_other" in usage or "input_cached" in usage):
        raw_prompt = _safe_int(usage.get("input_other"), 0) + _safe_int(usage.get("input_cached"), 0)
    prompt_tokens = _safe_int(raw_prompt, 0)

    # 2. 提取输出 Token (Completion)
    raw_comp = usage.get("output_tokens")
    if raw_comp is None:
        raw_comp = usage.get("completion_tokens")
    if raw_comp is None and has_nested_usage:
        raw_comp = usage.get("output", 0)
    completion_tokens = _safe_int(raw_comp, 0)

    # 3. 提取或计算总 Token (Total)
    raw_total = usage.get("total_tokens")
    if raw_total is None and has_nested_usage:
        raw_total = usage.get("total")

    total_tokens = _safe_int(raw_total, 0)
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens

    if total_tokens <= 0 and (prompt_tokens > 0 or completion_tokens > 0):
        total_tokens = prompt_tokens + completion_tokens

    return prompt_tokens, completion_tokens, cached_tokens, total_tokens


def _resolve_image_gateway_provider_id(gateway: Any) -> str:
    """解析生图网关的 Provider ID（优先读取自身 provider_id，其次提取 endpoint host，兜底 openai_image）"""
    if hasattr(gateway, "provider_id") and gateway.provider_id:
        return str(gateway.provider_id)
    endpoint = getattr(gateway, "_images_generations_endpoint", "") or ""
    if not endpoint and hasattr(gateway, "_endpoint_candidates"):
        candidates = getattr(gateway, "_endpoint_candidates", [])
        if candidates and isinstance(candidates, list) and candidates:
            endpoint = candidates[0]
    if endpoint:
        try:
            from urllib.parse import urlsplit
            host = urlsplit(str(endpoint)).hostname or ""
            if host:
                parts = host.split(".")
                if len(parts) >= 2 and not parts[-1].isdigit():
                    return parts[-2]
                return host
        except Exception:
            pass
    return "openai_image"


def _find_openai_image_gateway_classes() -> list[type]:
    """动态搜寻并导入 astrbot_plugin_openai_image 插件中的 OpenAIImageGateway 类"""
    classes: list[type] = []
    seen: set[type] = set()

    candidate_modules = [
        "data.plugins.astrbot_plugin_openai_image.core.gateways.openai_image_gateway",
        "astrbot_plugin_openai_image.core.gateways.openai_image_gateway",
    ]
    for mod_name in candidate_modules:
        try:
            mod = sys.modules.get(mod_name) or importlib.import_module(mod_name)
            cls = getattr(mod, "OpenAIImageGateway", None)
            if inspect.isclass(cls) and cls not in seen:
                seen.add(cls)
                classes.append(cls)
        except Exception:
            pass

    # 扫描已加载模块，防止在特定命名空间或路径下未匹配
    for mod_name, mod in list(sys.modules.items()):
        if "openai_image_gateway" in mod_name and mod:
            cls = getattr(mod, "OpenAIImageGateway", None)
            if inspect.isclass(cls) and cls not in seen:
                seen.add(cls)
                classes.append(cls)

    return classes


def install_interceptor(store: TrackerStore, get_cfg: Any) -> None:
    """挂载全局切面拦截器至 LLM 对话 Provider 及 EmbeddingProvider 基类与所有具体提供商子类"""
    global _PATCHED_METHODS

    if _PATCHED_METHODS:
        return

    # 1. 尝试导入所有官方已内置的 provider 模块以确保子类完全注册
    try:
        import astrbot.core.provider.sources as sources_pkg
        for _, modname, _ in pkgutil.iter_modules(sources_pkg.__path__):
            try:
                importlib.import_module(f"astrbot.core.provider.sources.{modname}")
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"token-tracker | load provider sources: {e}")

    # 2. 递归收集对话 Provider 及其所有继承子类
    chat_classes: list[type] = [Provider]
    seen_chat: set[type] = {Provider}

    def _recurse_subclasses(cls: type, target_list: list[type], seen_set: set[type]):
        for sub in cls.__subclasses__():
            if sub not in seen_set:
                seen_set.add(sub)
                target_list.append(sub)
                _recurse_subclasses(sub, target_list, seen_set)

    _recurse_subclasses(Provider, chat_classes, seen_chat)

    # 收集注册表中的所有提供商类
    try:
        from astrbot.core.provider.register import provider_cls_map
        for pm in provider_cls_map.values():
            if pm.cls_type and pm.cls_type not in seen_chat:
                seen_chat.add(pm.cls_type)
                chat_classes.append(pm.cls_type)
    except Exception:
        pass

    # 3. 递归收集 EmbeddingProvider 及其所有继承子类
    embedding_classes: list[type] = []
    seen_embedding: set[type] = set()
    if EmbeddingProvider is not None:
        embedding_classes.append(EmbeddingProvider)
        seen_embedding.add(EmbeddingProvider)
        _recurse_subclasses(EmbeddingProvider, embedding_classes, seen_embedding)

    # 4. 对定义了对话方法的类安装 AOP 拦截器
    for cls in chat_classes:
        # Patch text_chat
        if "text_chat" in cls.__dict__:
            orig_chat = cls.__dict__["text_chat"]
            _PATCHED_METHODS[(cls, "text_chat")] = orig_chat

            def _make_chat_wrapper(original_fn: Any):
                async def patched_text_chat(self: Provider, *args: Any, **kwargs: Any) -> LLMResponse:
                    cfg: PluginConfig = get_cfg()
                    if not cfg.tracker.enable or _IS_TRACKING.get():
                        return await original_fn(self, *args, **kwargs)

                    token = _IS_TRACKING.set(True)
                    start_time = time.time()
                    session_id = kwargs.get("session_id") or ""
                    prompt = kwargs.get("prompt") or (args[0] if args else "")
                    contexts = kwargs.get("contexts")
                    caller_type, caller_name = _identify_caller()

                    try:
                        resp: LLMResponse = await original_fn(self, *args, **kwargs)
                        duration_ms = (time.time() - start_time) * 1000.0

                        model_name, provider_id = _resolve_model_and_provider(self, kwargs, resp)
                        prompt_tok, comp_tok, cache_tok, tot_tok, is_est = _extract_usage_from_response(
                            resp,
                            prompt=str(prompt or ""),
                            contexts=contexts,
                            estimate_fallback=cfg.tracker.estimate_when_missing,
                        )

                        # 异步入库
                        asyncio.create_task(
                            store.record_usage(
                                model=model_name,
                                provider_id=provider_id,
                                caller_type=caller_type,
                                caller_name=caller_name,
                                session_id=str(session_id or ""),
                                is_streaming=False,
                                is_estimated=is_est,
                                prompt_tokens=prompt_tok,
                                completion_tokens=comp_tok,
                                cached_tokens=cache_tok,
                                total_tokens=tot_tok,
                                duration_ms=duration_ms,
                            )
                        )
                        return resp
                    finally:
                        _IS_TRACKING.reset(token)

                return patched_text_chat

            cls.text_chat = _make_chat_wrapper(orig_chat)

        # Patch text_chat_stream
        if "text_chat_stream" in cls.__dict__:
            orig_stream = cls.__dict__["text_chat_stream"]
            _PATCHED_METHODS[(cls, "text_chat_stream")] = orig_stream

            def _make_stream_wrapper(original_fn: Any):
                async def patched_text_chat_stream(
                    self: Provider, *args: Any, **kwargs: Any
                ) -> AsyncGenerator[LLMResponse, None]:
                    cfg: PluginConfig = get_cfg()
                    if not cfg.tracker.enable or not cfg.tracker.record_streaming or _IS_TRACKING.get():
                        async for chunk in original_fn(self, *args, **kwargs):
                            yield chunk
                        return

                    token = _IS_TRACKING.set(True)
                    start_time = time.time()
                    session_id = kwargs.get("session_id") or ""
                    prompt = kwargs.get("prompt") or (args[0] if args else "")
                    contexts = kwargs.get("contexts")
                    caller_type, caller_name = _identify_caller()

                    accumulated_chunks = []
                    captured_usage_chunk = None

                    try:
                        async for chunk in original_fn(self, *args, **kwargs):
                            if chunk:
                                accumulated_chunks.append(chunk)
                                if getattr(chunk, "usage", None) or (
                                    getattr(chunk, "raw_completion", None) and getattr(chunk.raw_completion, "usage", None)
                                ):
                                    captured_usage_chunk = chunk
                            yield chunk
                    finally:
                        _IS_TRACKING.reset(token)
                        duration_ms = (time.time() - start_time) * 1000.0
                        prompt_tok, comp_tok, cache_tok, tot_tok = 0, 0, 0, 0
                        is_est = False

                        if captured_usage_chunk:
                            prompt_tok, comp_tok, cache_tok, tot_tok, is_est = _extract_usage_from_response(
                                captured_usage_chunk,
                                prompt=str(prompt or ""),
                                contexts=contexts,
                                estimate_fallback=False,
                            )

                        if tot_tok <= 0 and cfg.tracker.estimate_when_missing:
                            full_text = "".join(
                                getattr(c, "completion_text", "") or "" for c in accumulated_chunks
                            )
                            context_str = str(contexts) if isinstance(contexts, list) else ""
                            prompt_tok = _estimate_tokens(str(prompt or "") + context_str)
                            comp_tok = _estimate_tokens(full_text)
                            tot_tok = prompt_tok + comp_tok
                            is_est = True

                        if tot_tok > 0:
                            model_name, provider_id = _resolve_model_and_provider(
                                self, kwargs, captured_usage_chunk
                            )
                            asyncio.create_task(
                                store.record_usage(
                                    model=model_name,
                                    provider_id=provider_id,
                                    caller_type=caller_type,
                                    caller_name=caller_name,
                                    session_id=str(session_id or ""),
                                    is_streaming=True,
                                    is_estimated=is_est,
                                    prompt_tokens=prompt_tok,
                                    completion_tokens=comp_tok,
                                    cached_tokens=cache_tok,
                                    total_tokens=tot_tok,
                                    duration_ms=duration_ms,
                                )
                            )

                return patched_text_chat_stream

            cls.text_chat_stream = _make_stream_wrapper(orig_stream)

    # 5. 对底层 SDK 客户端打补丁以精确截获 API 官方 usage 响应（OpenAI SDK & DashScope SDK）
    try:
        from openai.resources.embeddings import AsyncEmbeddings
        if "create" in AsyncEmbeddings.__dict__:
            orig_ae_create = AsyncEmbeddings.create
            _PATCHED_METHODS[(AsyncEmbeddings, "create")] = orig_ae_create

            async def patched_ae_create(self: Any, *args: Any, **kwargs: Any) -> Any:
                resp = await orig_ae_create(self, *args, **kwargs)
                try:
                    usage = getattr(resp, "usage", None)
                    if usage:
                        tok = (
                            getattr(usage, "prompt_tokens", 0)
                            or getattr(usage, "total_tokens", 0)
                            or getattr(usage, "input_tokens", 0)
                            or 0
                        )
                        model = getattr(resp, "model", "") or kwargs.get("model") or ""
                        if tok > 0:
                            _CAPTURED_EMBEDDING_USAGE.set((int(tok), str(model)))
                except Exception:
                    pass
                return resp

            AsyncEmbeddings.create = patched_ae_create
    except Exception as e:
        logger.debug(f"token-tracker | openai AsyncEmbeddings patch: {e}")

    try:
        import dashscope
        if hasattr(dashscope, "TextEmbedding") and hasattr(dashscope.TextEmbedding, "call"):
            orig_te_call = dashscope.TextEmbedding.call
            _PATCHED_METHODS[(dashscope.TextEmbedding, "call")] = orig_te_call

            def patched_te_call(*args: Any, **kwargs: Any) -> Any:
                resp = orig_te_call(*args, **kwargs)
                try:
                    usage = getattr(resp, "usage", None)
                    if usage:
                        tok = getattr(usage, "total_tokens", 0)
                        model = kwargs.get("model") or ""
                        if tok > 0:
                            _CAPTURED_EMBEDDING_USAGE.set((int(tok), str(model)))
                except Exception:
                    pass
                return resp

            dashscope.TextEmbedding.call = patched_te_call
    except Exception as e:
        logger.debug(f"token-tracker | dashscope TextEmbedding patch: {e}")

    # 6. 对定义了向量化方法的 Embedding 类安装 AOP 拦截器（如 livingmemory / 知识库）
    for cls in embedding_classes:
        # Patch get_embedding
        if "get_embedding" in cls.__dict__:
            orig_ge = cls.__dict__["get_embedding"]
            _PATCHED_METHODS[(cls, "get_embedding")] = orig_ge

            def _make_embedding_wrapper(original_fn: Any):
                async def patched_get_embedding(self: Any, text: str, *args: Any, **kwargs: Any) -> list[float]:
                    cfg: PluginConfig = get_cfg()
                    if (
                        not cfg.tracker.enable
                        or not getattr(cfg.tracker, "record_embedding", True)
                        or _IS_TRACKING.get()
                    ):
                        return await original_fn(self, text, *args, **kwargs)

                    token = _IS_TRACKING.set(True)
                    start_time = time.time()
                    caller_type, caller_name = _identify_caller()
                    _CAPTURED_EMBEDDING_USAGE.set(None)

                    try:
                        res = await original_fn(self, text, *args, **kwargs)
                        duration_ms = (time.time() - start_time) * 1000.0

                        model_name, provider_id = _resolve_embedding_model_and_provider(self)
                        captured = _CAPTURED_EMBEDDING_USAGE.get()
                        if captured and captured[0] > 0:
                            prompt_tok = captured[0]
                            is_est = False
                            if captured[1]:
                                model_name = captured[1]
                        else:
                            prompt_tok = _estimate_tokens(str(text or ""))
                            is_est = True

                        if prompt_tok > 0:
                            asyncio.create_task(
                                store.record_usage(
                                    model=model_name,
                                    provider_id=provider_id,
                                    caller_type=caller_type,
                                    caller_name=caller_name,
                                    session_id="",
                                    is_streaming=False,
                                    is_estimated=is_est,
                                    prompt_tokens=prompt_tok,
                                    completion_tokens=0,
                                    cached_tokens=0,
                                    total_tokens=prompt_tok,
                                    duration_ms=duration_ms,
                                )
                            )
                        return res
                    finally:
                        _CAPTURED_EMBEDDING_USAGE.set(None)
                        _IS_TRACKING.reset(token)

                return patched_get_embedding

            cls.get_embedding = _make_embedding_wrapper(orig_ge)

        # Patch get_embeddings (批量向量化)
        if "get_embeddings" in cls.__dict__:
            orig_ges = cls.__dict__["get_embeddings"]
            _PATCHED_METHODS[(cls, "get_embeddings")] = orig_ges

            def _make_embeddings_wrapper(original_fn: Any):
                async def patched_get_embeddings(
                    self: Any, text: list[str], *args: Any, **kwargs: Any
                ) -> list[list[float]]:
                    cfg: PluginConfig = get_cfg()
                    if (
                        not cfg.tracker.enable
                        or not getattr(cfg.tracker, "record_embedding", True)
                        or _IS_TRACKING.get()
                    ):
                        return await original_fn(self, text, *args, **kwargs)

                    token = _IS_TRACKING.set(True)
                    start_time = time.time()
                    caller_type, caller_name = _identify_caller()
                    _CAPTURED_EMBEDDING_USAGE.set(None)

                    try:
                        res = await original_fn(self, text, *args, **kwargs)
                        duration_ms = (time.time() - start_time) * 1000.0

                        model_name, provider_id = _resolve_embedding_model_and_provider(self)
                        captured = _CAPTURED_EMBEDDING_USAGE.get()
                        if captured and captured[0] > 0:
                            prompt_tok = captured[0]
                            is_est = False
                            if captured[1]:
                                model_name = captured[1]
                        else:
                            texts = text if isinstance(text, list) else [text]
                            prompt_tok = sum(_estimate_tokens(str(t or "")) for t in texts)
                            is_est = True

                        if prompt_tok > 0:
                            asyncio.create_task(
                                store.record_usage(
                                    model=model_name,
                                    provider_id=provider_id,
                                    caller_type=caller_type,
                                    caller_name=caller_name,
                                    session_id="",
                                    is_streaming=False,
                                    is_estimated=is_est,
                                    prompt_tokens=prompt_tok,
                                    completion_tokens=0,
                                    cached_tokens=0,
                                    total_tokens=prompt_tok,
                                    duration_ms=duration_ms,
                                )
                            )
                        return res
                    finally:
                        _CAPTURED_EMBEDDING_USAGE.set(None)
                        _IS_TRACKING.reset(token)

                return patched_get_embeddings

            cls.get_embeddings = _make_embeddings_wrapper(orig_ges)

    # 7. 对生图插件 OpenAIImageGateway 安装 AOP 拦截器
    image_gateway_classes = _find_openai_image_gateway_classes()
    for gw_cls in image_gateway_classes:
        # Patch request_response
        if "request_response" in gw_cls.__dict__:
            orig_rr = gw_cls.__dict__["request_response"]
            _PATCHED_METHODS[(gw_cls, "request_response")] = orig_rr

            def _make_response_wrapper(original_fn: Any):
                async def patched_request_response(
                    self: Any, payload: dict[str, Any], *args: Any, **kwargs: Any
                ) -> dict[str, Any]:
                    cfg: PluginConfig = get_cfg()
                    if (
                        not cfg.tracker.enable
                        or not getattr(cfg.tracker, "record_image", True)
                        or _IS_TRACKING.get()
                    ):
                        return await original_fn(self, payload, *args, **kwargs)

                    token = _IS_TRACKING.set(True)
                    start_time = time.time()
                    session_id = _extract_session_id_from_stack()
                    try:
                        resp = await original_fn(self, payload, *args, **kwargs)
                        duration_ms = (time.time() - start_time) * 1000.0

                        model_name = (
                            (resp.get("model") if isinstance(resp, dict) else None)
                            or (payload.get("model") if isinstance(payload, dict) else None)
                            or "openai-image"
                        )
                        provider_id = _resolve_image_gateway_provider_id(self)
                        prompt_tok, comp_tok, cache_tok, tot_tok = _extract_usage_from_dict(resp)

                        if tot_tok > 0:
                            asyncio.create_task(
                                store.record_usage(
                                    model=str(model_name),
                                    provider_id=str(provider_id),
                                    caller_type="plugin",
                                    caller_name="astrbot_plugin_openai_image",
                                    session_id=str(session_id or ""),
                                    is_streaming=False,
                                    is_estimated=False,
                                    prompt_tokens=prompt_tok,
                                    completion_tokens=comp_tok,
                                    cached_tokens=cache_tok,
                                    total_tokens=tot_tok,
                                    duration_ms=duration_ms,
                                )
                            )
                        return resp
                    finally:
                        _IS_TRACKING.reset(token)

                return patched_request_response

            gw_cls.request_response = _make_response_wrapper(orig_rr)

        # Patch request_image_generation
        if "request_image_generation" in gw_cls.__dict__:
            orig_rig = gw_cls.__dict__["request_image_generation"]
            _PATCHED_METHODS[(gw_cls, "request_image_generation")] = orig_rig

            def _make_image_gen_wrapper(original_fn: Any):
                async def patched_request_image_generation(
                    self: Any, payload: dict[str, Any], *args: Any, **kwargs: Any
                ) -> dict[str, Any]:
                    cfg: PluginConfig = get_cfg()
                    if (
                        not cfg.tracker.enable
                        or not getattr(cfg.tracker, "record_image", True)
                        or _IS_TRACKING.get()
                    ):
                        return await original_fn(self, payload, *args, **kwargs)

                    token = _IS_TRACKING.set(True)
                    start_time = time.time()
                    session_id = _extract_session_id_from_stack()
                    try:
                        resp = await original_fn(self, payload, *args, **kwargs)
                        duration_ms = (time.time() - start_time) * 1000.0

                        model_name = (
                            (resp.get("model") if isinstance(resp, dict) else None)
                            or (payload.get("model") if isinstance(payload, dict) else None)
                            or "dall-e-3"
                        )
                        provider_id = _resolve_image_gateway_provider_id(self)
                        prompt_tok, comp_tok, cache_tok, tot_tok = _extract_usage_from_dict(resp)

                        if tot_tok > 0:
                            asyncio.create_task(
                                store.record_usage(
                                    model=str(model_name),
                                    provider_id=str(provider_id),
                                    caller_type="plugin",
                                    caller_name="astrbot_plugin_openai_image",
                                    session_id=str(session_id or ""),
                                    is_streaming=False,
                                    is_estimated=False,
                                    prompt_tokens=prompt_tok,
                                    completion_tokens=comp_tok,
                                    cached_tokens=cache_tok,
                                    total_tokens=tot_tok,
                                    duration_ms=duration_ms,
                                )
                            )
                        return resp
                    finally:
                        _IS_TRACKING.reset(token)

                return patched_request_image_generation

            gw_cls.request_image_generation = _make_image_gen_wrapper(orig_rig)

        # Patch request_image_edit
        if "request_image_edit" in gw_cls.__dict__:
            orig_rie = gw_cls.__dict__["request_image_edit"]
            _PATCHED_METHODS[(gw_cls, "request_image_edit")] = orig_rie

            def _make_image_edit_wrapper(original_fn: Any):
                async def patched_request_image_edit(
                    self: Any,
                    data: dict[str, str],
                    files: list[tuple[str, bytes, str]],
                    *args: Any,
                    **kwargs: Any,
                ) -> dict[str, Any]:
                    cfg: PluginConfig = get_cfg()
                    if (
                        not cfg.tracker.enable
                        or not getattr(cfg.tracker, "record_image", True)
                        or _IS_TRACKING.get()
                    ):
                        return await original_fn(self, data, files, *args, **kwargs)

                    token = _IS_TRACKING.set(True)
                    start_time = time.time()
                    session_id = _extract_session_id_from_stack()
                    try:
                        resp = await original_fn(self, data, files, *args, **kwargs)
                        duration_ms = (time.time() - start_time) * 1000.0

                        model_name = (
                            (resp.get("model") if isinstance(resp, dict) else None)
                            or (data.get("model") if isinstance(data, dict) else None)
                            or "dall-e-2"
                        )
                        provider_id = _resolve_image_gateway_provider_id(self)
                        prompt_tok, comp_tok, cache_tok, tot_tok = _extract_usage_from_dict(resp)

                        if tot_tok > 0:
                            asyncio.create_task(
                                store.record_usage(
                                    model=str(model_name),
                                    provider_id=str(provider_id),
                                    caller_type="plugin",
                                    caller_name="astrbot_plugin_openai_image",
                                    session_id=str(session_id or ""),
                                    is_streaming=False,
                                    is_estimated=False,
                                    prompt_tokens=prompt_tok,
                                    completion_tokens=comp_tok,
                                    cached_tokens=cache_tok,
                                    total_tokens=tot_tok,
                                    duration_ms=duration_ms,
                                )
                            )
                        return resp
                    finally:
                        _IS_TRACKING.reset(token)

                return patched_request_image_edit

            gw_cls.request_image_edit = _make_image_edit_wrapper(orig_rie)

    logger.info(
        f"token-tracker | Global Provider AOP interceptor installed on {len(_PATCHED_METHODS)} methods across: "
        f"{', '.join(sorted({c.__name__ for c, _ in _PATCHED_METHODS.keys()}))}"
    )


def uninstall_interceptor() -> None:
    """还原所有被拦截的 Provider、EmbeddingProvider 及生图网关类方法"""
    global _PATCHED_METHODS

    if not _PATCHED_METHODS:
        return

    for (cls, method_name), original_fn in list(_PATCHED_METHODS.items()):
        setattr(cls, method_name, original_fn)

    _PATCHED_METHODS.clear()
    logger.info("token-tracker | Global Provider AOP interceptor uninstalled.")
