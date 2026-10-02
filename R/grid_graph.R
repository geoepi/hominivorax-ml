# Deterministic raster-node and binary queen-graph helpers.

node_table_from_mask <- function(
  valid_mask,
  x = NULL,
  y = NULL,
  lon = NULL,
  lat = NULL
) {
  if (!is.matrix(valid_mask) || !is.logical(valid_mask)) {
    stop("valid_mask must be a logical matrix")
  }
  nr <- nrow(valid_mask)
  nc <- ncol(valid_mask)
  cells <- which(valid_mask)
  if (!length(cells)) {
    return(data.frame(
      node_id = integer(),
      raster_cell = integer(),
      row = integer(),
      column = integer(),
      x = numeric(),
      y = numeric(),
      lon = numeric(),
      lat = numeric()
    ))
  }

  indices <- arrayInd(cells, .dim = dim(valid_mask))
  ordering <- order(indices[, 1L], indices[, 2L])
  indices <- indices[ordering, , drop = FALSE]
  cells <- (indices[, 1L] - 1L) * nc + indices[, 2L]

  coordinate_matrix <- function(value, default) {
    if (is.null(value)) {
      return(default)
    }
    if (is.matrix(value)) {
      return(value[cbind(indices[, 1L], indices[, 2L])])
    }
    if (length(value) == length(cells)) {
      return(value)
    }
    if (length(value) == nr * nc) {
      return(value[cells])
    }
    if (length(value) == nc && identical(default, indices[, 2L])) {
      return(value[indices[, 2L]])
    }
    if (length(value) == nr && identical(default, indices[, 1L])) {
      return(value[indices[, 1L]])
    }
    stop("coordinate vectors must have raster-cell, row, or column length")
  }

  data.frame(
    node_id = seq_len(nrow(indices)) - 1L,
    raster_cell = as.integer(cells),
    row = as.integer(indices[, 1L]),
    column = as.integer(indices[, 2L]),
    x = as.numeric(coordinate_matrix(x, indices[, 2L])),
    y = as.numeric(coordinate_matrix(y, indices[, 1L])),
    lon = as.numeric(coordinate_matrix(lon, indices[, 2L])),
    lat = as.numeric(coordinate_matrix(lat, indices[, 1L])),
    stringsAsFactors = FALSE
  )
}

node_table_from_terra <- function(template) {
  if (!requireNamespace("terra", quietly = TRUE)) {
    stop("terra is required for node_table_from_terra()")
  }
  values <- terra::values(template, mat = FALSE)
  valid <- !is.na(values)
  nr <- terra::nrow(template)
  nc <- terra::ncol(template)
  mask <- matrix(valid, nrow = nr, ncol = nc, byrow = TRUE)
  row_column <- arrayInd(which(mask), .dim = dim(mask))
  row_column <- row_column[order(row_column[, 1L], row_column[, 2L]), , drop = FALSE]
  cells <- (row_column[, 1L] - 1L) * nc + row_column[, 2L]
  xy <- terra::xyFromCell(template, cells)

  lonlat <- xy
  template_crs <- terra::crs(template)
  if (!is.na(template_crs) && nzchar(template_crs) &&
      !terra::is.lonlat(template)) {
    points <- terra::vect(xy, geom = c("x", "y"), crs = template_crs)
    lonlat <- terra::crds(terra::project(points, "EPSG:4326"))
  }

  result <- node_table_from_mask(
    mask,
    x = terra::xFromCol(template, seq_len(nc)),
    y = terra::yFromRow(template, seq_len(nr)),
    lon = lonlat[, 1L],
    lat = lonlat[, 2L]
  )
  attr(result, "template_geometry") <- list(
    crs = terra::crs(template),
    nrow = nr,
    ncol = nc,
    resolution = terra::res(template),
    extent = as.vector(terra::ext(template)),
    origin = terra::origin(template),
    nodata = terra::NAflag(template)
  )
  result
}

queen_edges <- function(nodes, nrow, ncol) {
  required <- c("node_id", "row", "column")
  if (!all(required %in% names(nodes))) {
    stop("nodes must contain node_id, row, and column")
  }
  lookup <- nodes$node_id
  names(lookup) <- paste(nodes$row, nodes$column, sep = ":")
  result <- vector("list", 0L)

  for (i in seq_len(nrow(nodes))) {
    for (dr in -1L:1L) {
      for (dc in -1L:1L) {
        if (dr == 0L && dc == 0L) {
          next
        }
        neighbor_key <- paste(nodes$row[i] + dr, nodes$column[i] + dc, sep = ":")
        neighbor <- unname(lookup[neighbor_key])
        if (length(neighbor) == 1L && !is.na(neighbor)) {
          result[[length(result) + 1L]] <- c(nodes$node_id[i], neighbor)
        }
      }
    }
  }

  if (!length(result)) {
    return(data.frame(source_node = integer(), target_node = integer()))
  }
  edges <- as.data.frame(do.call(rbind, result), stringsAsFactors = FALSE)
  names(edges) <- c("source_node", "target_node")
  edges$source_node <- as.integer(edges$source_node)
  edges$target_node <- as.integer(edges$target_node)
  edges[order(edges$source_node, edges$target_node), , drop = FALSE]
}

queen_graph_components <- function(nodes, edges) {
  ids <- as.integer(nodes$node_id)
  adjacency <- vector("list", length(ids))
  names(adjacency) <- as.character(ids)
  for (i in seq_len(nrow(edges))) {
    source <- as.character(edges$source_node[i])
    target <- as.character(edges$target_node[i])
    adjacency[[source]] <- c(adjacency[[source]], edges$target_node[i])
    adjacency[[target]] <- c(adjacency[[target]], edges$source_node[i])
  }

  remaining <- ids
  components <- list()
  while (length(remaining)) {
    root <- remaining[1L]
    queue <- root
    visited <- integer()
    while (length(queue)) {
      current <- queue[1L]
      queue <- queue[-1L]
      if (current %in% visited) {
        next
      }
      visited <- c(visited, current)
      queue <- c(queue, adjacency[[as.character(current)]])
    }
    components[[length(components) + 1L]] <- sort(unique(visited))
    remaining <- setdiff(remaining, visited)
  }
  components
}

queen_graph_qa <- function(nodes, edges) {
  node_ids <- as.integer(nodes$node_id)
  edge_keys <- paste(edges$source_node, edges$target_node, sep = ":")
  reverse_keys <- paste(edges$target_node, edges$source_node, sep = ":")
  valid_indices <- edges$source_node %in% node_ids &
    edges$target_node %in% node_ids
  degree <- table(factor(edges$source_node, levels = node_ids))
  components <- queen_graph_components(nodes, edges)

  list(
    node_count = length(node_ids),
    directed_edge_count = nrow(edges),
    duplicate_directed_edges = anyDuplicated(edge_keys) > 0L,
    invalid_edge_indices = sum(!valid_indices),
    symmetric = setequal(edge_keys, reverse_keys),
    self_loops = sum(edges$source_node == edges$target_node),
    degree = as.integer(degree),
    degree_min = if (length(degree)) min(degree) else NA_integer_,
    degree_max = if (length(degree)) max(degree) else NA_integer_,
    isolated_nodes = sum(degree == 0L),
    connected_components = length(components),
    component_sizes = sort(vapply(components, length, integer(1L)), decreasing = TRUE)
  )
}
