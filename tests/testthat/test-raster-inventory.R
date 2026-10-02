source(testthat::test_path("..", "..", "R", "date_utils.R"))
source(testthat::test_path("..", "..", "R", "raster_inventory.R"))

testthat::test_that("weekly filename parsing recognizes ISO weeks and dates", {
  iso <- parse_week_identifier("era5_mintemp_2024-W01.tif")
  date <- parse_week_identifier("era5_mintemp_20240108.tif")
  unknown <- parse_week_identifier("README.tif")
  testthat::expect_equal(iso$week_id, "2024-W01")
  testthat::expect_equal(date$week_id, "2024-W02")
  testthat::expect_true(is.na(unknown$week_id))
})

testthat::test_that("week inventory identifies missing and duplicate weeks", {
  parsed <- data.frame(
    filename = c("a_2024-W01.tif", "b_2024-W01.tif", "c_2024-W03.tif"),
    week_id = c("2024-W01", "2024-W01", "2024-W03"),
    iso_year = c(2024L, 2024L, 2024L),
    iso_week = c(1L, 1L, 3L),
    parse_method = rep("ISO year-week", 3L),
    stringsAsFactors = FALSE
  )
  summary <- summarize_week_identifiers(parsed)
  testthat::expect_equal(summary$duplicate_ids, "2024-W01")
  testthat::expect_equal(summary$missing_ids, "2024-W02")
})
