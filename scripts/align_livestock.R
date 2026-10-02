#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
value_for <- function(flag, default = NULL) {
  position <- match(flag, args)
  if (is.na(position) || position == length(args)) return(default)
  args[[position + 1L]]
}

livestock_root <- value_for("--livestock-root")
search_root <- value_for("--search-root", dirname(livestock_root))
template_path <- value_for("--template")
mask_path <- value_for("--mask")
nodes_path <- value_for("--nodes")
output_directory <- value_for("--output-directory")
summary_path <- value_for("--summary")
node_output <- value_for("--node-output")
if (any(vapply(list(livestock_root, template_path, mask_path, nodes_path,
                    output_directory, summary_path, node_output), is.null, logical(1L)))) {
  stop("missing livestock-alignment argument")
}
if (!requireNamespace("terra", quietly = TRUE) ||
    !requireNamespace("arrow", quietly = TRUE) ||
    !requireNamespace("jsonlite", quietly = TRUE)) {
  stop("terra, arrow, and jsonlite are required")
}
source(file.path("R", "raster_inventory.R"))
source(file.path("R", "livestock_alignment.R"))

dir.create(output_directory, recursive = TRUE, showWarnings = FALSE)
template <- terra::rast(template_path, lyrs = 1)
mask <- terra::rast(mask_path, lyrs = 1)
valid_mask <- !is.na(terra::values(mask, mat = FALSE))

expected <- c(
  goat = "goat_density20.tif",
  cattle = "cattle_density20.tif",
  sheep = "sheep_density20.tif",
  horse = "horse_density.tif",
  pig = "pig_density20.tiff"
)
source_paths <- file.path(livestock_root, unname(expected))
names(source_paths) <- names(expected)

all_search_files <- list.files(search_root, recursive = TRUE, full.names = TRUE)
pig_candidates <- all_search_files[
  grepl("\\.(tif|tiff)$", all_search_files, ignore.case = TRUE) &
    grepl("pig|swine|porcine", basename(all_search_files), ignore.case = TRUE)
]
pig_density_candidates <- pig_candidates[
  grepl("density|dens", basename(pig_candidates), ignore.case = TRUE)
]
pig_density20_candidates <- pig_density_candidates[
  grepl("^pig_density20\\.(tif|tiff)$", basename(pig_density_candidates), ignore.case = TRUE)
]
if (!file.exists(source_paths[["pig"]]) && length(pig_density20_candidates) == 1L) {
  source_paths[["pig"]] <- pig_density20_candidates[[1L]]
} else if (!file.exists(source_paths[["pig"]]) && length(pig_density_candidates) == 1L) {
  source_paths[["pig"]] <- pig_density_candidates[[1L]]
}

nodes <- arrow::read_parquet(nodes_path, as_data_frame = TRUE)
node_covariates <- data.frame(node_id = as.integer(nodes$node_id))
reports <- list()
for (animal in names(source_paths)) {
  source_path <- source_paths[[animal]]
  if (!file.exists(source_path)) {
    reports[[animal]] <- list(
      animal = animal,
      status = "omitted",
      reason = if (animal == "pig") {
        "No clearly corresponding pig/swine/porcine density raster was found under the bounded search root."
      } else "Required livestock raster is missing.",
      bounded_search_root = normalizePath(search_root, winslash = "/", mustWork = FALSE),
      pig_candidates = if (animal == "pig") normalizePath(pig_candidates, winslash = "/", mustWork = FALSE) else character()
    )
    next
  }
  source_header <- safe_raster_header(source_path, include_values = TRUE, include_minmax = TRUE)
  alignment <- area_weighted_density_to_template(source_path, template, valid_mask = valid_mask)
  output_path <- file.path(output_directory, paste0(animal, "_density_aligned.tif"))
  terra::writeRaster(alignment$raster, output_path, overwrite = TRUE, datatype = "FLT4S", NAflag = -9999)
  node_covariates[[paste0(animal, "_density")]] <- alignment$values[as.integer(nodes$raster_cell)]
  reports[[animal]] <- c(
    list(status = "aligned"),
    alignment_summary(
      alignment,
      source_path = source_path,
      animal = animal,
      explicit_units = NULL,
      metadata = list(
        datatype = source_header$data_type,
        bands = source_header$bands,
        nodata = source_header$nodata,
        metadata = source_header$metadata,
        description = source_header$description
      )
    ),
    list(output_path = normalizePath(output_path, winslash = "/", mustWork = TRUE))
  )
}

arrow::write_parquet(node_covariates, node_output)
result <- list(
  status = "completed",
  livestock_root = normalizePath(livestock_root, winslash = "/", mustWork = FALSE),
  bounded_pig_search_root = normalizePath(search_root, winslash = "/", mustWork = FALSE),
  pig_candidates = normalizePath(pig_candidates, winslash = "/", mustWork = FALSE),
  pig_density_candidates = normalizePath(pig_density_candidates, winslash = "/", mustWork = FALSE),
  template_path = normalizePath(template_path, winslash = "/", mustWork = TRUE),
  canonical_mask_path = normalizePath(mask_path, winslash = "/", mustWork = TRUE),
  reports = reports,
  node_covariates_path = normalizePath(node_output, winslash = "/", mustWork = TRUE)
)
jsonlite::write_json(result, summary_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
message("Wrote livestock alignment summary: ", summary_path)
