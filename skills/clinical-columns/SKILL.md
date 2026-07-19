---
name: clinical-columns
description: Identify patient ID, binary outcome, and usable clinical feature columns from a clinical table summary.
---

# Clinical Column Identification

Analyze the supplied table metadata for a radiomics study and return only one JSON object with these keys:

```json
{"id_col": "...", "label_col": "...", "feature_cols": ["..."], "reasoning": "..."}
```

- Select an ID column that uniquely and stably identifies patients where possible.
- Select a binary 0/1 outcome column for `label_col`; do not treat identifiers or continuous measurements as outcomes.
- Exclude `id_col` and `label_col` from `feature_cols`.
- Include only plausible clinical predictors described by the supplied columns and task hint.
- Keep `reasoning` brief and grounded in names, types, uniqueness, missingness, and sample values.

Do not add prose outside the JSON object.
