from __future__ import annotations

import pytest

from astrbot_plugin_token_tracker.plugin_config import (
    PluginConfig,
    PricingConfig,
    TrackerConfig,
    WebUIConfig,
    parse_plugin_config,
)


def test_default_config():
    cfg = parse_plugin_config({})
    assert isinstance(cfg, PluginConfig)
    assert cfg.tracker.enable is True
    assert cfg.tracker.record_streaming is True
    assert cfg.tracker.record_embedding is True
    assert cfg.tracker.estimate_when_missing is True
    assert cfg.webui.enable is True
    assert cfg.webui.port == 6186
    assert cfg.pricing.currency_symbol == "¥"


def test_custom_config():
    custom = {
        "tracker": {
            "enable": False,
            "record_streaming": False,
            "record_embedding": False,
            "estimate_when_missing": False,
        },
        "webui": {
            "enable": True,
            "port": 6188,
            "access_password": "custom_password_123",
            "session_timeout": 7200,
        },
        "pricing": {
            "currency_symbol": "$",
            "reference_rates": {
                "default": 0.005,
                "gpt-4o": 0.03,
            },
        },
    }
    cfg = parse_plugin_config(custom)
    assert cfg.tracker.enable is False
    assert cfg.tracker.record_streaming is False
    assert cfg.tracker.record_embedding is False
    assert cfg.tracker.estimate_when_missing is False
    assert cfg.webui.port == 6188
    assert cfg.webui.access_password == "custom_password_123"
    assert cfg.webui.session_timeout == 7200
    assert cfg.pricing.currency_symbol == "$"
    assert cfg.pricing.reference_rates["gpt-4o"] == 0.03
