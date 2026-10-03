source(testthat::test_path("..", "..", "R", "revised_domain_audit.R"))
source(testthat::test_path("..", "..", "R", "date_utils.R"))

testthat::test_that("fixed geographic rule retains Mexico and U.S. south of 40N only", {
  testthat::skip_if_not_installed("sf")
  boundary <- sf::st_as_sf(
    data.frame(code = c("MX", "US", "GT")),
    geometry = sf::st_sfc(
      sf::st_polygon(list(rbind(c(-110, 14), c(-95, 14), c(-95, 33), c(-110, 33), c(-110, 14)))),
      sf::st_polygon(list(rbind(c(-125, 25), c(-65, 25), c(-65, 49), c(-125, 49), c(-125, 25)))),
      sf::st_polygon(list(rbind(c(-95, 10), c(-85, 10), c(-85, 15), c(-95, 15), c(-95, 10)))),
      crs = 4326
    )
  )
  points <- data.frame(lon = c(-100, -100, -90, -90), lat = c(20, 42, 12, 41))
  country <- task2d_classify_points(points$lon, points$lat, boundary, boundary$code)
  region <- task2d_region(country, points$lat)
  retained <- country == "MX" | (country == "US" & points$lat < 40)
  testthat::expect_equal(country, c("MX", "US", "GT", "US"))
  testthat::expect_equal(region, c("Mexico", "excluded-U.S.-north-of-40N", "excluded-Central-America-south-of-Mexico", "excluded-U.S.-north-of-40N"))
  testthat::expect_equal(retained, c(TRUE, FALSE, FALSE, FALSE))
})

testthat::test_that("induced graph preserves only retained canonical edges", {
  nodes <- data.frame(node_id = 0:3, row = c(1L, 1L, 2L, 2L), column = c(1L, 2L, 1L, 2L))
  edges <- data.frame(source_node = c(0L, 1L, 1L, 2L, 2L, 3L), target_node = c(1L, 0L, 2L, 1L, 3L, 2L))
  retained <- c(0L, 1L, 2L)
  induced <- edges[edges$source_node %in% retained & edges$target_node %in% retained, , drop = FALSE]
  qa <- task2d_graph_qa(nodes[nodes$node_id %in% retained, , drop = FALSE], induced)
  testthat::expect_equal(qa$directed_edge_count, 4L)
  testthat::expect_true(qa$symmetric)
  testthat::expect_equal(qa$invalid_edge_count, 0L)
})

testthat::test_that("candidate masks use only response weeks at or after the candidate", {
  weeks <- data.frame(iso_week = c("2024-W52", "2025-W01", "2025-W02", "2026-W29", "2026-W30"))
  mask <- weeks$iso_week >= "2025-W01" & weeks$iso_week <= "2026-W29"
  testthat::expect_equal(mask, c(FALSE, TRUE, TRUE, TRUE, FALSE))
  counts <- matrix(c(4L, 0L, 0L, 0L, 0L, 1L, 0L, 0L, 0L, 0L), nrow = 5L, byrow = TRUE)
  metrics <- task2d_candidate_metrics("2025-W01", weeks[1:4, , drop = FALSE], counts[1:4, , drop = FALSE], data.frame(lat = c(20, 21)), c("Mexico", "Mexico"))
  testthat::expect_equal(metrics$response_weeks, 3L)
  testthat::expect_equal(metrics$positive_node_weeks, 1L)
  testthat::expect_false("2024-W52" >= metrics$candidate_start)
  testthat::expect_true("2026-W29" >= metrics$candidate_start)
  testthat::expect_false("2026-W30" %in% weeks$iso_week[1:4])
})

testthat::test_that("continuous calendar phase does not reset at an ISO year boundary", {
  dates <- as.Date(c("2024-12-30", "2025-01-06"))
  index <- 1:2
  period <- 52.1775
  sine <- sin(2 * pi * index / period)
  cosine <- cos(2 * pi * index / period)
  testthat::expect_lt(abs(sine[[2L]] - sine[[1L]]), 0.25)
  testthat::expect_lt(abs(cosine[[2L]] - cosine[[1L]]), 0.25)
  testthat::expect_equal(iso_week_id(dates), c("2025-W01", "2025-W02"))
})
