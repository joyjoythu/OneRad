---
name: radiomics-workflow
description: Workflow guidance for radiomics discovery, clinical matching, feature extraction, modeling, and reporting. Apply on every main agent model call.
---

# Radiomics Workflow

Reason about a radiomics study as a traceable sequence:

0. When asked to start the analysis, first survey the project with `dispatch_subagent(mode="explore")`: fan out independent read-only subtasks covering stages 1-4 (discovery candidates, pairing status, clinical table structure, extraction parameters) and reconcile their conclusions before touching any write or extraction step.
1. Discover image and segmentation candidates and verify patient-level pairing.
2. Inspect the clinical table; identify the patient ID, binary outcome, and requested covariates.
3. Reconcile identifiers and report unmatched or ambiguous cases before analysis.
4. Review image/mask quality and extraction parameters.
5. Extract reproducible radiomic features with the project YAML configuration.
6. Run the configured feature selection and cross-validated model analysis.
7. Interpret performance, calibration, decision curves, limitations, and generated artifacts without overstating evidence.

Prefer the dedicated discovery, extraction, and analysis tools for these stages. Do not skip a failed prerequisite or manufacture missing measurements. When reusing existing outputs, verify their paths and relevance to the current cohort first.
