# -*- coding: utf-8 -*-
"""desk.tech_score must import and build without streamlit/plotly (daily_update path)."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tech_score_imports_without_streamlit_or_plotly():
    code = textwrap.dedent(
        """
        import sys
        class _Block:
            def find_spec(self, name, path=None, target=None):
                if name.split('.')[0] in ('streamlit', 'plotly'):
                    raise ImportError('blocked ' + name)
                return None
        sys.meta_path.insert(0, _Block())
        from desk.tech_score import write_tech_score_snapshot, build_tech_score_table, _kline_pattern
        from desk.local_bars import load_local_bars, load_carry_gaps
        assert 'streamlit' not in sys.modules and 'plotly' not in sys.modules
        print('ok')
        """
    )
    res = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert res.returncode == 0, res.stderr
    assert "ok" in res.stdout


def test_panel_reexports_build_logic():
    # Backward-compat: UI module still exposes the moved names (needs desk deps).
    import pytest

    pytest.importorskip("streamlit")
    from desk import tech_score, tech_score_panel

    assert tech_score_panel.write_tech_score_snapshot is tech_score.write_tech_score_snapshot
    assert tech_score_panel._kline_pattern is tech_score._kline_pattern
