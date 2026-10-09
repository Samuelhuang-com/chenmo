"""六爻排盤引擎（問爻用）。純規則、不連網、可完全測試。

    from app.services.liuyao import build_chart
    chart = build_chart([7, 8, 9, 7, 6, 8], datetime(...))   # 初爻→上爻
"""
from .chart import Chart, Line, build_chart  # noqa: F401
