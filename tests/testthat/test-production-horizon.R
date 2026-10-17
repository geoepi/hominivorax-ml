source(testthat::test_path("..", "..", "R", "date_utils.R"))
source(testthat::test_path("..", "..", "R", "raster_inventory.R"))
source(testthat::test_path("..", "..", "R", "production_horizon.R"))

testthat::test_that("historical 133-week horizon remains reproducible", {
  horizon <- production_week_horizon("2024-01-01", "2026-07-19", 52L)
  testthat::expect_length(horizon$target_week_ids, 133L)
  testthat::expect_length(horizon$history_week_ids, 185L)
  testthat::expect_equal(horizon$target_week_ids[[1L]], "2024-W01")
  testthat::expect_equal(tail(horizon$target_week_ids, 1L), "2026-W29")
  testthat::expect_true(all(as.integer(format(horizon$target_dates, "%u")) == 1L))
})

testthat::test_that("extended horizons are derived from the supplied endpoint", {
  horizon <- production_week_horizon("2024-01-01", "2026-10-05", 52L)
  testthat::expect_gt(length(horizon$target_week_ids), 133L)
  testthat::expect_equal(tail(horizon$target_week_ids, 1L), "2026-W41")
  testthat::expect_equal(length(horizon$history_week_ids), length(horizon$target_week_ids) + 52L)
})

testthat::test_that("missing environmental weeks fail explicitly", {
  root <- tempfile("environment-")
  dir.create(file.path(root, "era5_mintemp", "weekly"), recursive = TRUE)
  file.create(file.path(root, "era5_mintemp", "weekly", "era5_mintemp_2024-W01.tif"))
  testthat::expect_error(
    resolve_production_week_files("era5_mintemp", root, c("2024-W01", "2024-W02")),
    "missing environmental weeks"
  )
})
