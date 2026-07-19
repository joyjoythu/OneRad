---
name: file-operations
description: Generate a safe JSON plan for organizing files inside a OneRad project. Use for plan_file_operations calls.
---

# File Operation Planning

Convert the user's organization request into a JSON array of proposed operations. Output only the JSON array, with no Markdown fence or commentary.

Allowed actions are `move`, `copy`, `rename`, and `mkdir`. Never propose deletion. Keep every `source` and `target` relative to the project root; do not emit absolute paths or parent traversal.

Use this shape for every item:

```json
{"action": "move", "source": "relative/source", "target": "relative/target", "reason": "brief reason"}
```

Base the plan on the supplied directory snapshot. Avoid overwriting unrelated files, and prefer the smallest plan that satisfies the request. The application will validate the JSON and enforce the sandbox before anything can execute.
