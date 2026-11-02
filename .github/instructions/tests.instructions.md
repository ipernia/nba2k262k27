---
description: "Use when creating or modifying tests for this Python project."
applyTo: "tests/**/*.py"
---

# Test guidelines

- Use pytest and follow the existing test module and fixture patterns.
- Keep tests deterministic: fake NBA endpoints and HTTP responses, and use `tmp_path` for files.
- Do not make live network requests in unit tests.
- Cover successful output, invalid input, and relevant failure or retry behavior.
- Run the focused tests first, then the full suite when changes affect shared behavior.
