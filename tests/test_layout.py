import json
import math
from pathlib import Path

ARTIFACT = Path("/app/output/final_layout.json")
EXPECTED = json.loads(Path("/tests/expected.json").read_text())
MM_TOL = 0.026
PX_TOL = 0.6
NUMERIC_FIELDS_MM = ("x_mm", "y_mm", "width_mm", "height_mm")
NUMERIC_FIELDS_PX = ("crop_left_px", "crop_top_px", "crop_right_px", "crop_bottom_px")
REQUIRED_FIELDS = {"frame_id", "asset_id", *NUMERIC_FIELDS_MM, *NUMERIC_FIELDS_PX}


def as_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AssertionError("numeric fields must be JSON numbers")
    value = float(value)
    assert math.isfinite(value), "numeric fields must be finite"
    return value


def keyed_placements(payload):
    assert isinstance(payload, dict), "top level must be an object"
    assert payload.get("revision") == EXPECTED["revision"], "wrong revision"
    rows = payload.get("placements")
    assert isinstance(rows, list), "placements must be an array"
    assert len(rows) == len(EXPECTED["placements"]), "wrong placement count"
    keyed = {}
    for row in rows:
        assert isinstance(row, dict), "each placement must be an object"
        assert REQUIRED_FIELDS.issubset(row), "placement is missing required fields"
        frame_id = row["frame_id"]
        assert isinstance(frame_id, str), "frame_id must be a string"
        assert frame_id not in keyed, "duplicate frame_id"
        keyed[frame_id] = row
    return keyed


def test_final_layout():
    assert ARTIFACT.exists(), "required artifact is missing"
    try:
        payload = json.loads(ARTIFACT.read_text())
    except Exception as exc:
        raise AssertionError(f"artifact is not valid JSON: {exc}") from exc

    actual = keyed_placements(payload)
    expected = {row["frame_id"]: row for row in EXPECTED["placements"]}
    assert set(actual) == set(expected), "frame set does not match"

    for frame_id, want in expected.items():
        got = actual[frame_id]
        assert got["asset_id"] == want["asset_id"], f"wrong asset for {frame_id}"
        for field in NUMERIC_FIELDS_MM:
            assert abs(as_number(got[field]) - float(want[field])) <= MM_TOL, f"{frame_id}.{field} outside tolerance"
        for field in NUMERIC_FIELDS_PX:
            assert abs(as_number(got[field]) - float(want[field])) <= PX_TOL, f"{frame_id}.{field} outside tolerance"
