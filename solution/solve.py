#!/usr/bin/env python3
"""Recover the missing layout state from the archived production evidence."""

import csv
import json
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DATA = Path("/app/data")
OUTPUT = Path("/app/output/final_layout.json")


def read_csv(name):
    with (DATA / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def quantize(value, step):
    scaled = Decimal(str(value)) / Decimal(str(step))
    return float(scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal(str(step)))


def bounded(value, low, high):
    return min(max(value, low), high)


def apply_frame_edit(frame, edit, reset_focus):
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
    else:
        raise ValueError(f"unsupported frame edit: {action}")


def apply_panel_event(state, panel, event, pivoted, nudge_scaled):
    action = event["action"]
    if action == "nudge":
        dx = float(event["p1"])
        dy = float(event["p2"])
        if nudge_scaled:
            dx *= state["scale"]
            dy *= state["scale"]
        state["tx"] += dx
        state["ty"] += dy
    elif action == "scale":
        factor = float(event["p1"])
        if pivoted:
            pivot_x = float(panel["pivot_x_mm"])
            pivot_y = float(panel["pivot_y_mm"])
        else:
            pivot_x = 0.0
            pivot_y = 0.0
        state["tx"] = pivot_x + factor * (state["tx"] - pivot_x)
        state["ty"] = pivot_y + factor * (state["ty"] - pivot_y)
        state["scale"] *= factor
    else:
        raise ValueError(f"unsupported panel event: {action}")


def render_frame(frame, panel_state, scale_inset):
    scale = panel_state["scale"]
    rendered = dict(frame)
    rendered["x_mm"] = scale * float(frame["x_mm"]) + panel_state["tx"]
    rendered["y_mm"] = scale * float(frame["y_mm"]) + panel_state["ty"]
    rendered["w_mm"] = scale * float(frame["w_mm"])
    rendered["h_mm"] = scale * float(frame["h_mm"])
    rendered["inset_mm"] = scale * float(frame["inset_mm"]) if scale_inset else float(frame["inset_mm"])
    return rendered


def compute_placement(frame, asset, anchor, sheet_width, mechanism):
    x = float(frame["x_mm"])
    y = float(frame["y_mm"])
    w = float(frame["w_mm"])
    h = float(frame["h_mm"])
    inset = float(frame["inset_mm"])

    content_x = x + inset
    content_y = y + inset
    content_w = w - 2 * inset
    content_h = h - 2 * inset

    scale_x = content_w / int(asset["width_px"])
    scale_y = content_h / int(asset["height_px"])
    scale = max(scale_x, scale_y) if mechanism["scale_mode"] == "cover" else min(scale_x, scale_y)
    placed_w = int(asset["width_px"]) * scale
    placed_h = int(asset["height_px"]) * scale

    if mechanism["anchor_mode"] == "focal":
        focus_x = float(frame["focus_x"]) if frame["focus_x"] != "" else float(asset["focal_x"])
        focus_y = float(frame["focus_y"]) if frame["focus_y"] != "" else float(asset["focal_y"])
    else:
        focus_x = 0.5
        focus_y = 0.5

    anchor_x = float(anchor["anchor_x"])
    anchor_y = float(anchor["anchor_y"])
    if frame["side"] == "back" and mechanism["back_reflect"]:
        anchor_x = 1.0 - anchor_x

    target_x = content_x + anchor_x * content_w
    target_y = content_y + anchor_y * content_h
    placed_x = target_x - focus_x * placed_w
    placed_y = target_y - focus_y * placed_h

    if mechanism["clamp"] and mechanism["scale_mode"] == "cover":
        placed_x = bounded(placed_x, content_x + content_w - placed_w, content_x)
        placed_y = bounded(placed_y, content_y + content_h - placed_h, content_y)

    crop_left = (content_x - placed_x) / scale
    crop_top = (content_y - placed_y) / scale
    crop_right = (content_x + content_w - placed_x) / scale
    crop_bottom = (content_y + content_h - placed_y) / scale

    step = mechanism["quantum"]
    view_x = quantize(placed_x, step)
    view_y = quantize(placed_y, step)
    out_w = quantize(placed_w, step)
    out_h = quantize(placed_h, step)
    proof_x = sheet_width - (view_x + out_w) if frame["side"] == "back" else view_x

    return {
        "view_x": view_x,
        "view_y": view_y,
        "proof_x": quantize(proof_x, step),
        "proof_y": view_y,
        "width": out_w,
        "height": out_h,
        "crop_left": round(crop_left, 2),
        "crop_top": round(crop_top, 2),
        "crop_right": round(crop_right, 2),
        "crop_bottom": round(crop_bottom, 2),
    }


def revision_for_run(run, revision_log):
    started = datetime.fromisoformat(run["started_at"])
    candidates = [row for row in revision_log if datetime.fromisoformat(row["committed_at"]) <= started]
    if not candidates:
        raise RuntimeError(f"run {run['run_id']} predates the revision log")
    return max(candidates, key=lambda row: row["committed_at"])["revision"]


def fit_axis(rows, nominal_key, measured_key):
    x = [float(row[nominal_key]) for row in rows]
    y = [float(row[measured_key]) for row in rows]
    x_bar = sum(x) / len(x)
    y_bar = sum(y) / len(y)
    denom = sum((value - x_bar) ** 2 for value in x)
    slope = sum((a - x_bar) * (b - y_bar) for a, b in zip(x, y)) / denom
    offset = y_bar - slope * x_bar
    return slope, offset


def fit_run_calibrations(registration_rows):
    grouped = {}
    for row in registration_rows:
        grouped.setdefault(row["run_id"], []).append(row)
    result = {}
    for run_id, rows in grouped.items():
        sx, tx = fit_axis(rows, "nominal_x_mm", "measured_x_mm")
        sy, ty = fit_axis(rows, "nominal_y_mm", "measured_y_mm")
        result[run_id] = (sx, sy, tx, ty)
    return result


def build_states(base_frames, frame_edits, panel_events, panels, observed_revisions, mechanism):
    frames = {row["frame_id"]: deepcopy(row) for row in base_frames}
    panel_state = {panel_id: {"scale": 1.0, "tx": 0.0, "ty": 0.0} for panel_id in panels}
    states = {"rv00": (deepcopy(frames), deepcopy(panel_state))}

    edits_by_revision = {}
    for edit in frame_edits:
        edits_by_revision.setdefault(edit["revision"], []).append(edit)
    panel_by_revision = {}
    for event in panel_events:
        panel_by_revision.setdefault(event["revision"], []).append(event)

    final_revision = max(
        [int(row["revision"][2:]) for row in frame_edits] + [int(row["revision"][2:]) for row in panel_events]
    )
    for index in range(1, final_revision + 1):
        revision = f"rv{index:02d}"
        for edit in edits_by_revision.get(revision, []):
            apply_frame_edit(frames[edit["frame_id"]], edit, mechanism["asset_resets_focus"])
        for event in panel_by_revision.get(revision, []):
            apply_panel_event(
                panel_state[event["panel_id"]],
                panels[event["panel_id"]],
                event,
                mechanism["panel_pivoted"],
                mechanism["nudge_scaled"],
            )
        if revision in observed_revisions:
            states[revision] = (deepcopy(frames), deepcopy(panel_state))
    return states, (frames, panel_state)


def minimum_assignment_cost(costs):
    # Seven proof slots are small enough that a bitmask dynamic program is both
    # clearer and faster than pulling in a numerical optimization dependency.
    n = len(costs)
    best = {0: 0.0}
    for row in range(n):
        next_best = {}
        for mask, value in best.items():
            for column in range(n):
                bit = 1 << column
                if mask & bit:
                    continue
                new_mask = mask | bit
                candidate = value + costs[row][column]
                if candidate < next_best.get(new_mask, float("inf")):
                    next_best[new_mask] = candidate
        best = next_best
    return best[(1 << n) - 1]


def score_pair(observed, predicted, asset, proxy, calibration):
    sx, sy, tx, ty = calibration
    expected = {
        "proof_x_mm": sx * predicted["proof_x"] + tx,
        "proof_y_mm": sy * predicted["proof_y"] + ty,
        "placed_w_mm": sx * predicted["width"],
        "placed_h_mm": sy * predicted["height"],
    }
    error = 0.0
    for key in ("proof_x_mm", "proof_y_mm", "placed_w_mm", "placed_h_mm"):
        # Normalizing to 0.05 mm keeps geometry and crop terms on comparable scales.
        delta = (float(observed[key]) - expected[key]) / 0.05
        error += delta * delta

    proxy_x = int(proxy["proxy_width_px"]) / int(asset["width_px"])
    proxy_y = int(proxy["proxy_height_px"]) / int(asset["height_px"])
    for source, key, factor in (
        ("crop_left_px", "crop_left", proxy_x),
        ("crop_top_px", "crop_top", proxy_y),
        ("crop_right_px", "crop_right", proxy_x),
        ("crop_bottom_px", "crop_bottom", proxy_y),
    ):
        delta = (float(observed[source]) - predicted[key] * factor) / 0.5
        error += delta * delta
    return error


def score_mechanism(mechanism, inputs):
    observed_revisions = set(inputs["run_revisions"].values())
    states, _ = build_states(
        inputs["base_frames"],
        inputs["frame_edits"],
        inputs["panel_events"],
        inputs["panels"],
        observed_revisions,
        mechanism,
    )

    total = 0.0
    for run_id, observed_rows in inputs["observations"].items():
        revision = inputs["run_revisions"][run_id]
        frames, panel_state = states[revision]
        predictions = []
        for frame_id in sorted(frames):
            frame = frames[frame_id]
            panel_id = inputs["bindings"][frame_id]
            rendered = render_frame(frame, panel_state[panel_id], mechanism["scale_inset"])
            asset = inputs["assets"][rendered["asset_id"]]
            placement = compute_placement(
                rendered,
                asset,
                inputs["anchors"][rendered["anchor_id"]],
                inputs["sheet_width"],
                mechanism,
            )
            predictions.append((placement, asset, inputs["proxies"][(run_id, rendered["asset_id"])]))

        costs = []
        for observed in observed_rows:
            row_costs = []
            for placement, asset, proxy in predictions:
                row_costs.append(score_pair(observed, placement, asset, proxy, inputs["calibrations"][run_id]))
            costs.append(row_costs)
        total += minimum_assignment_cost(costs)
    return total


def load_inputs():
    sheet = json.loads((DATA / "sheet.json").read_text())
    revision_log = read_csv("revision_log.csv")
    runs = read_csv("production_runs.csv")
    run_revisions = {row["run_id"]: revision_for_run(row, revision_log) for row in runs}

    observations = {}
    for row in read_csv("proof_observations.csv"):
        observations.setdefault(row["run_id"], []).append(row)

    return {
        "sheet": sheet,
        "sheet_width": float(sheet["width_mm"]),
        "base_frames": read_csv("base_layout.csv"),
        "frame_edits": read_csv("edit_history.csv"),
        "panel_events": read_csv("panel_events.csv"),
        "panels": {row["panel_id"]: row for row in read_csv("panels.csv")},
        "bindings": {row["frame_id"]: row["panel_id"] for row in read_csv("panel_bindings.csv")},
        "assets": {row["asset_id"]: row for row in read_csv("assets.csv")},
        "anchors": {row["anchor_id"]: row for row in read_csv("anchors.csv")},
        "proxies": {(row["run_id"], row["asset_id"]): row for row in read_csv("proxy_assets.csv")},
        "observations": observations,
        "run_revisions": run_revisions,
        "calibrations": fit_run_calibrations(read_csv("registration_marks.csv")),
    }


def candidate_mechanisms():
    for scale_mode in ("cover", "contain"):
        for anchor_mode in ("focal", "center"):
            for clamp in (True, False):
                for back_reflect in (True, False):
                    for quantum in (0.05, 0.10):
                        for reset_focus in (True, False):
                            for pivoted in (True, False):
                                for nudge_scaled in (True, False):
                                    for scale_inset in (True, False):
                                        yield {
                                            "scale_mode": scale_mode,
                                            "anchor_mode": anchor_mode,
                                            "clamp": clamp,
                                            "back_reflect": back_reflect,
                                            "quantum": quantum,
                                            "asset_resets_focus": reset_focus,
                                            "panel_pivoted": pivoted,
                                            "nudge_scaled": nudge_scaled,
                                            "scale_inset": scale_inset,
                                        }


def main():
    inputs = load_inputs()
    candidates = [(score_mechanism(mechanism, inputs), mechanism) for mechanism in candidate_mechanisms()]
    candidates.sort(key=lambda item: item[0])
    best_score, best = candidates[0]
    if candidates[1][0] <= best_score * 1.000001 + 0.01:
        raise RuntimeError("archived proofs do not identify one production behavior")

    observed_revisions = set(inputs["run_revisions"].values())
    _, (frames, panel_state) = build_states(
        inputs["base_frames"],
        inputs["frame_edits"],
        inputs["panel_events"],
        inputs["panels"],
        observed_revisions,
        best,
    )

    placements = []
    for frame_id in sorted(frames):
        frame = frames[frame_id]
        panel_id = inputs["bindings"][frame_id]
        rendered = render_frame(frame, panel_state[panel_id], best["scale_inset"])
        placed = compute_placement(
            rendered,
            inputs["assets"][rendered["asset_id"]],
            inputs["anchors"][rendered["anchor_id"]],
            inputs["sheet_width"],
            best,
        )
        placements.append({
            "frame_id": frame_id,
            "asset_id": rendered["asset_id"],
            "x_mm": round(placed["view_x"], 2),
            "y_mm": round(placed["view_y"], 2),
            "width_mm": round(placed["width"], 2),
            "height_mm": round(placed["height"], 2),
            "crop_left_px": placed["crop_left"],
            "crop_top_px": placed["crop_top"],
            "crop_right_px": placed["crop_right"],
            "crop_bottom_px": placed["crop_bottom"],
        })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"revision": inputs["sheet"]["required_revision"], "placements": placements}, indent=2) + "\n")


if __name__ == "__main__":
    main()
