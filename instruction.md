# Restore the missing production layout

A display-board job was handed off after the layout plug-in that produced the archived proofs became unavailable. The base document, revision history, panel controls, proof-run records, registration marks, proxy manifests, and several earlier proof exports are preserved in `/app/data`. Reconstruct the missing final state at revision `rv11` and write it to `/app/output/final_layout.json`.

The source files are:

- `/app/data/sheet.json`
- `/app/data/base_layout.csv`
- `/app/data/assets.csv`
- `/app/data/anchors.csv`
- `/app/data/edit_history.csv`
- `/app/data/panels.csv`
- `/app/data/panel_bindings.csv`
- `/app/data/panel_events.csv`
- `/app/data/revision_log.csv`
- `/app/data/production_runs.csv`
- `/app/data/registration_marks.csv`
- `/app/data/proxy_assets.csv`
- `/app/data/proof_observations.csv`

Layout dimensions are millimetres with a top-left origin. `base_layout.csv` is the `rv00` viewer-facing trim state. Panel `nudge` operands are millimetres and panel `scale` operands are unitless. Archived proof positions and sizes are in each production run's measured coordinate system; registration records preserve the corresponding nominal plate marks. Back-side nominal proof positions are plate-facing. Proof rows use run-local slot labels rather than persistent frame IDs. Archived crop coordinates are in the proxy pixels used by that run, while the required output crop coordinates are source-image pixels.

The output must be a JSON object with `revision` equal to `rv11` and a `placements` array containing exactly one entry for every frame in `base_layout.csv`. Array order is not significant. Each placement must contain:

- `frame_id`
- `asset_id`
- `x_mm`
- `y_mm`
- `width_mm`
- `height_mm`
- `crop_left_px`
- `crop_top_px`
- `crop_right_px`
- `crop_bottom_px`

`frame_id` and `asset_id` are JSON strings and must match the recovered final state. The eight geometry and crop fields are JSON numbers. Geometry is reported in viewer-facing trim coordinates. Millimetre values are accepted within `0.026 mm`; crop coordinates are accepted within `0.6 px`.

You have 7200 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
