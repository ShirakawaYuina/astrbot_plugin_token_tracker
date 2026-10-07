from __future__ import annotations

import asyncio
import datetime
import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class TrackerStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    datetime_str TEXT NOT NULL,
                    date_str TEXT NOT NULL,
                    hour_str TEXT NOT NULL,
                    model TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    caller_type TEXT NOT NULL,
                    caller_name TEXT NOT NULL,
                    session_id TEXT,
                    is_streaming INTEGER NOT NULL DEFAULT 0,
                    is_estimated INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    duration_ms REAL NOT NULL DEFAULT 0.0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_timestamp ON token_records(timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_model ON token_records(model)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_date ON token_records(date_str)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_caller ON token_records(caller_name)"
            )
            # 兼容历史数据: 确保早期记录中 prompt_tokens 包含 cached_tokens
            conn.execute(
                """
                UPDATE token_records 
                SET prompt_tokens = total_tokens - completion_tokens 
                WHERE total_tokens = (prompt_tokens + cached_tokens + completion_tokens) 
                  AND cached_tokens > 0 
                  AND total_tokens > (prompt_tokens + completion_tokens)
                """
            )

    async def record_usage(
        self,
        *,
        model: str,
        provider_id: str = "default",
        caller_type: str = "conversation",
        caller_name: str = "core_chat",
        session_id: str = "",
        is_streaming: bool = False,
        is_estimated: bool = False,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
        total_tokens: int = 0,
        duration_ms: float = 0.0,
    ) -> int:
        now = time.time()
        dt = datetime.datetime.fromtimestamp(now)
        datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        date_str = dt.strftime("%Y-%m-%d")
        hour_str = dt.strftime("%Y-%m-%d %H:00")

        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens

        clean_model = str(model or "unknown").strip() or "unknown"
        clean_provider = str(provider_id or "default").strip() or "default"
        clean_caller_type = str(caller_type or "unknown").strip()
        clean_caller_name = str(caller_name or "unknown").strip()

        async with self._lock:
            loop = asyncio.get_running_loop()

            def _insert() -> int:
                with self._get_connection() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO token_records (
                            timestamp, datetime_str, date_str, hour_str,
                            model, provider_id, caller_type, caller_name,
                            session_id, is_streaming, is_estimated,
                            prompt_tokens, completion_tokens, cached_tokens,
                            total_tokens, duration_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            now,
                            datetime_str,
                            date_str,
                            hour_str,
                            clean_model,
                            clean_provider,
                            clean_caller_type,
                            clean_caller_name,
                            str(session_id or ""),
                            1 if is_streaming else 0,
                            1 if is_estimated else 0,
                            max(0, prompt_tokens),
                            max(0, completion_tokens),
                            max(0, cached_tokens),
                            max(0, total_tokens),
                            max(0.0, float(duration_ms)),
                        ),
                    )
                    return cur.lastrowid or 0

            return await loop.run_in_executor(None, _insert)

    async def get_overview(
        self, *, start_time: float = 0.0, end_time: float = 0.0
    ) -> dict[str, Any]:
        """获取 Token 消耗总览看板数据（支持指定时段与历史数据统计）"""
        now = time.time()
        today_date = datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        seven_days_ago = now - (7 * 86400)
        thirty_days_ago = now - (30 * 86400)

        async with self._lock:
            loop = asyncio.get_running_loop()

            def _query() -> dict[str, Any]:
                with self._get_connection() as conn:
                    # 1. 历史总用量
                    total_row = conn.execute(
                        """
                        SELECT 
                            COUNT(*) as total_calls,
                            COALESCE(SUM(prompt_tokens), 0) as total_prompt,
                            COALESCE(SUM(completion_tokens), 0) as total_completion,
                            COALESCE(SUM(cached_tokens), 0) as total_cached,
                            COALESCE(SUM(total_tokens), 0) as total_tokens,
                            COUNT(DISTINCT model) as distinct_models,
                            COUNT(DISTINCT caller_name) as distinct_callers,
                            COALESCE(AVG(duration_ms), 0.0) as avg_duration_ms
                        FROM token_records
                        """
                    ).fetchone()

                    # 2. 今日用量
                    today_row = conn.execute(
                        """
                        SELECT 
                            COUNT(*) as today_calls,
                            COALESCE(SUM(total_tokens), 0) as today_tokens,
                            COALESCE(SUM(prompt_tokens), 0) as today_prompt,
                            COALESCE(SUM(completion_tokens), 0) as today_completion,
                            COALESCE(SUM(cached_tokens), 0) as today_cached,
                            COALESCE(AVG(duration_ms), 0.0) as today_avg_duration
                        FROM token_records
                        WHERE date_str = ?
                        """,
                        (today_date,),
                    ).fetchone()

                    # 3. 近 7 天用量
                    week_row = conn.execute(
                        """
                        SELECT 
                            COUNT(*) as week_calls,
                            COALESCE(SUM(total_tokens), 0) as week_tokens
                        FROM token_records
                        WHERE timestamp >= ?
                        """,
                        (seven_days_ago,),
                    ).fetchone()

                    # 4. 近 30 天用量
                    month_row = conn.execute(
                        """
                        SELECT 
                            COUNT(*) as month_calls,
                            COALESCE(SUM(total_tokens), 0) as month_tokens
                        FROM token_records
                        WHERE timestamp >= ?
                        """,
                        (thirty_days_ago,),
                    ).fetchone()

                    # 5. 指定筛选时段用量
                    has_period = bool(start_time > 0 or end_time > 0)
                    period_conds: list[str] = []
                    period_params: list[Any] = []
                    if start_time > 0:
                        period_conds.append("timestamp >= ?")
                        period_params.append(start_time)
                    if end_time > 0:
                        period_conds.append("timestamp <= ?")
                        period_params.append(end_time)

                    period_where = f"WHERE {' AND '.join(period_conds)}" if period_conds else ""
                    period_row = conn.execute(
                        f"""
                        SELECT 
                            COUNT(*) as period_calls,
                            COALESCE(SUM(total_tokens), 0) as period_tokens,
                            COALESCE(SUM(prompt_tokens), 0) as period_prompt,
                            COALESCE(SUM(completion_tokens), 0) as period_completion,
                            COALESCE(SUM(cached_tokens), 0) as period_cached,
                            COUNT(DISTINCT model) as period_distinct_models,
                            COUNT(DISTINCT caller_name) as period_distinct_callers,
                            COALESCE(AVG(duration_ms), 0.0) as period_avg_duration
                        FROM token_records
                        {period_where}
                        """,
                        period_params,
                    ).fetchone()

                    return {
                        "total_tokens": int(total_row["total_tokens"]),
                        "total_prompt_tokens": int(total_row["total_prompt"]),
                        "total_completion_tokens": int(total_row["total_completion"]),
                        "total_cached_tokens": int(total_row["total_cached"]),
                        "total_calls": int(total_row["total_calls"]),
                        "distinct_models": int(total_row["distinct_models"]),
                        "distinct_callers": int(total_row["distinct_callers"]),
                        "avg_duration_ms": round(float(total_row["avg_duration_ms"]), 1),
                        "today_tokens": int(today_row["today_tokens"]),
                        "today_prompt_tokens": int(today_row["today_prompt"]),
                        "today_completion_tokens": int(today_row["today_completion"]),
                        "today_cached_tokens": int(today_row["today_cached"]),
                        "today_calls": int(today_row["today_calls"]),
                        "today_avg_duration_ms": round(float(today_row["today_avg_duration"]), 1),
                        "week_tokens": int(week_row["week_tokens"]),
                        "week_calls": int(week_row["week_calls"]),
                        "month_tokens": int(month_row["month_tokens"]),
                        "month_calls": int(month_row["month_calls"]),
                        "has_period_filter": has_period,
                        "period_tokens": int(period_row["period_tokens"]),
                        "period_prompt_tokens": int(period_row["period_prompt"]),
                        "period_completion_tokens": int(period_row["period_completion"]),
                        "period_cached_tokens": int(period_row["period_cached"]),
                        "period_calls": int(period_row["period_calls"]),
                        "period_distinct_models": int(period_row["period_distinct_models"]),
                        "period_distinct_callers": int(period_row["period_distinct_callers"]),
                        "period_avg_duration_ms": round(float(period_row["period_avg_duration"]), 1),
                    }

            return await loop.run_in_executor(None, _query)

    async def get_model_stats(
        self, *, start_time: float = 0.0, end_time: float = 0.0
    ) -> list[dict[str, Any]]:
        async with self._lock:
            loop = asyncio.get_running_loop()

            def _query() -> list[dict[str, Any]]:
                with self._get_connection() as conn:
                    params: list[Any] = []
                    conditions: list[str] = []
                    if start_time > 0:
                        conditions.append("timestamp >= ?")
                        params.append(start_time)
                    if end_time > 0:
                        conditions.append("timestamp <= ?")
                        params.append(end_time)

                    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                    query = f"""
                        SELECT 
                            model,
                            COUNT(*) as call_count,
                            COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                            COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                            COALESCE(SUM(cached_tokens), 0) as cached_tokens,
                            COALESCE(SUM(total_tokens), 0) as total_tokens,
                            COALESCE(AVG(duration_ms), 0.0) as avg_duration_ms
                        FROM token_records
                        {where_clause}
                        GROUP BY model
                        ORDER BY total_tokens DESC
                    """
                    rows = conn.execute(query, params).fetchall()
                    return [
                        {
                            "model": row["model"],
                            "call_count": int(row["call_count"]),
                            "prompt_tokens": int(row["prompt_tokens"]),
                            "completion_tokens": int(row["completion_tokens"]),
                            "cached_tokens": int(row["cached_tokens"]),
                            "total_tokens": int(row["total_tokens"]),
                            "avg_duration_ms": round(float(row["avg_duration_ms"]), 1),
                        }
                        for row in rows
                    ]

            return await loop.run_in_executor(None, _query)

    async def get_caller_stats(
        self, *, start_time: float = 0.0, end_time: float = 0.0
    ) -> list[dict[str, Any]]:
        async with self._lock:
            loop = asyncio.get_running_loop()

            def _query() -> list[dict[str, Any]]:
                with self._get_connection() as conn:
                    params: list[Any] = []
                    conditions: list[str] = []
                    if start_time > 0:
                        conditions.append("timestamp >= ?")
                        params.append(start_time)
                    if end_time > 0:
                        conditions.append("timestamp <= ?")
                        params.append(end_time)

                    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                    query = f"""
                        SELECT 
                            caller_name,
                            caller_type,
                            COUNT(*) as call_count,
                            COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                            COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                            COALESCE(SUM(cached_tokens), 0) as cached_tokens,
                            COALESCE(SUM(total_tokens), 0) as total_tokens
                        FROM token_records
                        {where_clause}
                        GROUP BY caller_name, caller_type
                        ORDER BY total_tokens DESC
                    """
                    rows = conn.execute(query, params).fetchall()
                    return [
                        {
                            "caller_name": row["caller_name"],
                            "caller_type": row["caller_type"],
                            "call_count": int(row["call_count"]),
                            "prompt_tokens": int(row["prompt_tokens"]),
                            "completion_tokens": int(row["completion_tokens"]),
                            "cached_tokens": int(row["cached_tokens"]),
                            "total_tokens": int(row["total_tokens"]),
                        }
                        for row in rows
                    ]

            return await loop.run_in_executor(None, _query)

    async def _get_hourly_trends(self, start_time: float, end_time: float) -> dict[str, Any]:
        async with self._lock:
            loop = asyncio.get_running_loop()

            def _query() -> dict[str, Any]:
                with self._get_connection() as conn:
                    rows = conn.execute(
                        """
                        SELECT 
                            hour_str,
                            COUNT(*) as call_count,
                            COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                            COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                            COALESCE(SUM(total_tokens), 0) as total_tokens
                        FROM token_records
                        WHERE timestamp >= ? AND timestamp <= ?
                        GROUP BY hour_str
                        ORDER BY hour_str ASC
                        """,
                        (start_time, end_time),
                    ).fetchall()

                    data_by_hour = {row["hour_str"]: row for row in rows}
                    start_dt = datetime.datetime.fromtimestamp(start_time).replace(minute=0, second=0, microsecond=0)
                    end_dt = datetime.datetime.fromtimestamp(end_time).replace(minute=0, second=0, microsecond=0)

                    labels = []
                    totals = []
                    prompts = []
                    completions = []
                    calls = []

                    curr = start_dt
                    step_count = 0
                    while curr <= end_dt and step_count < 48:
                        h_str = curr.strftime("%Y-%m-%d %H:00")
                        display_label = curr.strftime("%H:00")
                        labels.append(display_label)
                        if h_str in data_by_hour:
                            r = data_by_hour[h_str]
                            totals.append(int(r["total_tokens"]))
                            prompts.append(int(r["prompt_tokens"]))
                            completions.append(int(r["completion_tokens"]))
                            calls.append(int(r["call_count"]))
                        else:
                            totals.append(0)
                            prompts.append(0)
                            completions.append(0)
                            calls.append(0)
                        curr += datetime.timedelta(hours=1)
                        step_count += 1

                    return {
                        "labels": labels,
                        "totals": totals,
                        "prompts": prompts,
                        "completions": completions,
                        "calls": calls,
                        "mode": "hourly",
                    }

            return await loop.run_in_executor(None, _query)

    async def _get_range_daily_trends(self, start_time: float, end_time: float) -> dict[str, Any]:
        async with self._lock:
            loop = asyncio.get_running_loop()

            def _query() -> dict[str, Any]:
                with self._get_connection() as conn:
                    rows = conn.execute(
                        """
                        SELECT 
                            date_str,
                            COUNT(*) as call_count,
                            COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                            COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                            COALESCE(SUM(total_tokens), 0) as total_tokens
                        FROM token_records
                        WHERE timestamp >= ? AND timestamp <= ?
                        GROUP BY date_str
                        ORDER BY date_str ASC
                        """,
                        (start_time, end_time),
                    ).fetchall()

                    data_by_date = {row["date_str"]: row for row in rows}
                    start_d = datetime.datetime.fromtimestamp(start_time).date()
                    end_d = datetime.datetime.fromtimestamp(end_time).date()

                    labels = []
                    totals = []
                    prompts = []
                    completions = []
                    calls = []

                    curr = start_d
                    step_count = 0
                    while curr <= end_d and step_count < 366:
                        d_str = curr.strftime("%Y-%m-%d")
                        labels.append(d_str)
                        if d_str in data_by_date:
                            r = data_by_date[d_str]
                            totals.append(int(r["total_tokens"]))
                            prompts.append(int(r["prompt_tokens"]))
                            completions.append(int(r["completion_tokens"]))
                            calls.append(int(r["call_count"]))
                        else:
                            totals.append(0)
                            prompts.append(0)
                            completions.append(0)
                            calls.append(0)
                        curr += datetime.timedelta(days=1)
                        step_count += 1

                    return {
                        "labels": labels,
                        "totals": totals,
                        "prompts": prompts,
                        "completions": completions,
                        "calls": calls,
                        "mode": "daily",
                    }

            return await loop.run_in_executor(None, _query)

    async def get_trends(
        self, *, days: int = 14, start_time: float = 0.0, end_time: float = 0.0
    ) -> dict[str, Any]:
        """获取用量趋势 (支持自定义天数或指定起止时间范围)"""
        now = time.time()
        if start_time > 0 and end_time > 0 and end_time >= start_time:
            span = end_time - start_time
            if span <= 36 * 3600:
                return await self._get_hourly_trends(start_time, end_time)
            return await self._get_range_daily_trends(start_time, end_time)

        start_dt = datetime.datetime.fromtimestamp(now) - datetime.timedelta(days=max(1, days) - 1)
        cutoff = start_dt.timestamp()
        async with self._lock:
            loop = asyncio.get_running_loop()

            def _query() -> dict[str, Any]:
                with self._get_connection() as conn:
                    rows = conn.execute(
                        """
                        SELECT 
                            date_str,
                            COUNT(*) as call_count,
                            COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                            COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                            COALESCE(SUM(total_tokens), 0) as total_tokens
                        FROM token_records
                        WHERE timestamp >= ?
                        GROUP BY date_str
                        ORDER BY date_str ASC
                        """,
                        (cutoff,),
                    ).fetchall()

                    data_by_date = {row["date_str"]: row for row in rows}

                    labels = []
                    totals = []
                    prompts = []
                    completions = []
                    calls = []

                    for i in range(max(1, days)):
                        d = (start_dt + datetime.timedelta(days=i)).strftime("%Y-%m-%d")
                        labels.append(d)
                        if d in data_by_date:
                            row = data_by_date[d]
                            totals.append(int(row["total_tokens"]))
                            prompts.append(int(row["prompt_tokens"]))
                            completions.append(int(row["completion_tokens"]))
                            calls.append(int(row["call_count"]))
                        else:
                            totals.append(0)
                            prompts.append(0)
                            completions.append(0)
                            calls.append(0)

                    return {
                        "labels": labels,
                        "totals": totals,
                        "prompts": prompts,
                        "completions": completions,
                        "calls": calls,
                        "mode": "daily",
                    }

            return await loop.run_in_executor(None, _query)

    async def get_recent_daily_trend(self, *, days: int = 14) -> list[dict[str, Any]]:
        trend_dict = await self.get_trends(days=days)
        result = []
        for i, label in enumerate(trend_dict.get("labels", [])):
            result.append({
                "date": label,
                "total_tokens": trend_dict["totals"][i] if i < len(trend_dict["totals"]) else 0,
                "prompt_tokens": trend_dict["prompts"][i] if i < len(trend_dict["prompts"]) else 0,
                "completion_tokens": trend_dict["completions"][i] if i < len(trend_dict["completions"]) else 0,
                "call_count": trend_dict["calls"][i] if i < len(trend_dict["calls"]) else 0,
            })
        return result

    async def get_records(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        model: str = "",
        model_filter: str = "",
        caller: str = "",
        caller_filter: str = "",
        keyword: str = "",
        start_time: float = 0.0,
        end_time: float = 0.0,
        start_date: str = "",
        end_date: str = "",
    ) -> dict[str, Any]:
        safe_page = max(1, page)
        safe_page_size = max(1, min(200, page_size))
        offset = (safe_page - 1) * safe_page_size

        target_model = (model or model_filter or "").strip()
        target_caller = (caller or caller_filter or "").strip()
        target_keyword = keyword.strip()
        target_start_date = start_date.strip()
        target_end_date = end_date.strip()

        async with self._lock:
            loop = asyncio.get_running_loop()

            def _query() -> dict[str, Any]:
                with self._get_connection() as conn:
                    conditions = []
                    params: list[Any] = []
                    if target_model:
                        conditions.append("model LIKE ?")
                        params.append(f"%{target_model}%")
                    if target_caller:
                        conditions.append("caller_name LIKE ?")
                        params.append(f"%{target_caller}%")
                    if target_keyword:
                        conditions.append("(model LIKE ? OR caller_name LIKE ? OR session_id LIKE ?)")
                        params.extend([f"%{target_keyword}%", f"%{target_keyword}%", f"%{target_keyword}%"])
                    if start_time > 0:
                        conditions.append("timestamp >= ?")
                        params.append(start_time)
                    if end_time > 0:
                        conditions.append("timestamp <= ?")
                        params.append(end_time)
                    if target_start_date:
                        conditions.append("date_str >= ?")
                        params.append(target_start_date)
                    if target_end_date:
                        conditions.append("date_str <= ?")
                        params.append(target_end_date)

                    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

                    count_cur = conn.execute(
                        f"SELECT COUNT(*) as total FROM token_records {where_sql}",
                        params,
                    )
                    total_count = int(count_cur.fetchone()["total"])

                    query_sql = f"""
                        SELECT 
                            id, datetime_str, model, provider_id,
                            caller_type, caller_name, session_id,
                            is_streaming, is_estimated,
                            prompt_tokens, completion_tokens, cached_tokens,
                            total_tokens, duration_ms
                        FROM token_records
                        {where_sql}
                        ORDER BY id DESC
                        LIMIT ? OFFSET ?
                    """
                    rows = conn.execute(query_sql, params + [safe_page_size, offset]).fetchall()
                    items = [dict(row) for row in rows]

                    return {
                        "total": total_count,
                        "page": safe_page,
                        "page_size": safe_page_size,
                        "total_pages": max(1, (total_count + safe_page_size - 1) // safe_page_size),
                        "items": items,
                    }

            return await loop.run_in_executor(None, _query)

    async def clear_all(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()

            def _clear() -> None:
                with self._get_connection() as conn:
                    conn.execute("DELETE FROM token_records")

            await loop.run_in_executor(None, _clear)
            
    # 别名兼容
    get_overview_summary = get_overview
    get_model_aggregation = get_model_stats
    get_caller_aggregation = get_caller_stats
    clear_records = clear_all

