<!--DISCLAIMER v1.0 -->

# SecondBrainSearch

Privacy-first local semantic search desktop application.

## Quick start

1. Create and activate a Python 3.10+ virtual environment:

   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. Install development dependencies:

   ```powershell
   pip install -r requirements-dev.txt
   ```

3. Run the smoke entry point:

   ```powershell
   python -m second_brain.main
   ```

4. Run the test suite:

   ```powershell
   pytest
   ```

5. Run lint checks:

   ```powershell
   ruff check .
   ruff format --check .
   ```

## Project layout

- `second_brain/` — Application package.
- `second_brain/ui/` — PyQt6 UI (must not import storage directly).
- `second_brain/core/` — Services and workers (must not import UI).
- `tests/` — pytest test pyramid: unit, integration, ui, e2e.
- `assets/` — Model assets (`all-MiniLM-L6-v2.onnx`, `tokenizer.json`).

## Architecture direction

```text
UI (PyQt6) -> Controller / Services -> Workers -> Storage (DuckDB)
```

The dependency direction is enforced by `tests/test_architecture_direction.py`.
