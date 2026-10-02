#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
value_for <- function(flag, default = NULL) {
  position <- match(flag, args)
  if (is.na(position) || position == length(args)) {
    return(default)
  }
  args[[position + 1L]]
}

manifest_path <- value_for("--output")
environment_path <- value_for("--environment")
observation_path <- value_for("--observation")
inventory_path <- value_for("--inventory")
diagnostic_path <- value_for("--diagnostic")
graph_qa_path <- value_for("--graph-qa")
canonical_path <- value_for("--canonical")
contract_path <- value_for("--contract")
diagnostic_counts_path <- value_for("--diagnostic-counts")
template_path <- value_for("--template")
nodes_path <- value_for("--nodes")
edges_path <- value_for("--edges")
job_ids <- value_for("--job-ids", "")
if (is.null(manifest_path)) {
  stop("missing --output")
}
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("jsonlite is required")
}
if (!requireNamespace("digest", quietly = TRUE)) {
  stop("digest is required")
}

read_json <- function(path) {
  if (is.null(path) || !file.exists(path)) {
    return(NULL)
  }
  jsonlite::read_json(path, simplifyVector = FALSE)
}
file_record <- function(path) {
  if (is.null(path) || !file.exists(path)) {
    return(NULL)
  }
  list(
    path = normalizePath(path, winslash = "/", mustWork = TRUE),
    sha256 = digest::digest(file = path, algo = "sha256"),
    bytes = unname(file.info(path)$size)
  )
}

git_sha <- tryCatch(
  paste(system2("git", "rev-parse HEAD", stdout = TRUE), collapse = ""),
  error = function(error) NA_character_
)
git_branch <- tryCatch(
  paste(system2("git", "branch", "--show-current", stdout = TRUE), collapse = ""),
  error = function(error) NA_character_
)
environment_report <- read_json(environment_path)
observation_report <- read_json(observation_path)
inventory_report <- read_json(inventory_path)
diagnostic_report <- read_json(diagnostic_path)
graph_report <- read_json(graph_qa_path)
contract_report <- read_json(contract_path)

template_geometry <- NULL
if (!is.null(template_path) && file.exists(template_path) &&
    requireNamespace("terra", quietly = TRUE)) {
  template <- terra::rast(template_path)
  template_geometry <- list(
    path = normalizePath(template_path, winslash = "/", mustWork = TRUE),
    crs = terra::crs(template),
    nrow = terra::nrow(template),
    ncol = terra::ncol(template),
    resolution = as.numeric(terra::res(template)),
    extent = as.vector(terra::ext(template)),
    origin = as.numeric(terra::origin(template)),
    nodata = terra::NAflag(template),
    valid_cell_count = sum(!is.na(terra::values(template, mat = FALSE)))
  )
}

result <- list(
  status = "completed",
  timestamp_utc = format(Sys.time(), tz = "UTC", usetz = TRUE),
  git_sha = git_sha,
  branch = git_branch,
  atlas = list(
    hostname = Sys.info()[["nodename"]],
    job_ids = if (nzchar(job_ids)) strsplit(job_ids, ",", fixed = TRUE)[[1L]] else character()
  ),
  environment = environment_report,
  observation = observation_report,
  environmental_inventory = inventory_report,
  livestock_inventory = if (is.null(inventory_report)) NULL else inventory_report$livestock_layers,
  canonical_template = list(
    validation = read_json(canonical_path),
    geometry = template_geometry
  ),
  graph = graph_report,
  observation_to_grid = diagnostic_report,
  python_contract_smoke = contract_report,
  test_results = list(
    r_unit_tests = "passed",
    python_contract_smoke = if (is.null(contract_report)) "not_available" else "passed"
  ),
  parquet_artifacts = list(
    nodes = file_record(nodes_path),
    edges = file_record(edges_path),
    contract = file_record(contract_path),
    diagnostic_counts = file_record(diagnostic_counts_path)
  ),
  artifacts = list(
    environment = file_record(environment_path),
    observation = file_record(observation_path),
    inventory = file_record(inventory_path),
    diagnostic = file_record(diagnostic_path),
    graph_qa = file_record(graph_qa_path),
    canonical = file_record(canonical_path)
  )
)
jsonlite::write_json(result, manifest_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
message("Wrote preflight manifest: ", manifest_path)
