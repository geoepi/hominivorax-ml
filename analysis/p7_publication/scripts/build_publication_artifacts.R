#!/usr/bin/env Rscript

# P7 publication build: aggregation and provenance only. This script never
# fits, tunes, recalibrates, or changes a scientific model.
options(stringsAsFactors = FALSE, scipen = 999)

args <- commandArgs(trailingOnly = TRUE)
arg_value <- function(flag, default = NULL) {
  i <- match(flag, args)
  if (is.na(i) || i == length(args)) return(default)
  args[[i + 1L]]
}
repo_root <- normalizePath(arg_value("--repo-root", getwd()), mustWork = TRUE)
output_root <- normalizePath(file.path(repo_root,
                                       arg_value("--output-root", "analysis/p7_publication")),
                             mustWork = FALSE)
verify_only <- "--verify-only" %in% args

stopf <- function(...) stop(sprintf(...), call. = FALSE)
relpath_one <- function(path) {
  path <- normalizePath(path, winslash = "/", mustWork = FALSE)
  root <- normalizePath(repo_root, winslash = "/", mustWork = TRUE)
  prefix <- paste0(root, "/")
  if (startsWith(tolower(path), tolower(prefix))) return(substring(path, nchar(prefix) + 1L))
  path
}
relpath <- function(path) vapply(path, relpath_one, character(1L))
abs_path <- function(relative_path) file.path(repo_root, relative_path)
if (!requireNamespace("jsonlite", quietly = TRUE)) stopf("jsonlite is required")
if (!requireNamespace("digest", quietly = TRUE)) stopf("digest is required")

read_json <- function(relative_path) {
  path <- abs_path(relative_path)
  if (!file.exists(path)) stopf("Required JSON source is missing: %s", relative_path)
  jsonlite::fromJSON(path, simplifyVector = FALSE)
}
read_csv <- function(relative_path) {
  path <- abs_path(relative_path)
  if (!file.exists(path)) stopf("Required CSV source is missing: %s", relative_path)
  utils::read.csv(path, check.names = FALSE, stringsAsFactors = FALSE,
                  na.strings = c("", "NA"))
}
sha256_file <- function(path) {
  if (!file.exists(path)) stopf("Cannot hash missing file: %s", relpath(path))
  tolower(digest::digest(file = path, algo = "sha256"))
}
assert_columns <- function(data, required, label) {
  missing <- setdiff(required, names(data))
  if (length(missing) > 0L) stopf("Schema validation failed for %s; missing: %s",
                                  label, paste(missing, collapse = ", "))
}
atomic_write_lines <- function(lines, path) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  tmp <- paste0(path, ".tmp")
  if (file.exists(tmp)) unlink(tmp)
  writeLines(enc2utf8(lines), tmp, useBytes = TRUE)
  if (file.exists(path)) unlink(path)
  if (!file.rename(tmp, path)) stopf("Atomic rename failed for %s", relpath(path))
}
atomic_write_csv <- function(data, path) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  tmp <- paste0(path, ".tmp")
  if (file.exists(tmp)) unlink(tmp)
  utils::write.csv(data, tmp, row.names = FALSE, na = "", quote = TRUE)
  if (file.exists(path)) unlink(path)
  if (!file.rename(tmp, path)) stopf("Atomic CSV rename failed for %s", relpath(path))
}
atomic_write_json <- function(object, path) {
  text <- jsonlite::toJSON(object, pretty = TRUE, auto_unbox = TRUE,
                           null = "null", na = "null", digits = 17)
  atomic_write_lines(strsplit(as.character(text), "\n", fixed = TRUE)[[1L]], path)
}
fmt4 <- function(x) {
  x <- suppressWarnings(as.numeric(x))
  ifelse(is.na(x), "NA", sprintf("%.4f", x))
}
fmt_pct <- function(x) {
  x <- suppressWarnings(as.numeric(x))
  ifelse(is.na(x), "NA", sprintf("%.1f%%", 100 * x))
}
raw_num <- function(x) {
  x <- suppressWarnings(as.numeric(x))
  ifelse(is.na(x), "NA", sprintf("%.17g", x))
}

for (d in c("results", "results/figure_data", "figures", "tables",
            "supplement", "scripts", "release_candidate")) {
  dir.create(file.path(output_root, d), recursive = TRUE, showWarnings = FALSE)
}

# These immutable hashes are the P0/P4/P5/P5A/P6 contract checks.
expected_hashes <- c(
  "config/production_model_freeze.json" = "420946f5752d24eeb643ec1bc0052d69420310d4c01d4795da23f11486a3de33",
  "analysis/structured_a3_evaluation/results/final_a3_model.json" = "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e",
  "analysis/p5a_environmental_proxy/results/proxy_contract.json" = "8cfd84439a7d40bedfc080f05ee261a101fccc1db1f3813a393da785110dbc83",
  "config/p6_production_config.json" = "7fd9d25cb6166d550a2984c8658a490a23d7d232965ad4a43470680849f9fc21",
  "analysis/p4_uncertainty_extrapolation/results/support_flag_specification.json" = "d9f0cda8ab1e9698ad0af6c6422f836b5084a63429778cf88f6a4063a8d1218c",
  "analysis/p5_operational_contract/results/input_contract.json" = "964e969a74a6dbe6e9d389d2bbc54866326aa99fe204440abe87f4462bdcf908"
)
for (source in names(expected_hashes)) {
  observed <- sha256_file(abs_path(source))
  if (!identical(observed, expected_hashes[[source]])) {
    stopf("Immutable source hash mismatch for %s: observed %s expected %s",
          source, observed, expected_hashes[[source]])
  }
}

required_sources <- unique(c(
  names(expected_hashes),
  "analysis/structured_a3_evaluation/results/final_a3_coefficients.csv",
  "docs/current/predictors.csv",
  "analysis/p1_production_validation/results/decision.json",
  "analysis/p1_production_validation/results/validation_metrics.csv",
  "analysis/p1_production_validation/results/frontier_metrics.csv",
  "analysis/p2_operational_nowcast/results/decision.json",
  "analysis/p2_operational_nowcast/results/horizon_metrics.csv",
  "analysis/p2_operational_nowcast/results/horizon_deltas.csv",
  "analysis/p2_operational_nowcast/results/count_metrics.csv",
  "analysis/p2_operational_nowcast/results/frontier_metrics.csv",
  "analysis/p2_operational_nowcast/results/calibration_bins.csv",
  "analysis/p3_robustness/results/decision.json",
  "analysis/p3_robustness/results/frontier_sensitivity_metrics.csv",
  "analysis/p3_robustness/results/partition_sensitivity_metrics.csv",
  "analysis/p3_robustness/results/limitation_resolution.csv",
  "analysis/p4_uncertainty_extrapolation/results/decision.json",
  "analysis/p4_uncertainty_extrapolation/results/performance_by_support.csv",
  "analysis/p4_uncertainty_extrapolation/results/support_thresholds.csv",
  "analysis/p5_operational_contract/results/decision.json",
  "analysis/p5_operational_contract/results/output_schema.json",
  "analysis/p5_operational_contract/results/warning_error_codes.json",
  "analysis/p5a_environmental_proxy/results/decision.json",
  "analysis/p5a_environmental_proxy/results/availability_reclassification.json",
  "analysis/p5a_environmental_proxy/results/occurrence_count_metrics.csv",
  "analysis/p5a_environmental_proxy/results/paired_proxy_minus_realized.csv",
  "analysis/p5a_environmental_proxy/results/horizon_degradation.csv",
  "analysis/p5a_environmental_proxy/results/frontier_metrics.csv",
  "analysis/p5a_environmental_proxy/results/support_metrics.csv",
  "analysis/p5a_environmental_proxy/results/support_transitions.csv",
  "analysis/p5a_environmental_proxy/results/proxy_decision.csv",
  "analysis/p5a_environmental_proxy/results/environmental_proxy_error.csv",
  "analysis/p6_production_hardening/results/p6_decision.json",
  "analysis/p6_production_hardening/results/replay_manifests.json",
  "analysis/p6_production_hardening/results/restart_test_results.json",
  "analysis/p6_production_hardening/results/duplicate_run_test.json",
  "analysis/p6_production_hardening/results/corruption_test.json",
  "analysis/p6_production_hardening/results/production_schema.json",
  "analysis/p6_production_hardening/results/monitoring_specification.json"
))
missing_sources <- required_sources[!file.exists(abs_path(required_sources))]
if (length(missing_sources) > 0L) stopf("Canonical source artifact(s) missing: %s",
                                        paste(missing_sources, collapse = ", "))

# Read and validate canonical inputs.
p0 <- read_json("config/production_model_freeze.json")
p6_config <- read_json("config/p6_production_config.json")
p5a_proxy <- read_json("analysis/p5a_environmental_proxy/results/proxy_contract.json")
p2_horizon <- read_csv("analysis/p2_operational_nowcast/results/horizon_metrics.csv")
p2_delta <- read_csv("analysis/p2_operational_nowcast/results/horizon_deltas.csv")
p2_count <- read_csv("analysis/p2_operational_nowcast/results/count_metrics.csv")
p2_calibration <- read_csv("analysis/p2_operational_nowcast/results/calibration_bins.csv")
p5a_occurrence <- read_csv("analysis/p5a_environmental_proxy/results/occurrence_count_metrics.csv")
p5a_paired <- read_csv("analysis/p5a_environmental_proxy/results/paired_proxy_minus_realized.csv")
p5a_frontier <- read_csv("analysis/p5a_environmental_proxy/results/frontier_metrics.csv")
p5a_support <- read_csv("analysis/p5a_environmental_proxy/results/support_metrics.csv")
p5a_transitions <- read_csv("analysis/p5a_environmental_proxy/results/support_transitions.csv")
p5a_decisions <- read_csv("analysis/p5a_environmental_proxy/results/proxy_decision.csv")

assert_columns(p2_horizon, c("scope", "horizon", "region", "n", "positives",
                             "prevalence", "brier", "log_loss",
                             "calibration_intercept", "calibration_slope", "auroc", "auprc"),
               "P2 horizon_metrics.csv")
assert_columns(p2_delta, c("comparison", "metric", "horizon_1", "horizon_3",
                           "delta_3_minus_1"), "P2 horizon_deltas.csv")
assert_columns(p2_count, c("scope", "horizon", "region", "n", "positive_n",
                           "conditional_mae", "conditional_bias",
                           "conditional_observed_predicted_ratio", "full_expected_mae",
                           "full_expected_bias"), "P2 count_metrics.csv")
assert_columns(p2_calibration, c("metric_family", "scope", "horizon", "n",
                                 "positive_n", "mean_predicted", "observed_probability"),
               "P2 calibration_bins.csv")
assert_columns(p5a_occurrence, c("proxy_id", "horizon", "n", "positives", "prevalence",
                                 "brier", "calibration_intercept", "calibration_slope",
                                 "log_loss", "auroc", "auprc", "conditional_mae",
                                 "conditional_bias", "conditional_observed_predicted_ratio",
                                 "full_expected_mae", "full_expected_bias"),
               "P5A occurrence_count_metrics.csv")
assert_columns(p5a_paired, c("proxy_id", "horizon", "metric", "proxy_value",
                             "realized_value", "difference_proxy_minus_realized"),
               "P5A paired_proxy_minus_realized.csv")
assert_columns(p5a_support, c("proxy_id", "horizon", "support_class", "n", "proportion"),
               "P5A support_metrics.csv")
assert_columns(p5a_transitions, c("proxy_id", "from_support_class", "to_support_class", "n"),
               "P5A support_transitions.csv")
assert_columns(p5a_decisions, c("proxy_id", "classification", "reason"),
               "P5A proxy_decision.csv")

p2_all <- p2_horizon[p2_horizon$scope == "all" & p2_horizon$region == "all" &
                      as.character(p2_horizon$horizon) %in% c("1", "2", "3"), , drop = FALSE]
p2_count_all <- p2_count[p2_count$scope == "all" & p2_count$region == "all" &
                          as.character(p2_count$horizon) %in% c("1", "2", "3"), , drop = FALSE]
p2_all <- p2_all[order(as.numeric(p2_all$horizon)), , drop = FALSE]
p2_count_all <- p2_count_all[order(as.numeric(p2_count_all$horizon)), , drop = FALSE]
if (nrow(p2_all) != 3L || !identical(as.character(p2_all$horizon), c("1", "2", "3"))) {
  stopf("P2 all-domain horizon rows are not exactly h=1,2,3")
}
if (nrow(p2_count_all) != 3L) stopf("P2 all-domain count rows are not h=1,2,3")
if (!identical(p0$identity$model_id, "STRUCTURED_A3")) stopf("P0 model is not STRUCTURED_A3")
if (length(p0$predictor_specification$ordered_predictors) != 34L) stopf("P0 predictor count is not 34")
if (!identical(p6_config$scientific_model$model_id, "STRUCTURED_A3") ||
    !identical(p6_config$operational_contract$proxy_id, "E0_LAST_AVAILABLE")) {
  stopf("P6 production configuration does not match qualified specification")
}
if (!"E0_LAST_AVAILABLE" %in% p5a_proxy$proxy_ids) stopf("P5A proxy contract does not include E0")

source_hashes <- data.frame(
  artifact = required_sources,
  sha256 = vapply(required_sources, function(x) sha256_file(abs_path(x)), character(1L)),
  stringsAsFactors = FALSE
)
atomic_write_csv(source_hashes, file.path(output_root, "results", "source_artifact_hashes.csv"))

if (verify_only) {
  expected_outputs <- c("results/claim_registry.csv", "results/results_synthesis.md",
                        "results/reproducibility_manifest.json", "results/figure_manifest.csv",
                        "tables/table_1_data_model_specification.csv",
                        "tables/table_2_occurrence_performance.csv",
                        "tables/table_3_count_performance.csv",
                        "tables/table_4_proxy_comparison.csv",
                        "tables/table_5_limitation_summary.csv",
                        "results/publication_reviewer_checklist.md",
                        "release_candidate/package_manifest.json")
  missing_outputs <- expected_outputs[!file.exists(file.path(output_root, expected_outputs))]
  if (length(missing_outputs) > 0L) stopf("P7 outputs missing: %s",
                                         paste(missing_outputs, collapse = ", "))
  cat("P7_PUBLICATION_BUILD_VERIFIED\n")
  quit(save = "no", status = 0L)
}

# Main tables.
table1 <- data.frame(
  item = c("scientific_model", "frozen_model_sha256", "training_horizon",
           "geographic_domain", "grid_resolution", "canonical_cells", "predictor_count",
           "occurrence_component", "count_component", "penalty", "theta",
           "operational_proxy", "prediction_horizons", "production_schema"),
  value = c(p0$identity$model_id, p0$frozen_artifacts[[1L]]$sha256,
            paste0(p0$scientific_specification$fitting_horizon$start_week, " to ",
                   p0$scientific_specification$fitting_horizon$end_week),
            p0$scientific_specification$geographic_domain,
            p0$scientific_specification$spatial_resolution,
            as.character(p0$scientific_specification$node_count),
            as.character(length(p0$predictor_specification$ordered_predictors)),
            p0$scientific_specification$occurrence_component,
            p0$scientific_specification$positive_count_component,
            raw_num(p0$model_specification$regularization_penalty),
            raw_num(p0$model_specification$theta), p6_config$operational_contract$proxy_id,
            paste(p6_config$operational_contract$horizons, collapse = ","),
            p6_config$output_contract$schema_version),
  source_artifact = c(rep("config/production_model_freeze.json", 11L),
                      rep("config/p6_production_config.json", 3L)),
  stringsAsFactors = FALSE
)
table2 <- data.frame(
  horizon = as.integer(p2_all$horizon), n = as.integer(p2_all$n),
  positives = as.integer(p2_all$positives), prevalence = fmt4(p2_all$prevalence),
  brier = fmt4(p2_all$brier), calibration_intercept = fmt4(p2_all$calibration_intercept),
  calibration_slope = fmt4(p2_all$calibration_slope), auroc = fmt4(p2_all$auroc),
  auprc = fmt4(p2_all$auprc),
  source_artifact = "analysis/p2_operational_nowcast/results/horizon_metrics.csv",
  stringsAsFactors = FALSE
)
table3 <- data.frame(
  horizon = as.integer(p2_count_all$horizon), positive_n = as.integer(p2_count_all$positive_n),
  conditional_mae = fmt4(p2_count_all$conditional_mae),
  conditional_bias = fmt4(p2_count_all$conditional_bias),
  observed_predicted_ratio = fmt4(p2_count_all$conditional_observed_predicted_ratio),
  full_expected_mae = fmt4(p2_count_all$full_expected_mae),
  full_expected_bias = fmt4(p2_count_all$full_expected_bias),
  source_artifact = "analysis/p2_operational_nowcast/results/count_metrics.csv",
  stringsAsFactors = FALSE
)
table4_rows <- list()
for (h in 1:3) for (proxy_id in c("REALIZED_ENV", "E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN")) {
  row <- p5a_occurrence[p5a_occurrence$proxy_id == proxy_id &
                        as.integer(p5a_occurrence$horizon) == h, , drop = FALSE]
  if (nrow(row) != 1L) stopf("Missing P5A occurrence row for %s h=%s", proxy_id, h)
  table4_rows[[length(table4_rows) + 1L]] <- data.frame(
    proxy_id = proxy_id, horizon = h, n = as.integer(row$n), brier = fmt4(row$brier),
    calibration_intercept = fmt4(row$calibration_intercept),
    calibration_slope = fmt4(row$calibration_slope), auprc = fmt4(row$auprc),
    conditional_mae = fmt4(row$conditional_mae), conditional_bias = fmt4(row$conditional_bias),
    full_expected_mae = fmt4(row$full_expected_mae), full_expected_bias = fmt4(row$full_expected_bias),
    source_artifact = "analysis/p5a_environmental_proxy/results/occurrence_count_metrics.csv",
    stringsAsFactors = FALSE)
}
table4 <- do.call(rbind, table4_rows)
table5 <- data.frame(
  limitation = c("Sparse frontier positives", "Sparse U.S./regional outcome support",
                 "Count-process bias", "Extrapolative environmental support",
                 "Dependence on E0_LAST_AVAILABLE", "No refitted spatial holdout",
                 "Observational/predictive rather than causal interpretation",
                 "Source-product availability and version limitations"),
  evidence = c("P1/P2 frontier strata and P3 sensitivity retain sparse positive support.",
               "P1/P2 regional strata contain few positives, especially in the U.S. footprint.",
               "P2/P3 count metrics show measurable conditional and full-hurdle bias.",
               "P4/P5A support metrics show a substantial CAUTION/EXTRAPOLATIVE burden.",
               "P5A validates E0 as an issue-time proxy, not a future environmental forecast.",
               "P3 regrouping is diagnostic and does not create a refitted spatial holdout.",
               "Predictive associations are not causal environmental effects.",
               "P5/P6 retain source-vintage and replay availability limitations."),
  phase_identified = c("P1--P3", "P1--P3", "P2--P3", "P4--P5A", "P5A--P6", "P1--P3", "P0--P7", "P5--P6"),
  operational_treatment = c("Report frontier strata and sample sizes; retain support flags.",
                            "Report regional results descriptively; do not generalize beyond support.",
                            "Report conditional and full-hurdle metrics; no recalibration.",
                            "Emit unchanged support classes and explicit extrapolative warnings.",
                            "Record proxy ID and source vintage in production provenance.",
                            "State the partition boundary explicitly; no claim of independent spatial holdout.",
                            "Use predictive language only.",
                            "Preserve source hashes/vintages and distinguish replay from readiness."),
  manuscript_interpretation = c("Robustly limited frontier inference.",
                                "Transfer evidence is strongest where outcomes are supported.",
                                "Counts are useful but not unbiased abundance estimates.",
                                "Support is heterogeneous and must accompany every prediction.",
                                "Operational nowcasts use a persistence-like environmental state.",
                                "Sensitivity does not replace a refitted holdout.",
                                "The package supports prediction, not causal interpretation.",
                                "Availability and revisions remain operational caveats."),
  source_artifact = c("analysis/p3_robustness/results/limitation_resolution.csv",
                      "analysis/p3_robustness/results/limitation_resolution.csv",
                      "analysis/p2_operational_nowcast/results/count_metrics.csv",
                      "analysis/p5a_environmental_proxy/results/support_metrics.csv",
                      "analysis/p5a_environmental_proxy/results/proxy_contract.json",
                      "analysis/p3_robustness/results/limitation_resolution.csv",
                      "config/production_model_freeze.json",
                      "analysis/p6_production_hardening/results/p6_decision.json"),
  stringsAsFactors = FALSE
)
atomic_write_csv(table1, file.path(output_root, "tables", "table_1_data_model_specification.csv"))
atomic_write_csv(table2, file.path(output_root, "tables", "table_2_occurrence_performance.csv"))
atomic_write_csv(table3, file.path(output_root, "tables", "table_3_count_performance.csv"))
atomic_write_csv(table4, file.path(output_root, "tables", "table_4_proxy_comparison.csv"))
atomic_write_csv(table5, file.path(output_root, "tables", "table_5_limitation_summary.csv"))

# Supplementary tables are copied through validated readers, not hand-entered.
supplement_sources <- c("docs/current/predictors.csv",
  "analysis/p1_production_validation/results/validation_metrics.csv",
  "analysis/p1_production_validation/results/frontier_metrics.csv",
  "analysis/p3_robustness/results/frontier_sensitivity_metrics.csv",
  "analysis/p3_robustness/results/partition_sensitivity_metrics.csv",
  "analysis/p4_uncertainty_extrapolation/results/support_thresholds.csv",
  "analysis/p5_operational_contract/results/warning_error_codes.json",
  "analysis/p6_production_hardening/results/production_schema.json",
  "analysis/p6_production_hardening/results/monitoring_specification.json")
for (source in supplement_sources) {
  dest <- file.path(output_root, "supplement", basename(source))
  if (grepl("\\.json$", source, ignore.case = TRUE)) atomic_write_json(read_json(source), dest)
  else atomic_write_csv(read_csv(source), dest)
}
atomic_write_csv(read_csv("analysis/structured_a3_evaluation/results/final_a3_coefficients.csv"),
                 file.path(output_root, "supplement", "frozen_a3_coefficients.csv"))
predictor_records <- p0$predictor_specification$ordered_predictors
predictor_inventory <- data.frame(
  predictor = vapply(predictor_records, function(x) x$name, character(1L)),
  frozen_role = vapply(predictor_records, function(x) x$lag, character(1L)),
  transformation = vapply(predictor_records, function(x) x$transformation, character(1L)),
  source_layer = vapply(predictor_records, function(x) x$source_layer, character(1L)),
  stringsAsFactors = FALSE)
atomic_write_csv(predictor_inventory,
                 file.path(output_root, "supplement", "frozen_34_predictor_inventory.csv"))

# Claim registry. Each exact_value string is generated from source rows before
# display rounding; it is not manually transcribed.
p2_brier <- setNames(p2_all$brier, p2_all$horizon)
p2_auprc <- setNames(p2_all$auprc, p2_all$horizon)
p2_delta_row <- p2_delta[p2_delta$metric == "brier" &
                          p2_delta$comparison == "h3_minus_h1_common_target_weeks", , drop = FALSE]
if (nrow(p2_delta_row) != 1L) stopf("P2 common-week Brier delta is missing")
e0_brier_delta <- p5a_paired[p5a_paired$proxy_id == "E0_LAST_AVAILABLE" &
                              p5a_paired$metric == "brier", , drop = FALSE]
e0_auprc_delta <- p5a_paired[p5a_paired$proxy_id == "E0_LAST_AVAILABLE" &
                              p5a_paired$metric == "auprc", , drop = FALSE]
frontier_h1 <- p5a_frontier[p5a_frontier$proxy_id == "REALIZED_ENV" &
                             p5a_frontier$horizon == 1, , drop = FALSE]
support_e0_h3 <- p5a_support[p5a_support$proxy_id == "E0_LAST_AVAILABLE" &
                              p5a_support$horizon == 3, , drop = FALSE]
p1_decision <- read_json("analysis/p1_production_validation/results/decision.json")
p2_decision <- read_json("analysis/p2_operational_nowcast/results/decision.json")
p3_decision <- read_json("analysis/p3_robustness/results/decision.json")
p4_decision <- read_json("analysis/p4_uncertainty_extrapolation/results/decision.json")
p5_decision <- read_json("analysis/p5_operational_contract/results/decision.json")
p5a_decision <- read_json("analysis/p5a_environmental_proxy/results/decision.json")
p6_decision <- read_json("analysis/p6_production_hardening/results/p6_decision.json")
decision_values <- list(P1 = p1_decision$decision, P2 = p2_decision$decision,
                       P3 = p3_decision$decision, P4 = p4_decision$decision,
                       P5 = p5_decision$decision, P5A = p5a_decision$decision,
                       P6 = p6_decision$decision)
if (is.null(decision_values$P1)) {
  decision_values$P1 <- paste0("P1_TRANSFER_VALIDATION_", p1_decision$overall_decision)
}
support_exact <- paste(paste0(support_e0_h3$support_class, "=", raw_num(support_e0_h3$proportion)),
                       collapse = "; ")
claim_registry <- data.frame(
  claim_id = LETTERS[1:8],
  concise_claim = c(
    "Occurrence discrimination and calibration are summarized across h=1--3.",
    "Common-week performance changes are reported with the exact source delta.",
    "E0_LAST_AVAILABLE has small paired occurrence differences from REALIZED_ENV.",
    "Frontier/newly unoccupied prediction is weaker and sparsely supported.",
    "Conditional and full-hurdle count predictions retain measurable bias.",
    "Bounded P3 sensitivity conclusions remain consistent with the canonical decision.",
    "A substantial share of rows are CAUTION or EXTRAPOLATIVE under P4 support rules.",
    "P6 records deterministic, restartable, hash-verified, failure-safe operation."),
  source_phase = c("P2", "P2", "P5A", "P1--P3/P5A", "P2--P3", "P3", "P4/P5A", "P5/P6"),
  source_artifact = c(
    "analysis/p2_operational_nowcast/results/horizon_metrics.csv",
    "analysis/p2_operational_nowcast/results/horizon_deltas.csv",
    "analysis/p5a_environmental_proxy/results/paired_proxy_minus_realized.csv",
    "analysis/p5a_environmental_proxy/results/frontier_metrics.csv",
    "analysis/p2_operational_nowcast/results/count_metrics.csv",
    "analysis/p3_robustness/results/decision.json",
    "analysis/p5a_environmental_proxy/results/support_metrics.csv",
    "analysis/p6_production_hardening/results/p6_decision.json"),
  source_metric_or_row = c(
    "scope=all, region=all, h=1..3: brier/auprc/calibration",
    "comparison=h3_minus_h1_common_target_weeks, metric=brier",
    "proxy=E0_LAST_AVAILABLE, metric=brier/auprc, h=1..3",
    "REALIZED_ENV, h=1, previously_unoccupied",
    "scope=all, region=all, h=1..3: conditional/full bias",
    "decision and limitation records",
    "proxy=E0_LAST_AVAILABLE, h=3 support rows",
    "decision and hardening validation records"),
  exact_value = c(
    paste0("Brier h1=", raw_num(p2_brier[["1"]]), "; h2=", raw_num(p2_brier[["2"]]),
           "; h3=", raw_num(p2_brier[["3"]]), "; AUPRC h1=", raw_num(p2_auprc[["1"]]),
           "; h2=", raw_num(p2_auprc[["2"]]), "; h3=", raw_num(p2_auprc[["3"]])),
    paste0("Brier common-week delta h3-h1=", raw_num(p2_delta_row$delta_3_minus_1)),
    paste0("E0 Brier deltas=", paste(raw_num(e0_brier_delta$difference_proxy_minus_realized), collapse = ","),
           "; AUPRC deltas=", paste(raw_num(e0_auprc_delta$difference_proxy_minus_realized), collapse = ",")),
    paste0("N previously_unoccupied=", frontier_h1$n[frontier_h1$frontier_class == "previously_unoccupied"],
           "; positives=", frontier_h1$positives[frontier_h1$frontier_class == "previously_unoccupied"],
           "; Brier=", raw_num(frontier_h1$brier[frontier_h1$frontier_class == "previously_unoccupied"]),
           "; AUPRC=", raw_num(frontier_h1$auprc[frontier_h1$frontier_class == "previously_unoccupied"])),
    paste0("conditional bias h1--h3=", paste(raw_num(p2_count_all$conditional_bias), collapse = ","),
           "; full bias h1--h3=", paste(raw_num(p2_count_all$full_expected_bias), collapse = ",")),
    p3_decision$decision,
    support_exact,
    paste0(p6_decision$decision, "; restartability=", p6_decision$restartability,
           "; duplicate_protection=", p6_decision$duplicate_protection,
           "; corruption_detection=", p6_decision$corruption_detection)),
  uncertainty_interval = c(
    "Canonical P2 bootstrap interval artifact; no P7 re-estimation.",
    "Canonical P2 horizon-delta source where available.",
    "Canonical P5A paired comparison source.",
    "Canonical sparse frontier source intervals/metrics.",
    "Canonical P2/P3 count diagnostics.",
    "P3 bounded sensitivity records.",
    "P4/P5A support summaries.",
    "P6 deterministic validation records."),
  allowed_interpretation = c(
    "Short-horizon retrospective rolling-origin occurrence performance.",
    "Minimal common-week horizon change as reported by P2.",
    "Issue-time proxy viability under P5A.",
    "Frontier evidence is weaker and sparse.",
    "Counts are predictive outputs with measurable bias.",
    "Stability within bounded prespecified sensitivity analyses.",
    "Support classes accompany predictions and identify extrapolation.",
    "Operational reproducibility within the qualified contract."),
  prohibited_overinterpretation = c(
    "No unrestricted prospective forecasting or universal validity.",
    "No claim of zero degradation outside the reported metric.",
    "No claim that E0 is a true future environmental forecast.",
    "No claim of complete frontier validity.",
    "No claim of unbiased abundance prediction.",
    "No extrapolation beyond P3 designs.",
    "No claim of universal environmental support.",
    "No claim that limitations are removed or automated retraining exists."),
  destination = c("Figure 2; Table 2", "Figure 2; Results", "Figure 4; Table 4",
                  "Figure 5; Table 5", "Figure 6; Table 3", "Results; Table 5",
                  "Figure 7; Table 5", "Figure 8; Methods/Results"),
  stringsAsFactors = FALSE)
atomic_write_csv(claim_registry, file.path(output_root, "results", "claim_registry.csv"))

# Figure source data.
figure_data_dir <- file.path(output_root, "results", "figure_data")
atomic_write_csv(p2_all[, c("horizon", "brier", "auprc", "calibration_intercept",
                            "calibration_slope")],
                 file.path(figure_data_dir, "figure_02_rolling_origin.csv"))
calibration <- p2_calibration[p2_calibration$metric_family == "occurrence" &
                               p2_calibration$scope == "all" &
                               as.character(p2_calibration$horizon) %in% c("1", "2", "3"),
                               c("horizon", "bin_index", "n", "mean_predicted",
                                 "observed_probability", "observed_se"), drop = FALSE]
if (nrow(calibration) == 0L) stopf("P2 calibration source has no h=1..3 rows")
atomic_write_csv(calibration, file.path(figure_data_dir, "figure_03_calibration.csv"))
proxy_plot <- p5a_paired[p5a_paired$proxy_id %in% c("E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN") &
                           p5a_paired$metric %in% c("brier", "auprc"), , drop = FALSE]
atomic_write_csv(proxy_plot, file.path(figure_data_dir, "figure_04_proxy_degradation.csv"))
frontier_plot <- p5a_frontier[p5a_frontier$proxy_id == "REALIZED_ENV" &
                               p5a_frontier$horizon == 1, , drop = FALSE]
atomic_write_csv(frontier_plot, file.path(figure_data_dir, "figure_05_frontier.csv"))
count_plot <- p2_count_all[, c("horizon", "conditional_bias", "full_expected_bias",
                               "conditional_mae", "full_expected_mae")]
atomic_write_csv(count_plot, file.path(figure_data_dir, "figure_06_counts.csv"))
support_plot <- p5a_support[p5a_support$proxy_id == "E0_LAST_AVAILABLE", , drop = FALSE]
atomic_write_csv(support_plot, file.path(figure_data_dir, "figure_07_support.csv"))

save_svg <- function(filename, width = 7.2, height = 4.8, plot_fun) {
  tmp <- paste0(filename, ".tmp")
  if (file.exists(tmp)) unlink(tmp)
  grDevices::svg(tmp, width = width, height = height, pointsize = 10,
                 onefile = FALSE, bg = "white")
  tryCatch(plot_fun(), finally = grDevices::dev.off())
  if (file.exists(filename)) unlink(filename)
  if (!file.rename(tmp, filename)) stopf("Could not finalize SVG %s", relpath(filename))
}
figure_paths <- file.path(output_root, "figures", sprintf("figure_%02d_", 1:8))
figure_paths <- paste0(figure_paths, c("framework.svg", "rolling_origin_performance.svg",
                                      "calibration.svg", "environmental_proxy.svg",
                                      "frontier_performance.svg", "count_performance.svg",
                                      "support_extrapolation.svg", "qualification_sequence.svg"))

save_svg(figure_paths[1L], plot_fun = function() {
  plot.new(); par(mar = c(0, 0, 1, 0))
  boxes <- list(c(0.03, 0.62, 0.22, 0.84), c(0.29, 0.62, 0.48, 0.84),
                c(0.55, 0.62, 0.74, 0.84), c(0.81, 0.62, 0.98, 0.84),
                c(0.16, 0.20, 0.38, 0.42), c(0.47, 0.20, 0.69, 0.42),
                c(0.78, 0.20, 0.98, 0.42))
  labels <- c("Weekly observations", "34-predictor input", "STRUCTURED_A3\nhurdle model",
              "1–3 week\nnowcast", "E0_LAST_AVAILABLE\nissue-time state",
              "P4 support /\nuncertainty", "Prediction +\nprovenance")
  fills <- c("#E7F0F7", "#EAF4EA", "#F7EEDC", "#F3E6F2", "#EAF4EA", "#F7EEDC", "#E7F0F7")
  for (i in seq_along(boxes)) {
    b <- boxes[[i]]
    rect(b[1], b[2], b[3], b[4], col = fills[[i]], border = "#4A5568", lwd = 1.1)
    text((b[1] + b[3]) / 2, (b[2] + b[4]) / 2, labels[[i]], cex = 0.86)
  }
  arrows(0.22, 0.73, 0.29, 0.73, length = 0.08)
  arrows(0.48, 0.73, 0.55, 0.73, length = 0.08)
  arrows(0.74, 0.73, 0.81, 0.73, length = 0.08)
  arrows(0.27, 0.42, 0.31, 0.62, length = 0.08)
  arrows(0.58, 0.42, 0.61, 0.62, length = 0.08)
  arrows(0.69, 0.73, 0.69, 0.42, length = 0.08)
  arrows(0.74, 0.31, 0.78, 0.31, length = 0.08)
  title("Study and operational nowcast framework", line = -1)
})

save_svg(figure_paths[2L], plot_fun = function() {
  par(mfrow = c(1, 2), mar = c(4, 4, 2, 1))
  h <- as.numeric(p2_all$horizon)
  plot(h, p2_all$brier, type = "b", pch = 19, xaxt = "n", xlab = "Horizon (weeks)",
       ylab = "Brier score", main = "Occurrence performance")
  axis(1, at = h, labels = h); grid()
  plot(h, p2_all$auprc, type = "b", pch = 19, xaxt = "n", xlab = "Horizon (weeks)",
       ylab = "AUPRC", main = "Occurrence discrimination")
  axis(1, at = h, labels = h); grid()
})

save_svg(figure_paths[3L], plot_fun = function() {
  par(mar = c(4, 4, 2, 1))
  cols <- c("#2C7FB8", "#41B6C4", "#7FCDBB")
  hvals <- sort(unique(as.numeric(calibration$horizon)))
  plot(range(calibration$mean_predicted, finite = TRUE),
       range(calibration$observed_probability, finite = TRUE), type = "n",
       xlab = "Mean predicted probability", ylab = "Observed probability",
       main = "Reliability by horizon")
  abline(0, 1, lty = 2, col = "grey50")
  for (i in seq_along(hvals)) {
    d <- calibration[as.numeric(calibration$horizon) == hvals[[i]], , drop = FALSE]
    lines(d$mean_predicted, d$observed_probability, type = "b", pch = 19,
          col = cols[[i]], lwd = 1.2)
  }
  legend("topleft", legend = paste0("h=", hvals), col = cols[seq_along(hvals)],
         lty = 1, pch = 19, bty = "n")
})

save_svg(figure_paths[4L], plot_fun = function() {
  par(mfrow = c(1, 2), mar = c(4, 4, 2, 1))
  for (metric in c("brier", "auprc")) {
    d <- proxy_plot[proxy_plot$metric == metric, , drop = FALSE]
    proxies <- unique(as.character(d$proxy_id))
    ylim <- range(d$difference_proxy_minus_realized, finite = TRUE)
    plot(NA, xlim = c(1, 3), ylim = ylim, xaxt = "n", xlab = "Horizon (weeks)",
         ylab = "Proxy minus REALIZED_ENV", main = toupper(metric))
    abline(h = 0, lty = 2, col = "grey50")
    for (i in seq_along(proxies)) {
      dd <- d[d$proxy_id == proxies[[i]], , drop = FALSE]
      lines(as.numeric(dd$horizon), dd$difference_proxy_minus_realized,
            type = "b", pch = 19, col = c("#2C7FB8", "#D95F02")[[i]])
    }
    legend("topleft", legend = proxies, col = c("#2C7FB8", "#D95F02"),
           lty = 1, pch = 19, bty = "n", cex = 0.8)
    axis(1, at = 1:3, labels = 1:3)
  }
})

save_svg(figure_paths[5L], plot_fun = function() {
  d <- frontier_plot
  mat <- rbind(d$brier, d$auprc)
  barplot(mat, beside = TRUE, names.arg = as.character(d$frontier_class),
          col = c("#2C7FB8", "#D95F02"), ylab = "Metric",
          main = "h=1 frontier strata (REALIZED_ENV)",
          legend.text = c("Brier", "AUPRC"),
          args.legend = list(bty = "n", cex = 0.8))
})

save_svg(figure_paths[6L], plot_fun = function() {
  par(mfrow = c(1, 2), mar = c(4, 4, 2, 1))
  h <- as.numeric(count_plot$horizon)
  plot(h, count_plot$conditional_bias, type = "b", pch = 19, xaxt = "n",
       xlab = "Horizon (weeks)", ylab = "Mean signed bias", main = "Count bias")
  lines(h, count_plot$full_expected_bias, type = "b", pch = 17, col = "#D95F02")
  axis(1, at = h, labels = h); abline(h = 0, lty = 2, col = "grey50")
  legend("topleft", legend = c("Conditional", "Full hurdle"), pch = c(19, 17),
         col = c("black", "#D95F02"), bty = "n", cex = 0.8)
  plot(h, count_plot$conditional_mae, type = "b", pch = 19, xaxt = "n",
       xlab = "Horizon (weeks)", ylab = "MAE", main = "Count error")
  lines(h, count_plot$full_expected_mae, type = "b", pch = 17, col = "#D95F02")
  axis(1, at = h, labels = h)
})

save_svg(figure_paths[7L], plot_fun = function() {
  classes <- c("SUPPORTED", "CAUTION", "EXTRAPOLATIVE")
  mat <- t(sapply(1:3, function(h) {
    d <- support_plot[as.numeric(support_plot$horizon) == h, , drop = FALSE]
    setNames(d$proportion[match(classes, d$support_class)], classes)
  }))
  barplot(t(mat), beside = FALSE, col = c("#4DAF4A", "#FFB000", "#D95F02"),
          names.arg = paste0("h=", 1:3), ylim = c(0, 1), ylab = "Proportion",
          main = "E0 support classes")
  legend("topright", legend = classes, fill = c("#4DAF4A", "#FFB000", "#D95F02"),
         bty = "n", cex = 0.8)
})

save_svg(figure_paths[8L], plot_fun = function() {
  plot.new(); par(mar = c(0, 0, 1, 0))
  phase_labels <- c("P0\nFreeze", "P1\nTransfer", "P2\nNowcast", "P3\nRobustness",
                   "P4\nSupport", "P5A\nProxy", "P6\nHardening")
  x <- seq(0.07, 0.93, length.out = length(phase_labels))
  for (i in seq_along(x)) {
    rect(x[[i]] - 0.055, 0.45, x[[i]] + 0.055, 0.66,
         col = if (i == 6L) "#EAF4EA" else "#E7F0F7", border = "#4A5568")
    text(x[[i]], 0.555, phase_labels[[i]], cex = 0.82)
    if (i < length(x)) arrows(x[[i]] + 0.058, 0.555, x[[i + 1L]] - 0.058,
                              0.555, length = 0.06)
  }
  text(0.5, 0.25, "Qualified production: STRUCTURED_A3 + E0_LAST_AVAILABLE + P4 support flags",
       cex = 0.9)
  title("Qualification sequence and production contract", line = -1)
})

figure_manifest <- data.frame(
  figure_id = sprintf("Figure %d", 1:8),
  path = relpath(figure_paths),
  source_artifact = c(
    "config/production_model_freeze.json; config/p6_production_config.json",
    "analysis/p2_operational_nowcast/results/horizon_metrics.csv",
    "analysis/p2_operational_nowcast/results/calibration_bins.csv",
    "analysis/p5a_environmental_proxy/results/paired_proxy_minus_realized.csv",
    "analysis/p5a_environmental_proxy/results/frontier_metrics.csv",
    "analysis/p2_operational_nowcast/results/count_metrics.csv",
    "analysis/p5a_environmental_proxy/results/support_metrics.csv",
    "analysis/p6_production_hardening/results/p6_decision.json"),
  generation_script = "analysis/p7_publication/scripts/build_publication_artifacts.R",
  data_hash = c(NA_character_,
    sha256_file(file.path(figure_data_dir, "figure_02_rolling_origin.csv")),
    sha256_file(file.path(figure_data_dir, "figure_03_calibration.csv")),
    sha256_file(file.path(figure_data_dir, "figure_04_proxy_degradation.csv")),
    sha256_file(file.path(figure_data_dir, "figure_05_frontier.csv")),
    sha256_file(file.path(figure_data_dir, "figure_06_counts.csv")),
    sha256_file(file.path(figure_data_dir, "figure_07_support.csv")), NA_character_),
  stringsAsFactors = FALSE)
atomic_write_csv(figure_manifest, file.path(output_root, "results", "figure_manifest.csv"))
atomic_write_lines(c(
  "# Figure captions", "",
  "**Figure 1.** Study/model framework for the frozen STRUCTURED_A3 hurdle model and issue-time environmental proxy.",
  "", "**Figure 2.** Retrospective rolling-origin occurrence performance by horizon.",
  "", "**Figure 3.** Reliability curves by horizon from canonical P2 calibration bins.",
  "", "**Figure 4.** Paired proxy-minus-realized differences for prespecified environmental proxies.",
  "", "**Figure 5.** h=1 frontier strata; sparse previously-unoccupied positives are shown.",
  "", "**Figure 6.** Conditional positive-count and full-hurdle expected-count behavior.",
  "", "**Figure 7.** P4 support classes under E0_LAST_AVAILABLE.",
  "", "**Figure 8.** Qualification sequence and qualified production contract."),
  file.path(output_root, "results", "figure_captions.md"))

# Controlled synthesis and manuscript components.
phase_decision_lines <- c(
  paste0("- P1: `", decision_values$P1, "`"),
  paste0("- P2: `", decision_values$P2, "`"),
  paste0("- P3: `", decision_values$P3, "`"),
  paste0("- P4: `", decision_values$P4, "`"),
  paste0("- P5: `", decision_values$P5, "`"),
  paste0("- P5A: `", decision_values$P5A, "`"),
  paste0("- P6: `", decision_values$P6, "`"))
headline_performance <- paste0(
  "P2 all-domain Brier scores were ", paste(fmt4(p2_all$brier), collapse = ", "),
  " for h=1--3 and AUPRC values were ", paste(fmt4(p2_all$auprc), collapse = ", "), ".")
proxy_summary <- paste0(
  "P5A E0 Brier differences relative to REALIZED_ENV were ",
  paste(fmt4(e0_brier_delta$difference_proxy_minus_realized), collapse = ", "),
  " for h=1--3; the source comparison is paired and uses the same evaluation records.")
support_summary <- paste0(
  "Under E0 at h=3, support proportions were ",
  paste(paste0(support_e0_h3$support_class, " ", fmt_pct(support_e0_h3$proportion)),
        collapse = ", "), ".")
synthesis_lines <- c(
  "# Controlled Results Synthesis", "",
  "This document is generated only from canonical P1--P6 machine-readable artifacts.",
  "It is a controlled source for manuscript wording, not a new scientific analysis.", "",
  "## Qualified model and horizon", "",
  paste0("The frozen model is `", p0$identity$model_id, "` with 34 predictors on the ",
         p0$scientific_specification$spatial_resolution, " canonical grid (",
         p0$scientific_specification$node_count, " cells). The qualified operational",
         " configuration uses `E0_LAST_AVAILABLE` across the 1--3 week nowcast horizon."),
  "Source: `config/production_model_freeze.json`; `config/p6_production_config.json`.", "",
  "## Canonical decisions", "", phase_decision_lines, "",
  "## Occurrence performance", "", headline_performance,
  "Calibration intercepts, slopes, AUROC, sample sizes, and prevalence are in",
  "`tables/table_2_occurrence_performance.csv`, sourced from",
  "`analysis/p2_operational_nowcast/results/horizon_metrics.csv`. These are",
  "retrospective rolling-origin results, not unrestricted prospective forecasts.", "",
  "## Horizon change", "",
  paste0("The canonical common-week Brier change from h=1 to h=3 was ",
         fmt4(p2_delta_row$delta_3_minus_1), ". Source: ",
         "`analysis/p2_operational_nowcast/results/horizon_deltas.csv`."), "",
  "## Environmental proxy", "", proxy_summary,
  "E0 is the latest legitimately available environmental state held across h=1--3;",
  "it is not a realized future environment or a numerical weather forecast.",
  "Source: `analysis/p5a_environmental_proxy/results/paired_proxy_minus_realized.csv` and",
  "`analysis/p5a_environmental_proxy/results/proxy_contract.json`.", "",
  "## Frontier, count, and support limitations", "",
  "Previously unoccupied/frontier rows have weaker performance and sparse positive",
  "support in the canonical frontier strata. Conditional positive-count and full-hurdle",
  "metrics retain measurable bias. P4 support classification is emitted per row",
  "and a substantial share of E0 predictions are CAUTION or EXTRAPOLATIVE.",
  support_summary,
  "Sources: P1--P4 frontier/support artifacts, `analysis/p2_operational_nowcast/results/count_metrics.csv`,",
  "and `analysis/p5a_environmental_proxy/results/support_metrics.csv`.", "",
  "## Production qualification", "",
  "P6 records deterministic replay, restartability, duplicate-run protection,",
  "corruption detection, and provenance within the qualified contract, with the",
  "documented source-vintage and history-cutoff limitations. The production",
  "interpretation is short-horizon nowcasting under an issue-time environmental",
  "proxy assumption, with support and uncertainty flags retained.",
  "Source: `analysis/p6_production_hardening/results/p6_decision.json`.")
atomic_write_lines(synthesis_lines, file.path(output_root, "results", "results_synthesis.md"))

methods_lines <- c(
  "# Methods Summary", "",
  "The analysis uses weekly node-level observations on the frozen 25 x 25 km",
  "canonical grid covering Mexico and the established United States footprint",
  "south of 40 degrees north. `STRUCTURED_A3` is a penalized spatiotemporal",
  "hurdle model with a Bernoulli/logistic occurrence component and a zero-truncated",
  "negative-binomial conditional positive-count component. The frozen schema has",
  "34 predictors and is defined by the P0 production-freeze manifest.", "",
  "Qualification used retrospective rolling-origin evaluation at h=1, h=2, and",
  "h=3, with the canonical P1 transfer regimes, P2 calibration and count metrics,",
  "bounded P3 frontier/partition/count/initialization sensitivity, P4 uncertainty",
  "and support classification, P5 operational-contract testing, P5A issue-time",
  "environmental proxy comparison, and P6 hardening/restart/provenance validation.", "",
  "The operational environmental state is `E0_LAST_AVAILABLE`: the latest",
  "legitimately available environmental observation at issue time, held constant",
  "for h=1--3. Support classes use the unchanged P4 reference distribution and",
  "thresholds. Production output includes occurrence risk, conditional positive",
  "count, full hurdle expected count, uncertainty/support fields, warnings, and",
  "complete provenance. Primary results are read from tracked P1--P6 outputs.")
atomic_write_lines(methods_lines, file.path(output_root, "results", "methods_summary.md"))

results_lines <- c(
  "# Results Draft", "", "## Model and retrospective nowcast performance", "",
  headline_performance,
  "Performance was evaluated retrospectively with explicit horizon labels and",
  "common-week comparisons. The canonical source table reports calibration,",
  "discrimination, prevalence, and sample sizes for each horizon.", "",
  "## Environmental proxy validation", "", proxy_summary,
  "E0 was selected by the prespecified simplicity-first rule in P5A. This result",
  "supports prospective issue-time input construction with explicit proxy",
  "limitations; it does not turn E0 into a future environmental observation.", "",
  "## Frontier, counts, support, and production", "",
  "Frontier strata remain weaker and sparse, count predictions retain measurable",
  "bias, and P4 support flags identify heterogeneous environmental support. P6",
  "demonstrated deterministic replay, restartability, duplicate-run protection,",
  "and corruption detection without changing the scientific model.")
atomic_write_lines(results_lines, file.path(output_root, "results", "results_draft.md"))

limitations_lines <- c(
  "# Limitations Draft", "",
  "The qualification program does not remove the following limitations:", "",
  "1. Frontier/newly unoccupied positives are sparse and performance is weaker in those strata.",
  "2. U.S./regional outcome support is sparse, so geographic transport claims are limited to supported evidence.",
  "3. Conditional positive-count and full-hurdle expected-count predictions retain measurable count-process bias; they are not unbiased abundance estimates.",
  "4. A substantial proportion of rows are CAUTION or EXTRAPOLATIVE under the unchanged P4 support specification.",
  "5. Prospective operation relies on `E0_LAST_AVAILABLE`, a persistence-like issue-time environmental proxy rather than a future environmental forecast.",
  "6. Bounded regrouping and sensitivity analyses do not create a refitted spatial holdout.",
  "7. The framework is predictive and observational; predictor associations are not causal environmental effects.",
  "8. Source-product publication, revision, and vintage limitations remain part of the operational contract and replay interpretation.")
atomic_write_lines(limitations_lines, file.path(output_root, "results", "limitations_draft.md"))

discussion_lines <- c(
  "# Discussion Outline", "", "## Predictive utility", "",
  "Discuss the value of a spatially explicit weekly occurrence/count framework for",
  "short-horizon nowcasting, with metrics interpreted within the retrospective",
  "rolling-origin design.", "", "## Ecological interpretation", "",
  "Separate predictive associations from ecological mechanism. Do not interpret",
  "coefficients as causal environmental effects.", "", "## Operational use", "",
  "Describe E0_LAST_AVAILABLE as an issue-time environmental-context assumption and",
  "emphasize that every prediction retains support and uncertainty flags.", "",
  "## Limits of transport", "",
  "Discuss sparse frontier and regional support, extrapolative support, count bias,",
  "the absence of a refitted spatial holdout, and source-vintage limits.", "",
  "## Relationship to complementary frameworks", "",
  "Position the framework as complementary to other modeling approaches without",
  "direct comparative superiority claims.")
atomic_write_lines(discussion_lines, file.path(output_root, "results", "discussion_outline.md"))

software_lines <- c(
  "# Software Availability Statement", "",
  "The repository contains the frozen STRUCTURED_A3 model metadata, the P0--P6",
  "qualification records, the E0_LAST_AVAILABLE operational proxy contract,",
  "publication-build scripts, and reproducibility manifests. The canonical",
  "publication command is:", "", "```text",
  "Rscript analysis/p7_publication/scripts/build_publication_artifacts.R --repo-root .",
  "```", "",
  "The production command and runtime contract are documented in the P6 runbook",
  "and configuration. The release candidate distinguishes the scientific model",
  "version, operational contract version, and production software Git SHA. No",
  "unavailable public release or data license is implied by this draft.")
atomic_write_lines(software_lines, file.path(output_root, "results", "software_availability.md"))

data_lines <- c(
  "# Data Availability Statement", "",
  "The package contains publication summaries, derived metadata, source hashes,",
  "and machine-readable qualification outputs. Public environmental-source metadata",
  "may be referenced through canonical source/product records. Observation inputs",
  "and large Atlas-retained artifacts are not bundled when restricted, protected,",
  "or unnecessary for publication regeneration. The reproducibility manifest",
  "identifies tracked derived artifacts and hashes needed to audit the package",
  "without exposing protected paths or secrets.")
atomic_write_lines(data_lines, file.path(output_root, "results", "data_availability.md"))

reviewer_lines <- c(
  "# Publication Reviewer Checklist", "",
  "- [ ] Every primary value traces to a machine-readable P1--P6 artifact.",
  "- [ ] Every primary figure has source metadata and plotted-data provenance.",
  "- [ ] All required limitations appear in the manuscript components.",
  "- [ ] No future-data leakage is implied by the retrospective results.",
  "- [ ] E0_LAST_AVAILABLE is described as an issue-time proxy, not a true future environmental forecast.",
  "- [ ] No causal language is used for predictive associations.",
  "- [ ] Frontier, regional, count, and support/extrapolation caveats are explicit.",
  "- [ ] Scientific model and operational-contract versions are distinguished.",
  "- [ ] No claim of full U.S. validation, unbiased abundance prediction, superiority, or unrestricted production readiness appears.",
  "- [ ] Protected raw data and secrets are absent from the release candidate.")
atomic_write_lines(reviewer_lines, file.path(output_root, "results", "publication_reviewer_checklist.md"))

production_use_lines <- c(
  "# Qualified Production-Use Statement", "",
  "The qualified production configuration uses the frozen STRUCTURED_A3 model",
  "with the latest legitimately available environmental state (E0_LAST_AVAILABLE)",
  "held across the 1--3 week nowcast horizons. Each prediction emits occurrence",
  "and count uncertainty fields and unchanged P4 support classes. EXTRAPOLATIVE",
  "predictions remain available but are explicitly flagged; support warnings do",
  "not silently suppress or rewrite predictions. The configuration is qualified",
  "with the limitations documented in the P1--P6 reports and this package.")
atomic_write_lines(production_use_lines, file.path(output_root, "results", "production_use_statement.md"))

# Qualification summary and reproducibility manifest.
phase_reports <- c(
  P1 = "analysis/p1_production_validation/p1_validation_report.md",
  P2 = "analysis/p2_operational_nowcast/p2_operational_nowcast_report.md",
  P3 = "analysis/p3_robustness/p3_robustness_report.md",
  P4 = "analysis/p4_uncertainty_extrapolation/p4_uncertainty_extrapolation_report.md",
  P5 = "analysis/p5_operational_contract/p5_operational_contract_report.md",
  P5A = "analysis/p5a_environmental_proxy/p5a_environmental_proxy_report.md",
  P6 = "analysis/p6_production_hardening/p6_production_hardening_report.md")
summary_lines <- c(
  "# Model Qualification Summary", "",
  "This entry point summarizes the completed qualification program for the frozen",
  "`STRUCTURED_A3` candidate. The scientific model remains frozen; P1--P7",
  "artifacts are evaluation, operational-contract, hardening, and publication",
  "records around that immutable object.", "",
  paste0("Frozen model artifact SHA-256: `", p0$frozen_artifacts[[1L]]$sha256, "`"), "",
  "| Phase | Objective | Decision | Major finding | Canonical report |",
  "|---|---|---|---|---|",
  paste0("| P1 | Transfer validation | `", decision_values$P1,
         "` | Transfer and frontier limitations remain explicit. | [`P1 report`](../", phase_reports[["P1"]], ") |"),
  paste0("| P2 | Rolling-origin 1--3 week nowcast evaluation | `", decision_values$P2,
         "` | Occurrence performance and count behavior are characterized by horizon. | [`P2 report`](../", phase_reports[["P2"]], ") |"),
  paste0("| P3 | Bounded robustness | `", decision_values$P3,
         "` | Main conclusions are stable within bounded sensitivity designs, with sparse frontier/regional support. | [`P3 report`](../", phase_reports[["P3"]], ") |"),
  paste0("| P4 | Uncertainty and support | `", decision_values$P4,
         "` | Support and extrapolation are quantified and emitted as flags. | [`P4 report`](../", phase_reports[["P4"]], ") |"),
  paste0("| P5 | Operational contract | `", decision_values$P5,
         "` | Retrospective environmental inputs were not prospective without a proxy. | [`P5 report`](../", phase_reports[["P5"]], ") |"),
  paste0("| P5A | Issue-time proxy validation | `", decision_values$P5A,
         "` | E0_LAST_AVAILABLE provides a validated prospective proxy with limitations. | [`P5A report`](../", phase_reports[["P5A"]], ") |"),
  paste0("| P6 | Production hardening | `", decision_values$P6,
         "` | Deterministic, restartable operation is documented with tooling/source-vintage limitations. | [`P6 report`](../", phase_reports[["P6"]], ") |"),
  "", "## Qualified use", "",
  "Use is limited to short-horizon nowcasting under the E0_LAST_AVAILABLE issue-time",
  "environmental-context rule. Support classes and uncertainty fields must accompany",
  "predictions. Frontier and regional support, count bias, extrapolative support,",
  "proxy dependence, and causal-interpretation limitations remain active.")
atomic_write_lines(summary_lines, abs_path("docs/model_qualification_summary.md"))

git_sha <- tryCatch({
  out <- system2("git", c("-c", "safe.directory=*", "-C", repo_root,
                           "rev-parse", "HEAD"), stdout = TRUE, stderr = FALSE)
  if (length(out) == 0L) "UNKNOWN" else trimws(out[[1L]])
}, error = function(e) "UNKNOWN")
primary_tables <- data.frame(
  table_id = paste0("Table ", 1:5),
  path = file.path("analysis/p7_publication/tables", c(
    "table_1_data_model_specification.csv", "table_2_occurrence_performance.csv",
    "table_3_count_performance.csv", "table_4_proxy_comparison.csv",
    "table_5_limitation_summary.csv")),
  source_artifact = c(
    "config/production_model_freeze.json; config/p6_production_config.json",
    "analysis/p2_operational_nowcast/results/horizon_metrics.csv",
    "analysis/p2_operational_nowcast/results/count_metrics.csv",
    "analysis/p5a_environmental_proxy/results/occurrence_count_metrics.csv; analysis/p5a_environmental_proxy/results/paired_proxy_minus_realized.csv",
    "P1--P6 limitation artifacts"),
  generation_script = "analysis/p7_publication/scripts/build_publication_artifacts.R",
  stringsAsFactors = FALSE)
atomic_write_csv(primary_tables, file.path(output_root, "results", "table_manifest.csv"))

generated_files <- list.files(output_root, recursive = TRUE, full.names = TRUE)
generated_files <- generated_files[!dir.exists(generated_files)]
generated_files <- generated_files[!grepl("reproducibility_manifest\\.json$", generated_files)]
output_hashes <- setNames(vapply(generated_files, sha256_file, character(1L)),
                          vapply(generated_files, relpath, character(1L)))
manifest <- list(
  schema_version = "P7_REPRODUCIBILITY_1.0",
  canonical_main_sha_at_build = git_sha,
  frozen_model = list(model_id = p0$identity$model_id,
                      artifact = "analysis/structured_a3_evaluation/results/final_a3_model.json",
                      sha256 = p0$frozen_artifacts[[1L]]$sha256),
  operational_specification = list(
    proxy_id = p6_config$operational_contract$proxy_id,
    proxy_contract = "analysis/p5a_environmental_proxy/results/proxy_contract.json",
    proxy_contract_sha256 = sha256_file(abs_path("analysis/p5a_environmental_proxy/results/proxy_contract.json")),
    horizons = p6_config$operational_contract$horizons,
    support_specification = "analysis/p4_uncertainty_extrapolation/results/support_flag_specification.json",
    support_specification_sha256 = sha256_file(abs_path("analysis/p4_uncertainty_extrapolation/results/support_flag_specification.json")),
    production_schema = p6_config$output_contract$schema_version,
    production_config = "config/p6_production_config.json",
    production_config_sha256 = sha256_file(abs_path("config/p6_production_config.json"))),
  phase_decisions = decision_values,
  source_artifacts = split(source_hashes$sha256, source_hashes$artifact),
  primary_figures = split(figure_manifest$source_artifact, figure_manifest$figure_id),
  primary_tables = split(primary_tables$source_artifact, primary_tables$table_id),
  claim_registry = "analysis/p7_publication/results/claim_registry.csv",
  build_script = "analysis/p7_publication/scripts/build_publication_artifacts.R",
  generation_timestamp_utc = format(Sys.time(), tz = "UTC", usetz = TRUE),
  output_hashes_excluding_manifest = as.list(output_hashes),
  no_model_fitting = TRUE,
  protected_raw_data_bundled = FALSE)
manifest_path <- file.path(output_root, "results", "reproducibility_manifest.json")
atomic_write_json(manifest, manifest_path)

package_manifest <- list(
  package_type = "publication_release_candidate",
  version_identifier = "v1.0.0-rc1",
  final_release_tag_created = FALSE,
  generated_from_git_sha = git_sha,
  included = c("analysis/p7_publication/results", "analysis/p7_publication/figures",
               "analysis/p7_publication/tables", "analysis/p7_publication/supplement",
               "analysis/p7_publication/scripts", "docs/model_qualification_summary.md",
               "analysis/p7_publication/p7_prespecification.md"),
  excluded = c("protected raw data", "secrets", "unnecessary large Atlas intermediates",
               "machine-specific runtime paths"),
  manifest = "analysis/p7_publication/results/reproducibility_manifest.json")
atomic_write_json(package_manifest, file.path(output_root, "release_candidate", "package_manifest.json"))
atomic_write_lines(c(
  "# Publication Release Candidate", "",
  "This directory describes the non-final P7 release candidate (`v1.0.0-rc1`).",
  "No Git tag or final public release is created by P7.", "",
  "The candidate consists of generated publication artifacts, source hashes, the",
  "qualification summary, and the build script referenced by",
  "`release_candidate/package_manifest.json`. Protected raw data, secrets, and",
  "unnecessary large Atlas intermediates are excluded."),
  file.path(output_root, "release_candidate", "README.md"))

# Include the completed release-candidate directory in the output hash map while
# keeping the manifest itself excluded to avoid a self-hash cycle.
generated_files <- list.files(output_root, recursive = TRUE, full.names = TRUE)
generated_files <- generated_files[!dir.exists(generated_files)]
generated_files <- generated_files[!grepl("reproducibility_manifest\\.json$", generated_files)]
output_hashes <- setNames(vapply(generated_files, sha256_file, character(1L)),
                          vapply(generated_files, relpath, character(1L)))
manifest$output_hashes_excluding_manifest <- as.list(output_hashes)
atomic_write_json(manifest, manifest_path)

expected_outputs <- c(
  file.path(output_root, "results", "claim_registry.csv"),
  file.path(output_root, "results", "results_synthesis.md"),
  file.path(output_root, "results", "reproducibility_manifest.json"),
  file.path(output_root, "results", "figure_manifest.csv"),
  file.path(output_root, "tables", c("table_1_data_model_specification.csv",
                                     "table_2_occurrence_performance.csv",
                                     "table_3_count_performance.csv",
                                     "table_4_proxy_comparison.csv",
                                     "table_5_limitation_summary.csv")),
  figure_paths, abs_path("docs/model_qualification_summary.md"))
missing_outputs <- expected_outputs[!file.exists(expected_outputs)]
if (length(missing_outputs) > 0L) stopf("P7 build incomplete; missing: %s",
                                       paste(vapply(missing_outputs, relpath, character(1L)), collapse = ", "))

# Exact source-derived consistency checks before display rounding are represented
# in the table values and claim registry. The table check confirms the rendered
# values match the canonical P2 rows.
table2_check <- utils::read.csv(file.path(output_root, "tables", "table_2_occurrence_performance.csv"),
                                stringsAsFactors = FALSE)
if (!identical(fmt4(table2_check$brier), fmt4(p2_all$brier)) ||
    !identical(fmt4(table2_check$auprc), fmt4(p2_all$auprc))) {
  stopf("Table 2 numerical consistency check failed against P2 source")
}
claim_check <- utils::read.csv(file.path(output_root, "results", "claim_registry.csv"),
                               stringsAsFactors = FALSE)
if (nrow(claim_check) != 8L || !identical(as.character(claim_check$claim_id), LETTERS[1:8])) {
  stopf("Claim registry completeness check failed")
}
cat("P7_PUBLICATION_BUILD_COMPLETE\n")
cat(sprintf("generated_from_git_sha=%s\n", git_sha))
cat(sprintf("output_root=%s\n", relpath(output_root)))
cat(sprintf("primary_claims=%d\n", nrow(claim_registry)))
cat(sprintf("primary_figures=%d\n", nrow(figure_manifest)))
cat(sprintf("primary_tables=%d\n", nrow(primary_tables)))
