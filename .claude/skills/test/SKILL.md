---
name: test
description: Run the existing MCP test suite and report results — pass/fail, failure details. Read-only: does not write, edit, or fix any code, and does not scaffold new tests. Use when the user asks to run tests, check if the suite passes, or verify a claim against the real test results. For writing code or fixing failures, use the dev skill instead.
---

This skill runs the existing automated test suite and reports what
actually happened. It never edits, fixes, or writes code, and never
creates or scaffolds new test files — if a failure needs a code change or
new coverage, report it and hand off to the dev skill instead of touching
code yourself.

## Running the suite

Tests live in `MCP/tests/` as `unittest.TestCase` classes and import
modules relative to `MCP/` (e.g. `from web.app import create_server`,
`from modules.data_trust import ...`), so run them from that directory:

```bash
cd MCP
python -m unittest discover -s tests -p "test_*.py" -v
```

If `pytest` is available in the environment it can run the same
unittest-style tests and gives more compact output:

```bash
cd MCP
python -m pytest tests/ -v
```

To run a single file or test during investigation:

```bash
cd MCP
python -m unittest tests.test_data_trust -v
python -m pytest tests/test_data_trust.py::TestDataTrustRulePack1::test_name -v
```

## Reporting results

- Report the real pass/fail counts and, for every failure, the actual
  assertion error or traceback — not a paraphrase.
- Never report a suite as "passing" without having actually run it in
  this turn.
- Never treat a written "N/N tests passed" claim (in a PR description,
  task summary, or elsewhere) as fact — re-run the suite yourself and
  report what you observed.
- If tests fail to even collect/import (missing dependency, path issue),
  report that as its own finding — it means the suite didn't run, not
  that it passed.
- Stop at reporting. If the user wants failures fixed or new tests
  written, say so explicitly and point them to the dev skill rather than
  making the change yourself.
