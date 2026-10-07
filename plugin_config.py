from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _to_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes", "on", "y"}:
            return True
        if v in {"false", "0", "no", "off", "n"}:
            return False
    return default


def _to_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class TrackerSettingsConfig:
    enable: bool = True
    record_streaming: bool = True
    record_embedding: bool = True
    record_image: bool = True
    estimate_when_missing: bool = True
    currency_symbol: str = "¥"


# 别名兼容
TrackerConfig = TrackerSettingsConfig


@dataclass(frozen=True)
class WebUISettingsConfig:
    enable: bool = True
    host: str = "0.0.0.0"
    port: int = 6186
    access_password: str = ""
    session_timeout: int = 86400


# 别名兼容
WebUIConfig = WebUISettingsConfig


@dataclass(frozen=True)
class PricingConfig:
    currency_symbol: str = "¥"
    reference_rates: dict[str, float] = field(
        default_factory=lambda: {
            "default": 0.002,
        }
    )


@dataclass(frozen=True)
class PluginConfig:
    tracker: TrackerSettingsConfig = field(default_factory=TrackerSettingsConfig)
    webui: WebUISettingsConfig = field(default_factory=WebUISettingsConfig)
    pricing: PricingConfig = field(default_factory=PricingConfig)


def parse_plugin_config(raw: dict[str, Any] | None) -> PluginConfig:
    raw = raw or {}

    tracker_raw = raw.get("tracker", {})
    if not isinstance(tracker_raw, dict):
        tracker_raw = {}

    currency_sym = str(
        tracker_raw.get("currency_symbol")
        or (raw.get("pricing", {}).get("currency_symbol") if isinstance(raw.get("pricing"), dict) else None)
        or "¥"
    ).strip() or "¥"

    tracker = TrackerSettingsConfig(
        enable=_to_bool(tracker_raw.get("enable"), True),
        record_streaming=_to_bool(tracker_raw.get("record_streaming"), True),
        record_embedding=_to_bool(tracker_raw.get("record_embedding"), True),
        record_image=_to_bool(tracker_raw.get("record_image"), True),
        estimate_when_missing=_to_bool(tracker_raw.get("estimate_when_missing"), True),
        currency_symbol=currency_sym,
    )

    webui_raw = raw.get("webui", {})
    if not isinstance(webui_raw, dict):
        webui_raw = {}

    webui = WebUISettingsConfig(
        enable=_to_bool(webui_raw.get("enable"), True),
        host=str(webui_raw.get("host") or "0.0.0.0").strip() or "0.0.0.0",
        port=max(1, min(65535, _to_int(webui_raw.get("port"), 6186))),
        access_password=str(webui_raw.get("access_password") or "").strip(),
        session_timeout=max(60, _to_int(webui_raw.get("session_timeout"), 86400)),
    )

    pricing_raw = raw.get("pricing", {})
    ref_rates: dict[str, float] = {"default": 0.002}
    if isinstance(pricing_raw, dict):
        raw_rates = pricing_raw.get("reference_rates")
        if isinstance(raw_rates, dict):
            for k, v in raw_rates.items():
                ref_rates[str(k)] = _to_float(v, 0.002)

    pricing = PricingConfig(
        currency_symbol=currency_sym,
        reference_rates=ref_rates,
    )

    return PluginConfig(
        tracker=tracker,
        webui=webui,
        pricing=pricing,
    )
