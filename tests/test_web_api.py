from __future__ import annotations

import json
import tempfile
from pathlib import Path
import pytest

from astrbot_plugin_token_tracker.plugin_config import parse_plugin_config
from astrbot_plugin_token_tracker.tracker_store import TrackerStore
from astrbot_plugin_token_tracker.web_api import TokenTrackerWebApi


class DummyContext:
    def __init__(self):
        self.registered_web_apis = []

    def register_web_api(self, route, handler, methods, desc):
        self.registered_web_apis.append((route, handler, methods, desc))


@pytest.mark.asyncio
async def test_web_api_routes():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_api.db"
        store = TrackerStore(db_path)
        cfg = parse_plugin_config({})
        ctx = DummyContext()

        api = TokenTrackerWebApi(ctx, store, lambda: cfg)
        api.register_routes()

        # 检查路由注册
        routes = [r[0] for r in ctx.registered_web_apis]
        assert "/astrbot_plugin_token_tracker/overview" in routes
        assert "/astrbot_plugin_token_tracker/models" in routes
        assert "/astrbot_plugin_token_tracker/callers" in routes
        assert "/astrbot_plugin_token_tracker/trend" in routes
        assert "/astrbot_plugin_token_tracker/records" in routes
        assert "/astrbot_plugin_token_tracker/clear" in routes
        assert "/astrbot_plugin_token_tracker/export-csv" in routes

        # 插入测试数据
        await store.record_usage(
            model="gpt-4o",
            provider_id="openai_main",
            caller_type="conversation",
            caller_name="core_chat",
            session_id="test_sess",
            is_streaming=False,
            is_estimated=False,
            prompt_tokens=100,
            completion_tokens=50,
            cached_tokens=20,
            total_tokens=150,
            duration_ms=500.0,
        )

        # 1. 概览
        res_overview = await api.get_overview()
        assert res_overview.status_code == 200
        body = json.loads(res_overview.body.decode("utf-8"))
        assert body["total_tokens"] == 150
        assert body["today_tokens"] == 150

        # 2. 模型
        res_models = await api.get_models()
        assert res_models.status_code == 200
        body = json.loads(res_models.body.decode("utf-8"))
        assert len(body["models"]) == 1
        assert body["models"][0]["model"] == "gpt-4o"

        # 3. 来源
        res_callers = await api.get_callers()
        assert res_callers.status_code == 200
        body = json.loads(res_callers.body.decode("utf-8"))
        assert len(body["callers"]) == 1
        assert body["callers"][0]["caller_name"] == "core_chat"

        # 4. 趋势
        res_trend = await api.get_trend()
        assert res_trend.status_code == 200
        body = json.loads(res_trend.body.decode("utf-8"))
        assert len(body["labels"]) == 14

        # 5. 明细
        res_records = await api.get_records()
        assert res_records.status_code == 200
        body = json.loads(res_records.body.decode("utf-8"))
        assert body["total"] == 1

        # 6. CSV 导出
        res_csv = await api.export_csv()
        assert res_csv.status_code == 200
        assert b"gpt-4o" in res_csv.body

        # 7. 清空
        res_clear = await api.clear_records()
        assert res_clear.status_code == 200
        res_after = await api.get_overview()
        body_after = json.loads(res_after.body.decode("utf-8"))
        assert body_after["total_tokens"] == 0
