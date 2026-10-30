#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(jsonlite)
  library(digest)
})

repo_root <- normalizePath(getwd(), winslash = "/", mustWork = TRUE)
root <- file.path(repo_root, "analysis", "p7e_rolling_forecasts")
results <- file.path(root, "results")
failures <- character()
check <- function(ok, message) if (!ok) failures <<- c(failures, message)
hash_file <- function(path) digest(path, algo = "sha256", file = TRUE)
week_num <- function(x) as.integer(sub(".*-W", "", x))

required <- c(
  "rolling_occurrence_forecasts.csv", "rolling_count_forecasts.csv",
  "rolling_forecast_coverage.csv", "observed_occurrence_history.csv",
  "atlas_rolling_forecast_manifest.json", "rendering_contract.json",
  "figure_source_registry.csv", "decision.json"
)
check(all(file.exists(file.path(results, required))), "required P7E result file is missing")
if (length(failures) > 0) stop(paste(failures, collapse = "\n"))

occ <- read.csv(file.path(results, "rolling_occurrence_forecasts.csv"), stringsAsFactors = FALSE, check.names = FALSE)
cnt <- read.csv(file.path(results, "rolling_count_forecasts.csv"), stringsAsFactors = FALSE, check.names = FALSE)
cov <- read.csv(file.path(results, "rolling_forecast_coverage.csv"), stringsAsFactors = FALSE, check.names = FALSE)
hist <- read.csv(file.path(results, "observed_occurrence_history.csv"), stringsAsFactors = FALSE, check.names = FALSE)
manifest <- fromJSON(file.path(results, "atlas_rolling_forecast_manifest.json"), simplifyVector = TRUE)
contract <- fromJSON(file.path(results, "rendering_contract.json"), simplifyVector = TRUE)
registry <- read.csv(file.path(results, "figure_source_registry.csv"), stringsAsFactors = FALSE, check.names = FALSE)

origins <- sprintf("2026-W%02d", 16:36)
check(identical(sort(unique(occ$issue_week)), origins), "origin weeks are not exactly 2026-W16 through W36")
check(identical(sort(unique(cnt$issue_week)), origins), "count origin weeks are not exactly 2026-W16 through W36")
check(nrow(occ) == 63 && nrow(cnt) == 63, "forecast aggregation does not contain exactly 63 rows")
check(identical(sort(unique(occ$horizon)), 1:3), "occurrence horizons are not exactly 1, 2, 3")
check(identical(sort(unique(cnt$horizon)), 1:3), "count horizons are not exactly 1, 2, 3")
check(!anyDuplicated(occ[c("issue_week", "horizon")]), "duplicate occurrence issue-week/horizon rows")
check(!anyDuplicated(cnt[c("issue_week", "horizon")]), "duplicate count issue-week/horizon rows")
check(all(occ$target_week == sprintf("2026-W%02d", week_num(occ$issue_week) + occ$horizon)), "occurrence target chronology mismatch")
check(all(cnt$target_week == sprintf("2026-W%02d", week_num(cnt$issue_week) + cnt$horizon)), "count target chronology mismatch")
check(all(cov$focal_cells == 1689 & cov$focal_rows == 1689), "focal coverage is not complete 1,689 cells for every forecast")
check(as.integer(manifest$focal_cells) == 1689, "manifest focal-cell count is not 1,689")
check(as.integer(manifest$forecast_row_count) == 63, "manifest forecast-row count is not 63")
check(all(hist$focal_cells == 1689), "observed history lacks complete focal coverage")
check(identical(range(hist$target_week), c("2026-W17", "2026-W39")), "observed history range is not W17-W39")
check(all(abs(occ$forecast_error - (occ$expected_positive_cells - occ$observed_positive_cells)) < 1e-10), "occurrence signed error formula mismatch")
check(all(abs(occ$absolute_error - abs(occ$forecast_error)) < 1e-10), "occurrence absolute error formula mismatch")
check(all(abs(cnt$forecast_error - (cnt$expected_total_count - cnt$observed_total_count)) < 1e-10), "count signed error formula mismatch")
check(all(abs(cnt$absolute_error - abs(cnt$forecast_error)) < 1e-10), "count absolute error formula mismatch")
check(identical(as.character(contract$uncertainty_status), "NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS"), "uncertainty status is not the canonical unsupported state")
check(isTRUE(contract$no_uncertainty_ribbon), "contract does not prohibit an uncertainty ribbon")
check(isFALSE(contract$model_fitting), "contract does not state that model fitting is disabled")
check(nrow(registry) == 6, "source registry does not contain all six P7E panels")
check(all(file.exists(file.path(root, registry$output_file))), "registered figure output is missing")
check(all(vapply(seq_len(nrow(registry)), function(i) hash_file(file.path(root, registry$output_file[i])) == registry$output_hash[i], logical(1))), "registered figure hash mismatch")

generator_text <- paste(readLines(file.path(root, "scripts", "generate_p7e_rolling_forecasts.R"), warn = FALSE), collapse = "\n")
check(!grepl("fit_fixed_theta|glmnet|recalibrat(e|ion)\\s*\\(", generator_text, ignore.case = TRUE), "figure generator contains model-fitting or recalibration code")

if (length(failures) > 0) {
  write(toJSON(list(status = "FAILED", failures = failures), auto_unbox = TRUE, pretty = TRUE), file.path(results, "validation_results.json"))
  stop(paste(failures, collapse = "\n"))
}
write(toJSON(list(status = "P7E_VALIDATION_PASSED", checks = 24), auto_unbox = TRUE, pretty = TRUE), file.path(results, "validation_results.json"))
cat("P7E_VALIDATION_PASSED\n")
