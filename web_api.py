from __future__ import annotations

import csv
import io
import time
from typing import Any

from starlette.responses import Response

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request
from astrbot.core.star.context import Context

from .plugin_config import PluginConfig
from .tracker_store import TrackerStore

PLUGIN_NAME = "astrbot_plugin_token_tracker"


def _safe_query(key: str, default: str = "") -> str:
    try:
        val = request.query.get(key)
        if val is None:
            return default
        return str(val)
    except Exception:
        return default


class TokenTrackerWebApi:
    def __init__(self, context: Context, store: TrackerStore, get_cfg: Any) -> None:
        self.context = context
        self.store = store
        self.get_cfg = get_cfg

    def register_routes(self) -> None:
        """向 AstrBot 注册内置 Web 接口"""
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/overview",
            self.get_overview,
            ["GET"],
            "获取 Token 用量概览看板数据",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/models",
            self.get_models,
            ["GET"],
            "获取按模型聚合的 Token 消耗统计",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/callers",
            self.get_callers,
            ["GET"],
            "获取按调用源/插件聚合的 Token 消耗统计",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/trend",
            self.get_trend,
            ["GET"],
            "获取近 N 天每日用量趋势",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/records",
            self.get_records,
            ["GET"],
            "分页与筛选查询详细调用记录",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/clear",
            self.clear_records,
            ["POST"],
            "清空所有 Token 统计记录",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/export-csv",
            self.export_csv,
            ["GET"],
            "导出历史 Token 用量记录 CSV 文件",
        )
        logger.info("token-tracker | Native Web APIs registered successfully.")

    async def get_overview(self) -> Any:
        try:
            summary = await self.store.get_overview()
            cfg: PluginConfig = self.get_cfg()
            ref_rate = cfg.pricing.reference_rates.get("default", 0.002)
            summary["currency_symbol"] = cfg.pricing.currency_symbol
            summary["estimated_cost_total"] = (summary.get("total_tokens", 0) / 1000.0) * ref_rate
            summary["estimated_cost_today"] = (summary.get("today_tokens", 0) / 1000.0) * ref_rate
            return json_response(summary)
        except Exception as e:
            logger.error("token-tracker | get_overview error: %s", e, exc_info=True)
            return error_response(f"获取概览数据失败: {e}", status_code=500)

    async def get_models(self) -> Any:
        try:
            start_time = 0.0
            raw_start = _safe_query("start_time")
            if raw_start:
                try:
                    start_time = float(raw_start)
                except ValueError:
                    pass
            models = await self.store.get_model_stats(start_time=start_time)
            return json_response({"models": models})
        except Exception as e:
            logger.error("token-tracker | get_models error: %s", e, exc_info=True)
            return error_response(f"获取模型统计失败: {e}", status_code=500)

    async def get_callers(self) -> Any:
        try:
            start_time = 0.0
            raw_start = _safe_query("start_time")
            if raw_start:
                try:
                    start_time = float(raw_start)
                except ValueError:
                    pass
            callers = await self.store.get_caller_stats(start_time=start_time)
            return json_response({"callers": callers})
        except Exception as e:
            logger.error("token-tracker | get_callers error: %s", e, exc_info=True)
            return error_response(f"获取来源统计失败: {e}", status_code=500)

    async def get_trend(self) -> Any:
        try:
            days = 14
            raw_days = _safe_query("days")
            if raw_days:
                try:
                    days = int(raw_days)
                except ValueError:
                    pass
            trends = await self.store.get_trends(days=days)
            return json_response(trends)
        except Exception as e:
            logger.error("token-tracker | get_trend error: %s", e, exc_info=True)
            return error_response(f"获取趋势数据失败: {e}", status_code=500)

    async def get_records(self) -> Any:
        try:
            page = 1
            page_size = 20
            raw_page = _safe_query("page")
            if raw_page:
                try:
                    page = int(raw_page)
                except ValueError:
                    pass
            raw_page_size = _safe_query("page_size")
            if raw_page_size:
                try:
                    page_size = int(raw_page_size)
                except ValueError:
                    pass

            keyword = _safe_query("keyword")
            model = _safe_query("model")
            caller = _safe_query("caller")


            records = await self.store.get_records(
                page=page,
                page_size=page_size,
                keyword=keyword,
                model_filter=model,
                caller_filter=caller,
            )
            return json_response(records)
        except Exception as e:
            logger.error("token-tracker | get_records error: %s", e, exc_info=True)
            return error_response(f"获取详细记录失败: {e}", status_code=500)

    async def clear_records(self) -> Any:
        try:
            await self.store.clear_all()
            return json_response({"status": "ok", "message": "已成功清空所有记录"})
        except Exception as e:
            logger.error("token-tracker | clear_records error: %s", e, exc_info=True)
            return error_response(f"清空记录失败: {e}", status_code=500)

    async def export_csv(self) -> Any:
        try:
            res = await self.store.get_records(page=1, page_size=20000)
            items = res.get("items", [])

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                "ID",
                "时间",
                "模型名称",
                "提供商",
                "调用类型",
                "调用源名称",
                "会话ID",
                "是否流式",
                "是否估算",
                "输入 Token",
                "输出 Token",
                "缓存 Token",
                "总计 Token",
                "响应耗时(ms)",
            ])
            for r in items:
                writer.writerow([
                    r.get("id"),
                    r.get("datetime_str"),
                    r.get("model"),
                    r.get("provider_id"),
                    r.get("caller_type"),
                    r.get("caller_name"),
                    r.get("session_id"),
                    "是" if r.get("is_streaming") else "否",
                    "是" if r.get("is_estimated") else "否",
                    r.get("prompt_tokens"),
                    r.get("completion_tokens"),
                    r.get("cached_tokens"),
                    r.get("total_tokens"),
                    f"{r.get('duration_ms', 0):.1f}",
                ])

            content = buf.getvalue().encode("utf-8-sig")
            filename = f"token_records_{int(time.time())}.csv"
            return Response(
                content=content,
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                },
            )
        except Exception as e:
            logger.error("token-tracker | export_csv error: %s", e, exc_info=True)
            return error_response(f"导出 CSV 失败: {e}", status_code=500)
