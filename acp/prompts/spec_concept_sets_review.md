Tool: concept-sets-review
Output contract:
{
  "plan": "string <=300 chars",
  "findings": [Finding],
  "patches": [Patch],
  "risk_notes": ["string"],
  "actions": [Action]  # optional if supported
}
Finding: { "id": "snake_case", "severity": "low|medium|high", "impact": "design|validity|portability|performance", "message": "<=220 chars", "evidence": [{"ref":"string","note":"<=160 chars"}] }
Patch: { "artifact": "string", "type": "jsonpatch", "ops": [ { "op": "note", "path": "/path", "value": { "summary": "<=160 chars", "details": "<=400 chars" } } ] }
Action (concept sets): { "type": "set_include_descendants", "where": { "domainId": "...", "conceptClassId": "...", "includeDescendants": true|false }, "value": true|false, "rationale": "<=160 chars", "confidence": 0-1 }
Constraints: JSON only, no markdown. Keep output < 15 KB. If nothing to report, return empty arrays and a neutral plan.
