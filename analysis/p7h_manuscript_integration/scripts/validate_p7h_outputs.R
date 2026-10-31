#!/usr/bin/env Rscript

# Standard-library-style focused validation for the P7H package. This is
# deliberately independent of pytest/testthat and performs no model fitting.
options(stringsAsFactors = FALSE, scipen = 999)
args <- commandArgs(trailingOnly = TRUE)
arg_value <- function(flag, default = NULL) {
  i <- match(flag, args)
  if (is.na(i) || i == length(args)) return(default)
  args[[i + 1L]]
}
repo_root <- normalizePath(arg_value("--repo-root", getwd()), mustWork = TRUE)
abs_path <- function(x) file.path(repo_root, x)
stopf <- function(...) stop(sprintf(...), call. = FALSE)
if (!requireNamespace("jsonlite", quietly = TRUE)) stopf("jsonlite is required")
if (!requireNamespace("digest", quietly = TRUE)) stopf("digest is required")
sha256 <- function(path) tolower(digest::digest(file = path, algo = "sha256"))
read_json <- function(path) jsonlite::fromJSON(abs_path(path), simplifyVector = FALSE)
required <- c(
  "analysis/p7h_manuscript_integration/p7h_prespecification.md",
  "analysis/p7h_manuscript_integration/p7h_manuscript_integration_report.md",
  "analysis/p7h_manuscript_integration/results/p7h_decision.json",
  "analysis/p7h_manuscript_integration/results/p7h_source_registry.csv",
  "analysis/p7h_manuscript_integration/results/p7h_provenance_manifest.json",
  "analysis/p7h_manuscript_integration/results/p7h_numerical_traceability.csv",
  "analysis/p7h_manuscript_integration/results/p7h_publication_artifact_registry.csv",
  "analysis/p7_publication/results/claim_registry.csv",
  "analysis/p7_publication/results/methods_summary.md",
  "analysis/p7_publication/results/results_draft.md",
  "analysis/p7_publication/results/results_synthesis.md",
  "analysis/p7_publication/results/limitations_draft.md",
  "analysis/p7_publication/results/discussion_outline.md",
  "analysis/p7_publication/results/publication_reviewer_checklist.md",
  "analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.svg",
  "analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.png",
  "analysis/p7h_manuscript_integration/figures/archive/figure_06_predictor_associations_p7f_superseded.svg",
  "analysis/p7h_manuscript_integration/figures/archive/figure_06_predictor_associations_p7f_superseded.png")
missing <- required[!file.exists(vapply(required, abs_path, character(1L)))]
if (length(missing)) stopf("Missing P7H output(s): %s", paste(missing, collapse = ", "))

model_path <- abs_path("analysis/structured_a3_evaluation/results/final_a3_model.json")
if (!identical(sha256(model_path), "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e")) {
  stopf("Frozen model hash mismatch")
}
p7g_manifest <- read_json("analysis/p7g_manuscript_evidence/results/p7g_reproducibility_manifest.json")
for (a in p7g_manifest$artifacts) {
  if (!identical(sha256(abs_path(a$path)), a$sha256)) stopf("P7G hash mismatch: %s", a$path)
}
p7g_decision <- read_json("analysis/p7g_manuscript_evidence/results/decision.json")
if (!identical(p7g_decision$decision, "P7G_MANUSCRIPT_EVIDENCE_COMPLETE_WITH_LIMITATIONS") ||
    !isTRUE(p7g_decision$no_model_fitting)) stopf("P7G decision contract failed")

decision <- read_json("analysis/p7h_manuscript_integration/results/p7h_decision.json")
if (!identical(decision$decision, "P7H_MANUSCRIPT_PACKAGE_READY_WITH_LIMITATIONS") ||
    !isTRUE(decision$no_model_fitting) || !isTRUE(decision$p7g_source_hashes_verified)) {
  stopf("P7H decision contract failed")
}
claims <- read.csv(abs_path("analysis/p7_publication/results/claim_registry.csv"),
                   stringsAsFactors = FALSE, check.names = FALSE)
if (nrow(claims) != 12L || !all(c("I", "J", "K", "L") %in% claims$claim_id)) {
  stopf("P7/P7H claim registry is incomplete")
}
assoc <- read.csv(abs_path("analysis/p7h_manuscript_integration/results/predictor_standardized_associations.csv"),
                  stringsAsFactors = FALSE, check.names = FALSE)
if (nrow(assoc) != 68L || length(unique(assoc$predictor)) != 34L ||
    !all(c("occurrence", "positive_count") %in% unique(assoc$component)) ||
    !all(nzchar(assoc$category))) stopf("Standardized association output is incomplete")
trace <- read.csv(abs_path("analysis/p7h_manuscript_integration/results/p7h_numerical_traceability.csv"),
                  stringsAsFactors = FALSE, check.names = FALSE)
if (nrow(trace) != 89L || any(!nzchar(trace$source_artifact))) stopf("P7H traceability output is incomplete")
if (!identical(sha256(abs_path("analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.svg")),
               sha256(abs_path("analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.svg")))) {
  stopf("Active P7F Figure 6 does not match the P7H standardized replacement")
}
text <- paste(readLines(abs_path("analysis/p7_publication/results/limitations_draft.md"), warn = FALSE), collapse = " ")
for (term in c("Residual", "observation-process", "coefficient-bootstrap", "spatial holdout", "E0_LAST_AVAILABLE")) {
  if (!grepl(tolower(term), tolower(text), fixed = TRUE)) stopf("Required limitation missing: %s", term)
}
p7h_manifest <- read_json("analysis/p7h_manuscript_integration/results/p7h_provenance_manifest.json")
for (nm in names(p7h_manifest$output_hashes_excluding_manifest)) {
  if (!file.exists(abs_path(nm))) stopf("P7H manifest output missing: %s", nm)
  if (!identical(sha256(abs_path(nm)), p7h_manifest$output_hashes_excluding_manifest[[nm]])) {
    stopf("P7H output hash mismatch: %s", nm)
  }
}
cat("P7H_OUTPUTS_VALIDATED\n")
cat(sprintf("p7g_artifacts=%d\n", length(p7g_manifest$artifacts)))
cat(sprintf("claims=%d\n", nrow(claims)))
cat(sprintf("association_rows=%d\n", nrow(assoc)))
cat(sprintf("trace_rows=%d\n", nrow(trace)))
cat("no_model_fitting=true\n")
