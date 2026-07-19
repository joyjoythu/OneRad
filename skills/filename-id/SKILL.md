---
name: filename-id
description: Infer a patient-ID regular expression from medical image and mask filename samples.
---

# Filename Patient-ID Inference

Infer a Python regular expression whose full match (`group(0)`) extracts the patient ID shared by image and mask filenames.

Return only this JSON shape:

```json
{"pattern": "regular expression", "explanation": "brief rationale"}
```

The pattern should exclude modality, sequence, channel, mask, segmentation, ROI, and extension suffixes. Generalize across the supplied samples without capturing unrelated digits. Escape the expression correctly for JSON and keep the explanation concise. Do not add Markdown fences or extra prose.
