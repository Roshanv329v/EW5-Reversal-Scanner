from __future__ import annotations

from core import prefs


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "filters.json"
    saved = {**prefs.default_prefs(), "time_frame": ["1D"], "search": "BAJ", "ratio": [0.618, None],
             "stat": "w4", "chart_groups": {"W5 targets": False}}
    prefs.save_prefs(path, saved)
    assert prefs.load_prefs(path) == saved


def test_missing_or_broken_file_gives_defaults(tmp_path):
    assert prefs.load_prefs(tmp_path / "nope.json") == prefs.default_prefs()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert prefs.load_prefs(bad) == prefs.default_prefs()


def test_ratio_range_fits_any_results_file():
    assert prefs.ratio_range([None, None], 0.1, 4.0) == (0.1, 4.0)
    assert prefs.ratio_range([0.618, None], 0.1, 4.0) == (0.618, 4.0)      # open top follows the file
    assert prefs.ratio_range([0.618, 9.0], 0.1, 4.0) == (0.618, 4.0)       # clamped
    assert prefs.ratio_range([5.0, 6.0], 0.1, 4.0) == (4.0, 4.0)
    assert prefs.ratio_pref((0.1, 4.0), 0.1, 4.0) == [None, None]
    assert prefs.ratio_pref((0.618, 4.0), 0.1, 4.0) == [0.618, None]


def test_legacy_ratio_key_and_extra_columns(tmp_path):
    old = tmp_path / "old.json"
    old.write_text('{"time_frame": ["4hr"], "w5_vs_w1": [0.5, null]}')
    loaded = prefs.load_prefs(old)
    assert loaded["time_frame"] == ["4hr"] and loaded["ratio"] == [0.5, None]
    cols = ("time_frame", "context")
    path = tmp_path / "ew3.json"
    prefs.save_prefs(path, {**prefs.default_prefs(cols), "context": ["AFTER_ABC"]}, cols)
    assert prefs.load_prefs(path, cols)["context"] == ["AFTER_ABC"]
    assert "reversal_side" not in prefs.load_prefs(path, cols)
