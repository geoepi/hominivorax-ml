test_that("P7F final figure package inventory is complete", {
  root <- test_path("..", "..", "analysis", "p7f_final_figures")
  disposition <- utils::read.csv(
    file.path(root, "results", "figure_disposition.csv"),
    stringsAsFactors = FALSE,
    check.names = FALSE
  )

  expect_equal(sum(disposition$disposition == "MAIN"), 6)
  expect_true(all(c("F1", "F2", "F3", "F4", "F5", "F6") %in% disposition$figure_id))
  expect_equal(disposition$disposition[disposition$figure_id == "A2"], "ARCHIVE")
  expect_equal(disposition$disposition[disposition$figure_id == "S6"], "SUPPLEMENT")

  decision <- jsonlite::fromJSON(file.path(root, "results", "decision.json"))
  expect_identical(decision$decision, "P7F_FINAL_FIGURE_SET_SUPPORTED_WITH_LIMITATIONS")
  expect_true(isTRUE(decision$no_model_fitting))

  validation <- jsonlite::fromJSON(file.path(root, "results", "validation_results.json"))
  expect_identical(validation$status, "P7F_VALIDATION_PASSED")
  expect_true(file.exists(file.path(root, "p7f_prespecification.md")))
  expect_true(file.exists(file.path(root, "captions", "final_captions.md")))
})
