# Archived Strategy Files

These files are kept for historical reference but are NOT loaded by the app.
They include `.deleted`, `.backup`, and internal helpers kept for debugging.

## Contents

- `*.deleted` — strategy files that were superseded or removed from active use
- `*.backup` — backup copies of strategy variants kept for reference
- `_run_v6.py`, `_safe_import.py` — internal helper scripts kept for debugging

## Why they are archived

Moving these out of the top-level `strategies/` directory ensures the strategy
loader/engine no longer picks them up as active strategies, while preserving
them for historical reference and debugging.
