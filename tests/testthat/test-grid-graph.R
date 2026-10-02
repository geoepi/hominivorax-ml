source(testthat::test_path("..", "..", "R", "grid_graph.R"))

testthat::test_that("node IDs are stable and raster-cell round trips are lossless", {
  mask <- matrix(TRUE, nrow = 2L, ncol = 3L)
  mask[1L, 2L] <- FALSE
  nodes <- node_table_from_mask(mask)
  testthat::expect_equal(nodes$node_id, 0:4)
  testthat::expect_equal(nodes$raster_cell, c(1L, 3L, 4L, 5L, 6L))
  testthat::expect_true(all(mask[cbind(nodes$row, nodes$column)]))
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
  mask <- matrix(TRUE, nrow = 2L, ncol = 2L)
  mask[1L, 2L] <- FALSE
  nodes <- node_table_from_mask(mask)
  edges <- queen_edges(nodes, 2L, 2L)
  qa <- queen_graph_qa(nodes, edges)
  testthat::expect_false(2L %in% nodes$raster_cell)
  cell_by_id <- nodes$raster_cell
  names(cell_by_id) <- nodes$node_id
  actual <- sort(paste(
    cell_by_id[as.character(edges$source_node)],
    cell_by_id[as.character(edges$target_node)],
    sep = ":"
  ))
  expected <- sort(c("1:3", "3:1", "1:4", "4:1", "3:4", "4:3"))
  testthat::expect_equal(actual, expected)
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
