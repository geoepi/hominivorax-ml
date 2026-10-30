testthat::test_that("P7 publication package is traceable and complete", {
  root <- normalizePath(testthat::test_path("..", ".."), mustWork = TRUE)
  p7 <- file.path(root, "analysis", "p7_publication")
  testthat::expect_true(file.exists(file.path(p7, "p7_prespecification.md")))
  testthat::expect_true(file.exists(file.path(root, "docs", "model_qualification_summary.md")))

  p0 <- jsonlite::fromJSON(file.path(root, "config", "production_model_freeze.json"),
                           simplifyVector = FALSE)
  p6 <- jsonlite::fromJSON(file.path(root, "config", "p6_production_config.json"),
                           simplifyVector = FALSE)
  testthat::expect_identical(p0$identity$model_id, "STRUCTURED_A3")
  testthat::expect_length(p0$predictor_specification$ordered_predictors, 34L)
  testthat::expect_identical(p6$operational_contract$proxy_id, "E0_LAST_AVAILABLE")
  testthat::expect_identical(p6$output_contract$schema_version, "P6_OUTPUT_1.0")

  claims <- utils::read.csv(file.path(p7, "results", "claim_registry.csv"),
                            stringsAsFactors = FALSE)
  testthat::expect_equal(nrow(claims), 8L)
  testthat::expect_identical(claims$claim_id, LETTERS[1:8])
  testthat::expect_true(all(nzchar(claims$source_artifact)))
  testthat::expect_true(all(nzchar(claims$exact_value)))

  tables <- utils::read.csv(file.path(p7, "results", "table_manifest.csv"),
                            stringsAsFactors = FALSE)
  testthat::expect_equal(nrow(tables), 5L)
  testthat::expect_true(all(file.exists(file.path(root, tables$path))))
  figure_manifest <- utils::read.csv(file.path(p7, "results", "figure_manifest.csv"),
                                     stringsAsFactors = FALSE)
  testthat::expect_equal(nrow(figure_manifest), 8L)
  testthat::expect_true(all(grepl("^analysis/p7_publication/figures/", figure_manifest$path)))
  testthat::expect_true(all(file.exists(file.path(root, figure_manifest$path))))
  testthat::expect_true(all(nzchar(figure_manifest$generation_script)))

  manifest <- jsonlite::fromJSON(file.path(p7, "results", "reproducibility_manifest.json"),
                                 simplifyVector = FALSE)
  testthat::expect_identical(manifest$schema_version, "P7_REPRODUCIBILITY_1.0")
  testthat::expect_identical(manifest$frozen_model$sha256,
                             "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e")
  testthat::expect_identical(manifest$operational_specification$proxy_id,
                             "E0_LAST_AVAILABLE")
  testthat::expect_true(isTRUE(manifest$no_model_fitting))
  testthat::expect_false(isTRUE(manifest$protected_raw_data_bundled))
  testthat::expect_true(length(manifest$output_hashes_excluding_manifest) > 10L)

  package_manifest <- jsonlite::fromJSON(file.path(p7, "release_candidate", "package_manifest.json"),
                                          simplifyVector = FALSE)
  testthat::expect_false(isTRUE(package_manifest$final_release_tag_created))
  package_files <- list.files(file.path(p7, "release_candidate"), recursive = TRUE,
                              full.names = FALSE)
  testthat::expect_false(any(grepl("(^|/)(raw|secrets?)(/|$)|\\.(npy|parquet)$",
                                   package_files, ignore.case = TRUE)))
})
