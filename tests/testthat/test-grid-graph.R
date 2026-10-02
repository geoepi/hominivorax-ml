source(testthat::test_path("..", "..", "R", "grid_graph.R"))

testthat::test_that("node IDs are stable and raster-cell round trips are lossless", {
  mask <- matrix(TRUE, nrow = 2L, ncol = 3L)
  mask[1L, 2L] <- FALSE
  nodes <- node_table_from_mask(mask)
  testthat::expect_equal(nodes$node_id, 0:4)
  testthat::expect_equal(nodes$raster_cell, c(1L, 3L, 4L, 5L, 6L))
  testthat::expect_equal(mask[cbind(nodes$row, nodes$column)], TRUE)
})

testthat::test_that("full 3 by 3 queen graph has correct boundary degrees", {
  nodes <- node_table_from_mask(matrix(TRUE, nrow = 3L, ncol = 3L))
  edges <- queen_edges(nodes, 3L, 3L)
  qa <- queen_graph_qa(nodes, edges)
  testthat::expect_equal(qa$directed_edge_count, 40L)
  testthat::expect_true(qa$symmetric)
  testthat::expect_equal(sort(qa$degree), c(3L, 3L, 3L, 3L, 5L, 5L, 5L, 5L, 8L))
  testthat::expect_equal(qa$isolated_nodes, 0L)
  testthat::expect_equal(qa$connected_components, 1L)
})

testthat::test_that("masked cells cannot create graph connections", {
  mask <- matrix(TRUE, nrow = 3L, ncol = 3L)
  mask[2L, 2L] <- FALSE
  nodes <- node_table_from_mask(mask)
  edges <- queen_edges(nodes, 3L, 3L)
  qa <- queen_graph_qa(nodes, edges)
  masked_node_id <- setdiff(0:8, nodes$node_id)
  testthat::expect_false(any(
    edges$source_node == masked_node_id | edges$target_node == masked_node_id
  ))
  testthat::expect_true(qa$symmetric)
  testthat::expect_equal(qa$connected_components, 1L)
  testthat::expect_equal(qa$isolated_nodes, 0L)
})

testthat::test_that("a singleton valid cell is isolated without self loops", {
  mask <- matrix(FALSE, nrow = 3L, ncol = 3L)
  mask[2L, 2L] <- TRUE
  nodes <- node_table_from_mask(mask)
  edges <- queen_edges(nodes, 3L, 3L)
  qa <- queen_graph_qa(nodes, edges)
  testthat::expect_equal(nrow(edges), 0L)
  testthat::expect_equal(qa$isolated_nodes, 1L)
  testthat::expect_equal(qa$connected_components, 1L)
})
