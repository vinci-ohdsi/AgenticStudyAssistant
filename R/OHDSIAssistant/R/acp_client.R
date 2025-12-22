acp_state <- new.env(parent = emptyenv())

#' Connect to ACP bridge
#' @param url e.g. "http://127.0.0.1:7777"
#' @param token optional bearer token
#' @return invisible(TRUE)
acp_connect <- function(url = "http://127.0.0.1:7777", token = NULL) {
  acp_state$url <- sub("/$", "", url)
  acp_state$token <- token
  resp <- httr::GET(paste0(acp_state$url, "/health"))
  if (httr::status_code(resp) != 200) stop("ACP bridge not reachable")
  invisible(TRUE)
}

.acp_post <- function(path, body) {
  if (is.null(acp_state$url)) stop("ACP not connected; call acp_connect().")
  url <- paste0(acp_state$url, path)
  headers <- c(`Content-Type` = "application/json")
  if (!is.null(acp_state$token)) {
    headers <- c(headers, Authorization = paste("Bearer", acp_state$token))
  }
  resp <- httr::POST(url,
                     body = jsonlite::toJSON(body, auto_unbox = TRUE),
                     httr::add_headers(.headers = headers))
  if (httr::status_code(resp) >= 300) stop("ACP error: ", httr::content(resp, as = "text"))
  jsonlite::fromJSON(httr::content(resp, as = "text"), simplifyVector = FALSE)
}
