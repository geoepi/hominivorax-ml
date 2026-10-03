testthat::test_that("Task 2E production output satisfies the refreshed contract", {
  output_root <- Sys.getenv(
    "STGNN_TASK2E_OUTPUT",
    "/project/disease_ecology/STGNN-output/revised_model_data"
  )
  testthat::skip_if_not(dir.exists(output_root))
  testthat::skip_if_not_installed("arrow")
  testthat::skip_if_not_installed("jsonlite")

  manifest <- jsonlite::fromJSON(
    file.path(output_root, "manifests", "revised_production_manifest.json"),
    simplifyVector = FALSE
  )
  nodes <- arrow::read_parquet(file.path(output_root, "raw", "nodes.parquet"))
  edges <- arrow::read_parquet(file.path(output_root, "raw", "edges_queen.parquet"))
  splits <- jsonlite::fromJSON(
    file.path(output_root, "splits", "temporal_splits.json"),
    simplifyVector = FALSE
  )

  testthat::expect_equal(nrow(nodes), 10037L)
  testthat::expect_equal(nodes$model_node_id, 0:10036)
  testthat::expect_equal(nrow(edges), 77614L)
  testthat::expect_equal(as.integer(unlist(manifest$array_shapes$dynamic_features)), c(81L, 10037L, 12L))
  testthat::expect_equal(as.integer(unlist(manifest$array_shapes$static_features)), c(10037L, 10L))
  testthat::expect_equal(as.integer(unlist(manifest$array_shapes$targets_count)), c(81L, 10037L))
  testthat::expect_equal(as.integer(unlist(manifest$array_shapes$targets_presence)), c(81L, 10037L))
  testthat::expect_equal(as.integer(manifest$response$positive_node_weeks), 14848L)
  testthat::expect_equal(as.integer(manifest$response$us_positive_node_weeks), 30L)
  testthat::expect_equal(as.integer(splits$response_week_count), 81L)
  testthat::expect_equal(as.integer(unlist(splits$final_test$indices)), 68:80)
  testthat::expect_false(isTRUE(manifest$terminal_holdout_metrics_calculated))
})
