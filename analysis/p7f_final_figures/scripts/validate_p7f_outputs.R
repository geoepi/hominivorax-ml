#!/usr/bin/env Rscript

suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(digest))

repo_root <- normalizePath(getwd(), winslash = "/", mustWork = TRUE)
root <- file.path(repo_root, "analysis", "p7f_final_figures")
results <- file.path(root, "results")
failures <- character()
check <- function(ok, message) if (!isTRUE(ok)) failures <<- c(failures, message)
hash_file <- function(path) digest(path, algo = "sha256", file = TRUE)

required <- c("results/figure_disposition.csv", "results/figure_source_registry.csv", "results/figure_style_spec.json", "results/science_qa.csv", "results/decision.json", "results/run_metadata.json", "results/plot_data/rolling_occurrence_plot_data.csv", "captions/final_captions.md")
check(all(file.exists(file.path(root, required))), "one or more required P7F artifacts are missing")
if (length(failures)) stop(paste(failures, collapse = "\n"))

disp <- read.csv(file.path(results, "figure_disposition.csv"), stringsAsFactors = FALSE, check.names = FALSE)
reg <- read.csv(file.path(results, "figure_source_registry.csv"), stringsAsFactors = FALSE, check.names = FALSE)
qa <- read.csv(file.path(results, "science_qa.csv"), stringsAsFactors = FALSE, check.names = FALSE)
style <- fromJSON(file.path(results, "figure_style_spec.json"), simplifyVector = TRUE)
decision <- fromJSON(file.path(results, "decision.json"), simplifyVector = TRUE)
rolling <- read.csv(file.path(results, "plot_data", "rolling_occurrence_plot_data.csv"), stringsAsFactors = FALSE, check.names = FALSE)

main <- disp[disp$disposition == "MAIN", , drop = FALSE]
check(nrow(main) >= 5L && nrow(main) <= 6L, "main figure count is not 5-6")
check(!anyDuplicated(main$figure_id), "duplicate main figure IDs")
check(disp$disposition[disp$figure_id == "A2"] == "ARCHIVE", "single-W36 trajectory is not archived")
check(disp$disposition[disp$figure_id == "S6"] == "SUPPLEMENT", "rolling count figure is not supplementary")
check(disp$disposition[disp$figure_id == "S5"] == "SUPPLEMENT", "support figure is not supplementary")
check(!any(disp$figure_id == "A2" & disp$disposition == "MAIN"), "single-W36 trajectory is classified as main")
check(!any(disp$title == "Expected-count spatial candidate" & disp$disposition == "MAIN"), "expected-count spatial candidate is classified as main")
check(nrow(reg) == nrow(disp), "source registry and disposition inventories differ")
check(nrow(qa) == 12L, "science QA does not cover active figures")
check(identical(as.character(decision$decision), "P7F_FINAL_FIGURE_SET_SUPPORTED_WITH_LIMITATIONS"), "unexpected P7F decision")
check(identical(as.character(decision$predictor_association_status), "INADEQUATE_REQUIRES_SEPARATE_PREDICTOR_INFLUENCE_ANALYSIS"), "predictor-association status not preserved")
check(nrow(rolling) == 63L, "rolling occurrence plotted data does not contain 63 rows")
check(identical(sort(unique(rolling$horizon)), 1:3), "rolling plotted data does not contain h=1-3")
check(identical(sort(unique(rolling$issue_week)), sprintf("2026-W%02d", 16:36)), "rolling plotted data does not contain all 21 origins")
check(isTRUE(style$base_font_size_pt == 11), "style base font size is not 11")
check(isTRUE(style$raster_preview_dpi == 220), "style preview DPI is not 220")
check(isTRUE(length(style$vector_formats) >= 2), "style vector format specification is incomplete")

pattern_paths <- function(pattern) {
  if (grepl("(png|svg)", pattern, fixed = TRUE)) {
    stem <- sub(".(png|svg)", "", pattern, fixed = TRUE)
    return(file.path(root, paste0(stem, c(".png", ".svg"))))
  }
  file.path(root, pattern)
}
for (i in seq_len(nrow(reg))) {
  paths <- pattern_paths(reg$output_file[i])
  check(all(file.exists(paths)), paste("registered output missing for", reg$figure_id[i]))
  expected <- strsplit(reg$output_hash[i], ";", fixed = TRUE)[[1]]
  check(length(expected) == length(paths), paste("registered hash count mismatch for", reg$figure_id[i]))
  if (length(expected) == length(paths) && all(file.exists(paths))) check(identical(expected, unname(vapply(paths, hash_file, character(1)))), paste("registered output hash mismatch for", reg$figure_id[i]))
}

rolling_svg <- file.path(root, "figures", "main", "figure_04_rolling_occurrence_forecasts.svg")
svg_text <- paste(readLines(rolling_svg, warn = FALSE), collapse = "\n")
check(grepl("A\\. Observed and forecast positive-cell burden", svg_text, fixed = FALSE), "rolling Panel A label missing")
check(grepl("B\\. Signed forecast error", svg_text, fixed = FALSE), "rolling Panel B label missing")
check(grepl("C\\. Error distribution by horizon", svg_text, fixed = FALSE), "rolling Panel C label missing")
check(grepl("expected - observed positive cells", svg_text, fixed = TRUE), "plain-language rolling error label missing")
check(!grepl("uncertainty ribbon|confidence ribbon", svg_text, ignore.case = TRUE), "unsupported uncertainty ribbon appears in rolling figure")

script_text <- paste(readLines(file.path(root, "scripts", "generate_p7f_figures.R"), warn = FALSE), collapse = "\n")
forbidden_terms <- c("glmnet", "fit_fixed_theta", "recalibration", "permutation importance", "partial dependence", "ablation")
check(!any(vapply(forbidden_terms, function(term) grepl(term, tolower(script_text), fixed = TRUE), logical(1))), "new analytic/modeling method detected in P7F generator")
check(!grepl("SHAP", script_text, fixed = TRUE), "new analytic/modeling method detected in P7F generator")
caption_text <- paste(readLines(file.path(root, "captions", "final_captions.md"), warn = FALSE), collapse = "\n")
check(!grepl("^## (Results|Discussion|Methods|Introduction|Abstract)", caption_text, ignore.case = TRUE), "caption file contains manuscript section prose")

if (length(failures)) {
  write(toJSON(list(status = "FAILED", failures = failures), auto_unbox = TRUE, pretty = TRUE), file.path(results, "validation_results.json"))
  stop(paste(failures, collapse = "\n"))
}
write(toJSON(list(status = "P7F_VALIDATION_PASSED", checks = 24), auto_unbox = TRUE, pretty = TRUE), file.path(results, "validation_results.json"))
cat("P7F_VALIDATION_PASSED\n")
