---
name: radiomics-workflow
description: Workflow guidance for radiomics discovery, parameter confirmation, feature extraction, clinical matching, modeling, and reporting. Apply on every main agent model call.
---

# Radiomics Workflow

Reason about a radiomics study as a traceable sequence:

0. When asked to start the analysis, re-analyze, or re-execute the workflow, first survey the project with `dispatch_subagent(mode="explore")`: fan out independent read-only subtasks covering discovery candidates, pairing status, extraction parameters, and clinical table structure, and reconcile their conclusions before touching any write or extraction step. This applies equally to first-time and repeat analyses — only exploration reveals what already exists and what has changed.
1. Discover image and segmentation candidates and verify patient-level pairing.
2. Confirm extraction parameters before extracting. Feature extraction depends only on images, masks, and the parameter YAML — it does not need clinical data.
   - Run `inspect_image_spacing` on the confirmed pairs and compare the measured spacing distribution with the YAML's current `resampledPixelSpacing`.
   - Always ask the user whether to adjust `resampledPixelSpacing`, reporting the current value, the measured distribution, and the suggested value. Never change it on your own.
   - If the user wants a different value, apply it with `update_yaml` on the project YAML before extraction. Changing the YAML invalidates cached h5 results, so affected cases re-extract automatically.
3. Extract reproducible radiomic features with the project YAML configuration.
   - Feature extraction MUST go through the built-in `extract_radiomics_features` tool. NEVER use `execute_python_script` to extract features yourself (e.g. calling pyradiomics directly or parsing h5 caches) — scripted extraction bypasses the cache, resume, and failure tracking built into the dedicated tool.
   - Check `existing_features` from the pairing discovery first. If `complete`, always ask the user with `ask_user_choice` whether to re-extract (and why) or to proceed to the analysis on the existing features — never start extraction on your own. If `partial`, continue extraction for the remaining cases (h5 cache resume) without asking.
4. Inspect the clinical table after extraction and before analysis; identify the patient ID, binary outcome, and requested covariates. Reconcile identifiers and report unmatched or ambiguous cases before analysis.
5. Run the configured feature selection and cross-validated model analysis.
   - Before calling `run_radiomics_analysis`, ALWAYS ask the user with `ask_user_choice` whether to adjust the analysis parameters, showing the values that will be used: CV folds (`n_splits`, default 5), max LASSO features (`max_lasso_features`, default 100), random seed (`random_state`, default 42), and the resolved covariates. If the user wants changes, collect the new values and pass them via the tool parameters; otherwise call it with defaults. Never skip this question.
   - Each run writes `analysis_params.json` (parameter snapshot) and `run_analysis.py` (rerun script) into the output directory — mention them to the user as the reproduction record.
   - If the clinical table has Chinese column names (e.g. 年龄、性别), they are automatically translated to English (Age、Gender…) before modeling so SHAP plots and reports render correctly. Tell the user this happened and show the original→English mapping (also saved as `covariate_name_mapping.csv` in the output directory); reports show translated covariates as `Age（年龄）`.
   - After the analysis succeeds and the reports are generated, call `interpret_analysis_results` (no parameters) once to append the LLM-generated Chinese interpretation to report.md / report.docx, and tell the user the reports have been updated. When the user later asks to "重新解读/再解读一次", call it again.
6. Interpret performance, calibration, decision curves, limitations, and generated artifacts without overstating evidence.

Prefer the dedicated discovery, extraction, and analysis tools for these stages. Do not skip a failed prerequisite or manufacture missing measurements. When reusing existing outputs, verify their paths and relevance to the current cohort first.

## Progress reporting (update_todo_list)

When asked to start, re-analyze, re-execute, or continue any multi-stage task (including the full analysis workflow), first call `update_todo_list` to create one step per macro stage (0–6 above), then submit the full updated list each time a stage is entered or completed, so the side panel reflects real progress. For re-analysis, inspect existing outputs first and mark already-completed stages accordingly.

Do not redo finished work: if the survey finds usable existing outputs, mark the corresponding stages `completed` and start `in_progress` from the actual entry point. Feature extraction resumes per-case from h5 cache — when only part of the cohort is extracted, keep that stage `in_progress` and continue with the remaining cases rather than restarting.
