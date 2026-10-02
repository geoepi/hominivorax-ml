source(testthat::test_path("..", "..", "R", "canonical_mask.R"))
source(testthat::test_path("..", "..", "R", "livestock_alignment.R"))

testthat::test_that("canonical mask is a cellwise intersection", {
  testthat::skip_if_not_installed("terra")
  first <- terra::rast(nrows = 2, ncols = 2, xmin = 0, xmax = 2, ymin = 0, ymax = 2,
                       crs = "EPSG:3857")
  second <- first
  terra::values(first) <- c(1, 1, 1, 1)
  terra::values(second) <- c(1, NA, 1, NA)
  first_path <- tempfile(fileext = ".tif")
  second_path <- tempfile(fileext = ".tif")
  terra::writeRaster(first, first_path, overwrite = TRUE)
  terra::writeRaster(second, second_path, overwrite = TRUE)
  result <- canonical_mask_from_paths(c(first_path, second_path))
  testthat::expect_equal(sum(result$mask), 2L)
  testthat::expect_equal(result$dropped_cell_count_by_input, c(2L, 0L))
})

testthat::test_that("density alignment uses exact overlap areas and conserves covered mass", {
  testthat::skip_if_not_installed("terra")
  source_raster <- terra::rast(nrows = 2, ncols = 2, xmin = 0, xmax = 2, ymin = 0, ymax = 2)
  terra::values(source_raster) <- c(1, 3, 5, 7)
  source_path <- tempfile(fileext = ".tif")
  terra::writeRaster(source_raster, source_path, overwrite = TRUE)
  destination <- terra::rast(nrows = 1, ncols = 1, xmin = 0, xmax = 2, ymin = 0, ymax = 2)
  result <- area_weighted_density_to_template(source_path, destination)
  testthat::expect_equal(result$values, 4, tolerance = 1e-12)
  testthat::expect_equal(result$coverage_fraction, 1, tolerance = 1e-12)
  testthat::expect_equal(result$source_mass, 16, tolerance = 1e-12)
  testthat::expect_equal(result$values * result$covered_area, result$source_mass,
                         tolerance = 1e-12)
})
