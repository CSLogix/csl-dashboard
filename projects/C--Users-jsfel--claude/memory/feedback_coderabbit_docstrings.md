---
name: CodeRabbit docstrings break builds
description: CodeRabbit auto-generated docstrings introduce syntax errors — missing JSDoc closers and Python indentation issues
type: feedback
---

CodeRabbit's auto-generated docstrings have caused build failures twice during PR #18 deploy:
1. `MarketBenchmarkCard.jsx` — JSDoc comment missing closing `*/` before `export default`
2. `directory.py` — docstring with excessive indentation (matched function signature indentation) causing `IndentationError`

**Why:** These errors only surface at build/deploy time, not during PR review, because CodeRabbit adds them in a way that passes linting but breaks parsers.

**How to apply:** After pulling PRs with CodeRabbit comments merged, always run `npm run build` locally before deploying. For Python files, do a quick syntax check (`python3 -c "import py_compile; py_compile.compile('file.py')"`) before SCP to server.
