from __future__ import annotations

import asyncio
import contextvars
import importlib
import inspect
import pkgutil
import time
from collections.abc import AsyncGenerator
from typing import Any

from astrbot.api import logger
from astrbot.api.provider import Provider
from astrbot.core.provider.entities import LLMResponse

from .plugin_config import PluginConfig
from .tracker_store import TrackerStore

# 用于记录所有被打补丁的 (类, 方法名) -> 原始方法
_PATCHED_METHODS: dict[tuple[type, str], Any] = {}
# 用于防止重入（例如子类方法中调用了父类方法导致的重复统计）
_IS_TRACKING: contextvars.ContextVar[bool] = contextvars.ContextVar("token_tracker_in_progress", default=False)


def _identify_caller() -> tuple[str, str]:
    """通过调用栈自动识别调用方是主对话还是具体某个第三方插件"""
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
                ]
            ):
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
        prompt_tokens = getattr(usage, "input_other", 0) or getattr(usage, "prompt_tokens", 0) or 0
        cached_tokens = getattr(usage, "input_cached", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details:
            cached_tokens = getattr(details, "cached_tokens", 0) or cached_tokens
        completion_tokens = getattr(usage, "output", 0) or getattr(usage, "completion_tokens", 0) or 0
        total_tokens = (
            getattr(usage, "total", 0)
            or getattr(usage, "total_tokens", 0)
            or (prompt_tokens + cached_tokens + completion_tokens)
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
    """安全解析模型名称与 Provider ID"""
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


def install_interceptor(store: TrackerStore, get_cfg: Any) -> None:
    """挂载全局切面拦截器至 Provider 基类及所有具体提供商实现子类"""
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

    # 2. 递归收集 Provider 及其所有继承子类
    target_classes: list[type] = [Provider]
    seen: set[type] = {Provider}

    def _recurse_subclasses(cls: type):
        for sub in cls.__subclasses__():
            if sub not in seen:
                seen.add(sub)
                target_classes.append(sub)
                _recurse_subclasses(sub)

    _recurse_subclasses(Provider)

    # 3. 收集注册表中的所有提供商类
    try:
        from astrbot.core.provider.register import provider_cls_map
        for pm in provider_cls_map.values():
            if pm.cls_type and pm.cls_type not in seen:
                seen.add(pm.cls_type)
                target_classes.append(pm.cls_type)
    except Exception:
        pass

    # 4. 对定义了核心调用方法的类安装 AOP 拦截器
    for cls in target_classes:
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

    logger.info(
        f"token-tracker | Global Provider AOP interceptor installed on {len(_PATCHED_METHODS)} methods across: "
        f"{', '.join(sorted({c.__name__ for c, _ in _PATCHED_METHODS.keys()}))}"
    )


def uninstall_interceptor() -> None:
    """还原所有被拦截的 Provider 类方法"""
    global _PATCHED_METHODS

    if not _PATCHED_METHODS:
        return

    for (cls, method_name), original_fn in list(_PATCHED_METHODS.items()):
        setattr(cls, method_name, original_fn)

    _PATCHED_METHODS.clear()
    logger.info("token-tracker | Global Provider AOP interceptor uninstalled.")
