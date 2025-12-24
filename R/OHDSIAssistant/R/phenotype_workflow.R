#' Suggest phenotypes for a study protocol (prototype)
#' @param protocolPath path to protocol markdown/text
#' @param cohortsCatalogPath path/URL to Cohorts.csv catalog
#' @param maxResults max phenotypes to return
#' @param interactive print plan and recommendations
#' @return list response from ACP or local stub
suggestPhenotypes <- function(protocolPath,
                              cohortsCatalogPath,
                              maxResults = 5,
                              interactive = TRUE) {
  protocolPath <- normalizePath(protocolPath, winslash = "/", mustWork = FALSE)
  cohortsCatalogPath <- normalizePath(cohortsCatalogPath, winslash = "/", mustWork = FALSE)
  protocol_txt <- paste(readLines(protocolPath, warn = FALSE), collapse = "\n")
  body <- list(
    protocolRef = protocolPath,
    cohortsCatalogRef = cohortsCatalogPath,
    maxResults = maxResults
  )
  res <- if (!is.null(acp_state$url)) {
    .acp_post("/tools/phenotype_recommendations", body)
  } else {
    local_phenotype_recommendations(protocol_txt, cohortsCatalogPath, maxResults)
  }
  res$artifact <- list(protocolRef = protocolPath, cohortsCatalogRef = cohortsCatalogPath)
  if (interactive) {
    cat("\n== Phenotype Suggestions ==\n")
    cat(res$plan %||% "", "\n")
    if (!is.null(res$mode)) cat(sprintf("Mode: %s\n", res$mode))
    recs <- res$phenotype_recommendations %||% list()
    if (length(recs) == 0) {
      cat("  [stub] No recommendations (LLM not connected or no matches).\n")
    } else {
      for (r in recs) {
        cat(sprintf("  - %s (%s): %s\n",
                    r$cohortName %||% "<unknown>",
                    r$cohortId %||% "?",
                    r$justification %||% ""))
      }
    }
  }
  res
}

#' Pull phenotype definitions to a local folder
#' @param cohortIds integer vector of cohortIds
#' @param outputDir directory to write JSON definitions
#' @param overwrite logical; if FALSE, auto-version the filename
#' @return character vector of written file paths
pullPhenotypeDefinitions <- function(cohortIds,
                                     outputDir = ".",
                                     overwrite = FALSE) {
  outputDir <- normalizePath(outputDir, winslash = "/", mustWork = FALSE)
  if (!dir.exists(outputDir)) dir.create(outputDir, recursive = TRUE)
  cds <- PhenotypeLibrary::getPlCohortDefinitionSet(as.integer(cohortIds))
  written <- character(0)
  for (i in seq_len(nrow(cds))) {
    nm <- cds$cohortName[i] %||% ""
    safe <- gsub("[^A-Za-z0-9_-]+", "_", nm)
    if (identical(safe, "") || is.na(safe)) safe <- paste0("cohort_", cds$cohortId[i])
    fname_base <- file.path(outputDir, sprintf("%s_%s.json", cds$cohortId[i], safe))
    target <- fname_base
    if (!overwrite) {
      idx <- 1
      while (file.exists(target)) {
        target <- file.path(outputDir, sprintf("%s_%s-v%d.json", cds$cohortId[i], safe, idx))
        idx <- idx + 1
      }
    }
    writeLines(cds$json[i], con = target, useBytes = TRUE)
    written <- c(written, target)
  }
  written
}

#' Review phenotype definitions for improvements (prototype)
#' @param protocolPath path to protocol markdown/text
#' @param cohortJsonPaths character vector of cohort definition JSON paths
#' @param characterizationPaths optional vector of paths to characterization outputs
#' @param interactive logical; print plan and summaries
#' @return list response from ACP or local stub
reviewPhenotypes <- function(protocolPath,
                             cohortJsonPaths,
                             characterizationPaths = NULL,
                             interactive = TRUE) {
  protocolPath <- normalizePath(protocolPath, winslash = "/", mustWork = FALSE)
  cohortJsonPaths <- vapply(cohortJsonPaths, normalizePath, character(1), winslash = "/", mustWork = FALSE)
  if (!is.null(characterizationPaths)) {
    characterizationPaths <- vapply(characterizationPaths, normalizePath, character(1), winslash = "/", mustWork = FALSE)
  }
  body <- list(
    protocolRef = protocolPath,
    cohortRefs = as.list(cohortJsonPaths),
    characterizationRefs = as.list(characterizationPaths %||% list())
  )
  res <- if (!is.null(acp_state$url)) {
    .acp_post("/tools/phenotype_improvements", body)
  } else {
    local_phenotype_improvements()
  }
  res$artifact <- list(protocolRef = protocolPath, cohortRefs = cohortJsonPaths)
  if (interactive) {
    cat("\n== Phenotype Improvements ==\n")
    cat(res$plan %||% "", "\n")
    if (!is.null(res$mode)) cat(sprintf("Mode: %s\n", res$mode))
    imp <- res$phenotype_improvements %||% list()
    if (length(imp) == 0) {
      cat("  [stub] No improvements returned (LLM not connected).\n")
    } else {
      for (p in imp) {
        cat(sprintf("  - %s\n", p$summary %||% jsonlite::toJSON(p, auto_unbox = TRUE)))
      }
    }
  }
  res
}

#' Select phenotype recommendations (interactive or programmatic)
#' @param recommendations list from suggestPhenotypes()$phenotype_recommendations
#' @param select either numeric cohortIds, integer indices, or "all"/NULL to pick all
#' @param interactive if TRUE and select is NULL, prompt user
#' @return integer vector of chosen cohortIds
selectPhenotypeRecommendations <- function(recommendations,
                                           select = NULL,
                                           interactive = interactive()) {
  recs <- recommendations %||% list()
  if (length(recs) == 0) return(integer(0))

  # normalize to cohortIds
  ids <- vapply(recs, function(r) r$cohortId %||% NA_real_, numeric(1))

  if (is.null(select) || identical(select, "all")) {
    if (interactive) {
      labels <- vapply(seq_along(recs), function(i) {
        sprintf("%s (%s)", recs[[i]]$cohortName %||% "<unknown>", recs[[i]]$cohortId %||% "?")
      }, character(1))
      picks <- utils::select.list(labels, multiple = TRUE, title = "Select phenotypes to pull")
      if (length(picks) == 0) return(integer(0))
      idx <- match(picks, labels)
      return(as.integer(ids[idx]))
    }
    return(as.integer(ids))
  }

  # explicit selection provided
  if (is.numeric(select)) {
    # if they look like indices (<= length), map to ids; else assume cohortIds
    if (all(select %% 1 == 0) && all(select >= 1) && all(select <= length(ids))) {
      return(as.integer(ids[select]))
    }
    return(as.integer(select))
  }

  integer(0)
}


local_phenotype_recommendations <- function(protocolText,
                                            cohortsCatalogPath,
                                            maxResults = 5) {
  cat_rows <- tryCatch(read.csv(cohortsCatalogPath, stringsAsFactors = FALSE), error = function(e) NULL)
  recs <- list()
  if (!is.null(cat_rows) && NROW(cat_rows) > 0) {
    n <- min(maxResults, NROW(cat_rows))
    for (i in seq_len(n)) {
      recs[[i]] <- list(
        cohortId = cat_rows$cohortId[i],
        cohortName = cat_rows$cohortNameLong[i] %||% cat_rows$cohortName[i] %||% "",
        justification = "Stub recommendation from deterministic fallback (no LLM)."
      )
    }
  }
  list(
    plan = "Stub: deterministic phenotype suggestions (LLM not connected).",
    phenotype_recommendations = recs,
    mode = "stub"
  )
}


local_phenotype_improvements <- function() {
  list(
    plan = "Stub: no phenotype improvements available without LLM.",
    phenotype_improvements = list(),
    code_suggestion = NULL,
    mode = "stub"
  )
}
