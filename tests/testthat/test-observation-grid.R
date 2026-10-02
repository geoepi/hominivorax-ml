source(testthat::test_path("..", "..", "R", "date_utils.R"))
source(testthat::test_path("..", "..", "R", "grid_graph.R"))
source(testthat::test_path("..", "..", "R", "observation_grid_diagnostic.R"))

testthat::test_that("observation records are classified and aggregated without source mutation", {
  testthat::skip_if_not_installed("terra")
  testthat::skip_if_not_installed("data.table")

  template_path <- tempfile("stgnn-template-", fileext = ".tif")
  template <- terra::rast(
    nrows = 2L, ncols = 2L,
    xmin = 0, xmax = 2, ymin = 0, ymax = 2,
    crs = "EPSG:4326"
  )
  terra::values(template) <- c(1, NA, 1, 1)
  terra::writeRaster(template, template_path, overwrite = TRUE)
  nodes <- node_table_from_terra(template)

  observation_path <- tempfile("stgnn-observations-", fileext = ".csv")
  observations <- data.frame(
    lon = c(0.5, 1.5, 1.5, 3.0),
    lat = c(1.5, 1.5, 0.5, 0.5),
    date = rep("2024-01-14", 4L)
  )
  utils::write.csv(observations, observation_path, row.names = FALSE)
  before <- unname(tools::md5sum(observation_path))

  result <- observation_to_grid_diagnostic(
    observation_path = observation_path,
    template_path = template_path,
    nodes = nodes
  )

  after <- unname(tools::md5sum(observation_path))
  testthat::expect_equal(before, after)
  testthat::expect_equal(result$total_post_2024_observations, 4L)
  testthat::expect_equal(result$successfully_assigned_observations, 2L)
  testthat::expect_equal(result$outside_extent_observations, 1L)
  testthat::expect_equal(result$masked_cell_observations, 1L)
  testthat::expect_equal(result$positive_node_weeks, 2L)
  testthat::expect_equal(result$number_model_nodes, 3L)
})
