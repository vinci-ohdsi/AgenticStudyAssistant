# Demo: apply LLM-proposed actions for concept set includeDescendants

devtools::load_all("R/OHDSIAssistant")
OHDSIAssistant::acp_connect("http://127.0.0.1:7777")

concept_set_ref <- "demo/concept_set.json"

# Ask tool for findings and actions
resp <- OHDSIAssistant:::`.acp_post`("/tools/propose_concept_set_diff", list(
  conceptSetRef = concept_set_ref,
  studyIntent   = paste(readLines("demo/protocol.md", warn = FALSE), collapse = " ")
))

actions <- resp$actions
print(actions)

# Preview execution of actions
prev <- OHDSIAssistant::applyLLMActionsConceptSet(concept_set_ref, actions, preview = TRUE)
print(prev$counts)
print(head(prev$preview_changes))

# Apply (writes new file if overwrite = FALSE)
applied <- OHDSIAssistant::applyLLMActionsConceptSet(concept_set_ref, actions, preview = FALSE, overwrite = FALSE, backup = TRUE)
print(applied$written_to)
