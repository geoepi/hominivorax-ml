source(testthat::test_path("..", "..", "R", "date_utils.R"))

testthat::test_that("strict date parsing rejects malformed and impossible dates", {
  parsed <- parse_strict_date(c("2024-01-01", "2024-02-30", "2024/01/01", NA))
  testthat::expect_equal(as.character(parsed[1]), "2024-01-01")
  testthat::expect_true(is.na(parsed[2]))
  testthat::expect_true(is.na(parsed[3]))
  testthat::expect_true(is.na(parsed[4]))
})

testthat::test_that("ISO week and target filtering are deterministic", {
  dates <- as.Date(c("2023-12-31", "2024-01-01", "2024-01-07", "2024-01-08"))
  testthat::expect_equal(iso_week_id(dates), c("2023-W52", "2024-W01", "2024-W01", "2024-W02"))
  testthat::expect_equal(
    filter_target_period(dates),
    c(FALSE, TRUE, TRUE, TRUE)
  )
})

testthat::test_that("latest complete week ends on the latest represented Sunday", {
  result <- latest_complete_iso_week(as.Date(c("2024-01-01", "2024-01-14")))
  testthat::expect_equal(as.character(result$candidate_analysis_end), "2024-01-14")
  testthat::expect_equal(result$latest_complete_iso_week, "2024-W02")
  testthat::expect_equal(result$target_week_count, 2L)
})

testthat::test_that("a partial latest week rolls back to the preceding Sunday", {
  result <- latest_complete_iso_week(as.Date(c("2024-01-01", "2024-01-12")))
  testthat::expect_equal(as.character(result$candidate_analysis_end), "2024-01-07")
  testthat::expect_equal(result$latest_complete_iso_week, "2024-W01")
})
