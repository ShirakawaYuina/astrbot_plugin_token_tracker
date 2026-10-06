from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from astrbot_plugin_token_tracker.tracker_store import TrackerStore


@pytest.mark.asyncio
async def test_tracker_store_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_tokens.db"
        store = TrackerStore(db_path)

        # 1. 初始状态总览为空
        overview = await store.get_overview_summary()
        assert overview["total_tokens"] == 0
        assert overview["total_calls"] == 0

        # 2. 插入记录 1 (主对话, gpt-4o)
        await store.record_usage(
            model="gpt-4o",
            provider_id="openai_chat",
            caller_type="conversation",
            caller_name="core_chat",
            session_id="session_123",
            is_streaming=False,
            is_estimated=False,
            prompt_tokens=100,
            completion_tokens=50,
            cached_tokens=20,
            total_tokens=150,
            duration_ms=1200.5,
        )

        # 3. 插入记录 2 (插件, deepseek-chat, 流式)
        await store.record_usage(
            model="deepseek-chat",
            provider_id="deepseek_main",
            caller_type="plugin",
            caller_name="astrbot_plugin_meme_manager",
            session_id="session_456",
            is_streaming=True,
            is_estimated=False,
            prompt_tokens=200,
            completion_tokens=80,
            cached_tokens=0,
            total_tokens=280,
            duration_ms=2500.0,
        )

        # 4. 插入记录 3 (另一个插件, gpt-4o, 估算)
        await store.record_usage(
            model="gpt-4o",
            provider_id="openai_chat",
            caller_type="plugin",
            caller_name="astrbot_plugin_astrbot_enhance_mode",
            session_id="session_789",
            is_streaming=False,
            is_estimated=True,
            prompt_tokens=300,
            completion_tokens=100,
            cached_tokens=0,
            total_tokens=400,
            duration_ms=1800.0,
        )

        # 5. 校验总览
        overview = await store.get_overview_summary()
        assert overview["total_tokens"] == 150 + 280 + 400
        assert overview["total_calls"] == 3
        assert overview["total_prompt_tokens"] == 100 + 200 + 300
        assert overview["total_completion_tokens"] == 50 + 80 + 100
        assert overview["total_cached_tokens"] == 20
        assert overview["today_tokens"] == 150 + 280 + 400
        assert overview["today_calls"] == 3

        # 6. 按模型聚合
        model_aggs = await store.get_model_aggregation()
        assert len(model_aggs) == 2
        # gpt-4o 应为第 1 (150 + 400 = 550)
        assert model_aggs[0]["model"] == "gpt-4o"
        assert model_aggs[0]["total_tokens"] == 550
        assert model_aggs[0]["call_count"] == 2
        # deepseek-chat 应为第 2 (280)
        assert model_aggs[1]["model"] == "deepseek-chat"
        assert model_aggs[1]["total_tokens"] == 280

        # 7. 按来源聚合
        caller_aggs = await store.get_caller_aggregation()
        assert len(caller_aggs) == 3
        names = [c["caller_name"] for c in caller_aggs]
        assert "astrbot_plugin_astrbot_enhance_mode" in names
        assert "astrbot_plugin_meme_manager" in names
        assert "core_chat" in names

        # 8. 近日趋势
        trends = await store.get_recent_daily_trend(days=7)
        assert len(trends) == 7
        assert trends[-1]["total_tokens"] == 150 + 280 + 400

        # 9. 分页与搜索记录
        paged = await store.get_records(page=1, page_size=10, model_filter="gpt-4o")
        assert paged["total"] == 2
        assert len(paged["items"]) == 2

        # 10. 清空记录
        await store.clear_records()
        overview_after = await store.get_overview_summary()
        assert overview_after["total_tokens"] == 0
        assert overview_after["total_calls"] == 0
