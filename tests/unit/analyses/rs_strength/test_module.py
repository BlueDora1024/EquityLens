from __future__ import annotations

import inspect

from stock_toolbox.analyses.rs_strength.module import RSStrengthModule


def test_rs_module_declares_provider_independent_requirements() -> None:
    module = RSStrengthModule()

    assert module.descriptor.analysis_id == "rs_strength"
    assert module.descriptor.display_name == "RS 强度"
    assert module.descriptor.requirements.daily_bars is True
    assert module.descriptor.requirements.quant_series is True
    assert module.descriptor.requirements.trading_calendar is True
    assert "longbridge" not in inspect.getsource(type(module)).lower()
