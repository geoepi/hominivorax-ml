testthat::test_that("P7A figure and table design audit is source-traceable", {
  root <- normalizePath(testthat::test_path("..", ".."), mustWork = TRUE)
  p7a <- file.path(root, "analysis", "p7a_figure_design")
  results <- file.path(p7a, "results")

  testthat::expect_true(file.exists(file.path(p7a, "p7a_prespecification.md")))
  testthat::expect_true(file.exists(file.path(p7a, "p7a_figure_design_report.md")))

  decision <- jsonlite::fromJSON(file.path(results, "decision.json"), simplifyVector = FALSE)
  testthat::expect_identical(decision$decision, "P7A_FIGURE_PLAN_SUPPORTED_WITH_LIMITATIONS")
  testthat::expect_true(isTRUE(decision$no_model_fitting))
  testthat::expect_true(isTRUE(decision$no_new_scientific_analysis))

  focal <- jsonlite::fromJSON(file.path(results, "mexico_texas_focal_region.json"), simplifyVector = FALSE)
  testthat::expect_identical(focal$region_id, "MEXICO_TEXAS_BORDER_CORRIDOR")
  testthat::expect_identical(focal$crs, "EPSG:4326")
  testthat::expect_equal(focal$canonical_cells, 1689L)
  testthat::expect_identical(unlist(focal$map_weeks), c("2026-W17", "2026-W22", "2026-W27", "2026-W32", "2026-W37"))
  testthat::expect_identical(focal$recommended_time_series[[2L]], "expected_positive_cell_burden=sum_i p_occurrence")

  weekly <- utils::read.csv(file.path(results, "focal_region_weekly_summary.csv"), stringsAsFactors = FALSE)
  testthat::expect_equal(nrow(weekly), 21L)
  testthat::expect_true(all(weekly$cells == 1689L))
  testthat::expect_identical(weekly$target_week[c(1L, 21L)], c("2026-W17", "2026-W37"))

  predictors <- utils::read.csv(file.path(results, "predictor_contribution_audit.csv"), stringsAsFactors = FALSE)
  testthat::expect_equal(nrow(predictors), 34L)
  testthat::expect_true(all(nzchar(predictors$coefficient_comparability)))
  testthat::expect_true(any(grepl("NOT_COMPARABLE", predictors$coefficient_comparability)))
  testthat::expect_true(all(grepl("not causal", predictors$interpretation, fixed = TRUE)))

  figures <- utils::read.csv(file.path(results, "figure_priority.csv"), stringsAsFactors = FALSE)
  testthat::expect_equal(nrow(figures), 10L)
  testthat::expect_equal(sum(figures$recommendation == "MAIN_REQUIRED"), 4L)
  testthat::expect_equal(sum(figures$recommendation == "SUPPLEMENT"), 4L)

  tables <- utils::read.csv(file.path(results, "table_priority.csv"), stringsAsFactors = FALSE)
  testthat::expect_equal(nrow(tables), 7L)
  testthat::expect_true(all(nzchar(tables$recommendation)))

  source_audit <- utils::read.csv(file.path(results, "focal_region_source_audit.csv"), stringsAsFactors = FALSE)
  testthat::expect_true(nrow(source_audit) >= 10L)
  testthat::expect_true(any(source_audit$status == "LIMITED"))
  testthat::expect_true(any(grepl("Atlas", source_audit$source_artifact, fixed = TRUE)))

  script_text <- paste(readLines(file.path(p7a, "scripts", "audit_p7a_design.R"), warn = FALSE), collapse = "\n")
  testthat::expect_false(grepl("\\b(shap|permutation importance|partial dependence|ale|leave-one-predictor-out)\\b", script_text, ignore.case = TRUE, perl = TRUE))
})
