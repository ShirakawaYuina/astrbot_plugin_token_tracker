from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .interceptor import install_interceptor, uninstall_interceptor
from .plugin_config import PluginConfig, parse_plugin_config
from .tracker_store import TrackerStore
from .web_api import TokenTrackerWebApi


class Main(star.Star):
    def __init__(self, context: star.Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.context = context
        self.config = config or {}
        self._cfg_cache: PluginConfig | None = None

        plugin_data_dir = (
            Path(get_astrbot_data_path())
            / "plugin_data"
            / "astrbot_plugin_token_tracker"
        )
        plugin_data_dir.mkdir(parents=True, exist_ok=True)
        db_path = plugin_data_dir / "tokens.db"

        self.store = TrackerStore(db_path)

        cfg = self._cfg()
        if cfg.tracker.enable:
            install_interceptor(self.store, self._cfg)
        else:
            logger.info("token-tracker | Tracker is disabled in configuration.")

        # 注册 AstrBot 内置 WebUI API
        self.web_api = TokenTrackerWebApi(self.context, self.store, self._cfg)
        self.web_api.register_routes()

        logger.info(
            "token-tracker | Initialized | db=%s tracker_enabled=%s built-in WebUI page ready",
            db_path,
            cfg.tracker.enable,
        )

    def _cfg(self) -> PluginConfig:
        return parse_plugin_config(self.config)

    async def terminate(self) -> None:
        logger.info("token-tracker | Plugin terminating...")
        uninstall_interceptor()
        logger.info("token-tracker | Plugin terminated.")

    @filter.command("token", alias={"tokens"})
    async def token_command(
        self,
        event: AstrMessageEvent,
        action: str = "",
        extra: str = "",
    ) -> AsyncGenerator[MessageEventResult, None]:
        """Token 统计查询指令"""
        cfg = self._cfg()
        action = (action or "").strip().lower()

        if action in {"help", "帮助", "-h", "--help"}:
            yield event.plain_result(self._render_help())
            return

        if action in {"webui", "ui", "url", "页面"}:
            yield event.plain_result(self._render_webui_info())
            return

        if action in {"today", "今日"}:
            msg = await self._render_today_detail(cfg)
            yield event.plain_result(msg)
            return

        if action in {"top", "排行"}:
            msg = await self._render_top(cfg)
            yield event.plain_result(msg)
            return

        if action in {"reset", "清空"}:
            if not getattr(event, "is_admin", False):
                yield event.plain_result("❌ 权限不足：仅管理员可执行重置操作。")
                return
            if extra.lower() != "confirm":
                yield event.plain_result("⚠️ 危险操作：该操作将清空所有 Token 统计记录！\n如确认清空，请发送：/token reset confirm")
                return
            await self.store.clear_all()
            yield event.plain_result("✅ 已成功清空所有 Token 统计记录。")
            return

        # 默认指令：展示仪表盘摘要
        msg = await self._render_summary(cfg)
        yield event.plain_result(msg)

    async def _render_summary(self, cfg: PluginConfig) -> str:
        summary = await self.store.get_overview()
        models = await self.store.get_model_stats()
        callers = await self.store.get_caller_stats()

        today_tokens = summary.get("today_tokens", 0)
        today_calls = summary.get("today_calls", 0)
        today_prompt = summary.get("today_prompt_tokens", 0)
        today_cached = summary.get("today_cached_tokens", 0)
        today_completion = summary.get("today_completion_tokens", 0)

        total_tokens = summary.get("total_tokens", 0)
        total_calls = summary.get("total_calls", 0)

        cost_total = self._calculate_cost(total_tokens, cfg)
        cost_today = self._calculate_cost(today_tokens, cfg)

        sym = cfg.pricing.currency_symbol

        lines = [
            "📊 Token 用量概况 (Token Tracker)",
            "━━━━━━━━━━━━━━━━━━━━",
            f"📅 今日消耗：",
            f"  • 总计: {today_tokens:,} tokens",
            f"  • 输入: {today_prompt:,} (缓存: {today_cached:,})",
            f"  • 输出: {today_completion:,}",
            f"  • 调用: {today_calls:,} 次",
            "",
            f"📈 历史累计：",
            f"  • 总计: {total_tokens:,} tokens",
            f"  • 调用: {total_calls:,} 次",
            "━━━━━━━━━━━━━━━━━━━━",
        ]

        if models:
            lines.append("🤖 模型消耗 Top 3：")
            for i, m in enumerate(models[:3], 1):
                m_name = m.get("model", "unknown")
                m_tok = m.get("total_tokens", 0)
                pct = (m_tok / total_tokens * 100.0) if total_tokens > 0 else 0.0
                lines.append(f"  {i}. {m_name}: {m_tok:,} ({pct:.1f}%)")
            lines.append("")

        if callers:
            lines.append("🧩 来源消耗 Top 3：")
            for i, c in enumerate(callers[:3], 1):
                c_name = c.get("caller_name", "unknown")
                c_tok = c.get("total_tokens", 0)
                lines.append(f"  {i}. {c_name}: {c_tok:,}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("🌐 内置 WebUI: 请前往 AstrBot 管理面板 -> 左侧导航「插件页面」->「Token 用量看板」查看")
        lines.append("💡 发送 `/token help` 查看更多快捷指令")

        return "\n".join(lines)

    async def _render_today_detail(self, cfg: PluginConfig) -> str:
        summary = await self.store.get_overview()
        today_tokens = summary.get("today_tokens", 0)
        today_calls = summary.get("today_calls", 0)
        today_prompt = summary.get("today_prompt_tokens", 0)
        today_cached = summary.get("today_cached_tokens", 0)
        today_comp = summary.get("today_completion_tokens", 0)

        lines = [
            "📅 今日 Token 详细消耗",
            "━━━━━━━━━━━━━━━━━━━━",
            f"• 总计 Token: {today_tokens:,}",
            f"• 输入 Token: {today_prompt:,}",
            f"• 缓存 Token: {today_cached:,}",
            f"• 输出 Token: {today_comp:,}",
            f"• 调用总次数: {today_calls:,} 次",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        return "\n".join(lines)

    async def _render_top(self, cfg: PluginConfig) -> str:
        models = await self.store.get_model_stats()
        callers = await self.store.get_caller_stats()

        lines = ["🏆 Token 消耗排行榜", "━━━━━━━━━━━━━━━━━━━━", "🤖 模型消耗排行："]
        if not models:
            lines.append("  (暂无记录)")
        else:
            for i, m in enumerate(models[:5], 1):
                m_name = m.get("model", "unknown")
                m_tok = m.get("total_tokens", 0)
                m_calls = m.get("call_count", 0)
                lines.append(f"  {i}. {m_name}: {m_tok:,} tokens ({m_calls} 次调用)")

        lines.append("")
        lines.append("🧩 插件/来源排行：")
        if not callers:
            lines.append("  (暂无记录)")
        else:
            for i, c in enumerate(callers[:5], 1):
                c_name = c.get("caller_name", "unknown")
                c_tok = c.get("total_tokens", 0)
                c_calls = c.get("call_count", 0)
                lines.append(f"  {i}. {c_name}: {c_tok:,} tokens ({c_calls} 次调用)")

        return "\n".join(lines)

    def _render_webui_info(self) -> str:
        return (
            "🌐 Token Tracker 已无缝集成至 AstrBot 内置控制台！\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👉 查看方式：\n"
            "1. 登录 AstrBot 管理控制台\n"
            "2. 点击左侧导航栏的「插件页面」\n"
            "3. 点击「Token 用量看板」即可直接打开可视化大屏！\n"
            "✨ 无需额外端口与登录密码，随开随用！"
        )

    def _render_help(self) -> str:
        return (
            "📖 Token Tracker 指令帮助：\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• `/token` : 查看用量简报与统计摘要\n"
            "• `/token webui` : 查看内置 WebUI 访问指引\n"
            "• `/token today` : 查看今日用量明细\n"
            "• `/token top` : 查看模型与插件消耗排行榜\n"
            "• `/token reset confirm` : (管理员) 清空所有统计记录\n"
            "• `/token help` : 查看本帮助"
        )

    def _calculate_cost(self, tokens: int, cfg: PluginConfig) -> float:
        if tokens <= 0:
            return 0.0
        rate = cfg.pricing.reference_rates.get("default", 0.002)
        return (tokens / 1000.0) * rate
