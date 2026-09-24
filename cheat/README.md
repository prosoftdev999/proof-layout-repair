These scripts are deliberate reviewer-side near misses. They are not part of the agent environment and are never called by the verifier.

- `carry-forward.py` reuses the last archived document state instead of replaying the missing tail.
- `contain-fit.py` uses a fit-inside image rule.
- `center-anchor.py` ignores focal positions.
- `no-clamp.py` omits edge clamping.
- `front-anchor.py` applies the front-side anchor convention to both sides.
- `coarse-quantization.py` rounds export geometry to 0.10 mm.
- `retain-focus.py` keeps a frame-local focus override after an asset relink.
- `panel-origin.py` scales panel content around the sheet origin rather than the recorded panel pivot.
- `scaled-nudges.py` treats panel nudges as panel-local distances and scales them.
- `fixed-inset.py` leaves frame insets unscaled when a panel is scaled.
- `no-panels.py` ignores the panel-control history entirely.

Each script is exercised against the sealed expected artifact during author validation and must score 0.
