import csv
import json
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DATA = Path("/app/data")
OUT = Path("/app/output/final_layout.json")


def rows(name):
    with (DATA / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def q(value, step):
    scaled = Decimal(str(value)) / Decimal(str(step))
    return float(scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal(str(step)))


def clamp(value, low, high):
    return min(max(value, low), high)


def apply_frame(frame, edit, reset_focus=True):
    action = edit["action"]
    if action == "focus":
        frame["focus_x"] = float(edit["p1"])
        frame["focus_y"] = float(edit["p2"])
    elif action == "resize":
        frame["x_mm"] = float(edit["p1"])
        frame["y_mm"] = float(edit["p2"])
        frame["w_mm"] = float(edit["p3"])
        frame["h_mm"] = float(edit["p4"])
    elif action == "anchor":
        frame["anchor_id"] = edit["p1"]
    elif action == "asset":
        frame["asset_id"] = edit["p1"]
        if reset_focus:
            frame["focus_x"] = ""
            frame["focus_y"] = ""
    elif action == "inset":
        frame["inset_mm"] = float(edit["p1"])


def apply_panel(state, panel, event, pivoted=True, nudge_scaled=False):
    if event["action"] == "nudge":
        dx = float(event["p1"])
        dy = float(event["p2"])
        if nudge_scaled:
            dx *= state["scale"]
            dy *= state["scale"]
        state["tx"] += dx
        state["ty"] += dy
    elif event["action"] == "scale":
        factor = float(event["p1"])
        px = float(panel["pivot_x_mm"]) if pivoted else 0.0
        py = float(panel["pivot_y_mm"]) if pivoted else 0.0
        state["tx"] = px + factor * (state["tx"] - px)
        state["ty"] = py + factor * (state["ty"] - py)
        state["scale"] *= factor


def render(options, stop_revision="rv11", output_revision="rv11"):
    assets = {row["asset_id"]: row for row in rows("assets.csv")}
    anchors = {row["anchor_id"]: row for row in rows("anchors.csv")}
    panels = {row["panel_id"]: row for row in rows("panels.csv")}
    bindings = {row["frame_id"]: row["panel_id"] for row in rows("panel_bindings.csv")}
    frames = {row["frame_id"]: deepcopy(row) for row in rows("base_layout.csv")}
    panel_state = {panel_id: {"scale": 1.0, "tx": 0.0, "ty": 0.0} for panel_id in panels}

    frame_by_revision = {}
    for edit in rows("edit_history.csv"):
        frame_by_revision.setdefault(edit["revision"], []).append(edit)
    panel_by_revision = {}
    for event in rows("panel_events.csv"):
        panel_by_revision.setdefault(event["revision"], []).append(event)

    last = int(stop_revision[2:])
    for index in range(1, last + 1):
        revision = f"rv{index:02d}"
        for edit in frame_by_revision.get(revision, []):
            apply_frame(frames[edit["frame_id"]], edit, options.get("reset_focus", True))
        if not options.get("ignore_panels", False):
            for event in panel_by_revision.get(revision, []):
                apply_panel(
                    panel_state[event["panel_id"]], panels[event["panel_id"]], event,
                    options.get("panel_pivoted", True), options.get("nudge_scaled", False)
                )

    output = []
    for frame_id in sorted(frames):
        frame = dict(frames[frame_id])
        pstate = panel_state[bindings[frame_id]]
        scale_panel = pstate["scale"]
        frame["x_mm"] = scale_panel * float(frame["x_mm"]) + pstate["tx"]
        frame["y_mm"] = scale_panel * float(frame["y_mm"]) + pstate["ty"]
        frame["w_mm"] = scale_panel * float(frame["w_mm"])
        frame["h_mm"] = scale_panel * float(frame["h_mm"])
        frame["inset_mm"] = scale_panel * float(frame["inset_mm"]) if options.get("scale_inset", True) else float(frame["inset_mm"])

        asset = assets[frame["asset_id"]]
        anchor = anchors[frame["anchor_id"]]
        x = float(frame["x_mm"]); y = float(frame["y_mm"]); w = float(frame["w_mm"]); h = float(frame["h_mm"]); inset = float(frame["inset_mm"])
        cx = x + inset; cy = y + inset; cw = w - 2 * inset; ch = h - 2 * inset
        sx = cw / int(asset["width_px"]); sy = ch / int(asset["height_px"])
        image_scale = max(sx, sy) if options["scale"] == "cover" else min(sx, sy)
        placed_w = int(asset["width_px"]) * image_scale
        placed_h = int(asset["height_px"]) * image_scale

        if options["anchor"] == "focal":
            fx = float(frame["focus_x"]) if frame["focus_x"] != "" else float(asset["focal_x"])
            fy = float(frame["focus_y"]) if frame["focus_y"] != "" else float(asset["focal_y"])
        else:
            fx = fy = 0.5
        ax = float(anchor["anchor_x"]); ay = float(anchor["anchor_y"])
        if frame["side"] == "back" and options["back_reflect"]:
            ax = 1.0 - ax
        px = cx + ax * cw - fx * placed_w
        py = cy + ay * ch - fy * placed_h
        if options["clamp"] and options["scale"] == "cover":
            px = clamp(px, cx + cw - placed_w, cx)
            py = clamp(py, cy + ch - placed_h, cy)

        u0 = (cx - px) / image_scale; v0 = (cy - py) / image_scale
        u1 = (cx + cw - px) / image_scale; v1 = (cy + ch - py) / image_scale
        output.append({
            "frame_id": frame_id,
            "asset_id": frame["asset_id"],
            "x_mm": q(px, options["quantum"]), "y_mm": q(py, options["quantum"]),
            "width_mm": q(placed_w, options["quantum"]), "height_mm": q(placed_h, options["quantum"]),
            "crop_left_px": round(u0, 2), "crop_top_px": round(v0, 2),
            "crop_right_px": round(u1, 2), "crop_bottom_px": round(v1, 2),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"revision": output_revision, "placements": output}, indent=2) + "\n")
