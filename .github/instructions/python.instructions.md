---
description: "Use when creating or modifying Python source in this repository."
applyTo: "src/**/*.py"
---

# Python project guidelines

- Support Python 3.10 and newer; preserve compatibility with the declared minimum.
- Add type annotations and use the existing helpers and error classes.
- Keep formatting and linting compatible with Ruff (`ruff check` and `ruff format`).
- Keep NBA network calls behind the existing client boundaries, with bounded timeouts and retries.
- Report expected operational failures through the existing project error handling; do not silently substitute data.
