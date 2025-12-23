import csv
import json
import os
import shlex
import shutil
import subprocess
import sys

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

LOG_MODEL = os.getenv("ACP_MODEL_LOG", "1") == "1"
TIMESTAMP_FMT = "%Y%m%dT%H%M%S"


def log_lines(prefix: str, text: str):
    if LOG_MODEL:
        for line in text.splitlines():
            print(f"{prefix}{line}", file=sys.stderr)


def format_time():
    return __import__("datetime").datetime.now().strftime(TIMESTAMP_FMT)


def write_json(target: str, obj, backup: bool = True, overwrite: bool = True):
    if target.startswith("http://") or target.startswith("https://"):
        raise ValueError("write only supported to local files")

    final_target = target
    backup_file = None

    if not overwrite and os.path.exists(target):
        root, ext = os.path.splitext(target)
        i = 1
        while True:
            candidate = f"{root}-assistant-v{i}{ext}"
            if not os.path.exists(candidate):
                final_target = candidate
                break
            i += 1

    if overwrite and backup and os.path.exists(final_target):
        backup_file = f"{final_target}.bak_{format_time()}"
        shutil.copyfile(final_target, backup_file)

    with open(final_target, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

    return final_target, backup_file


def resolve_local_path(ref: str):
    """Resolve a local path robustly relative to server cwd or its parent."""
    if os.path.isabs(ref):
        return ref
    # try as-is relative to cwd
    cand = os.path.abspath(ref)
    if os.path.exists(cand):
        return cand
    cwd = os.getcwd()
    # try relative to cwd parent (helps when client includes repo folder name)
    parent_cand = os.path.abspath(os.path.join(cwd, "..", ref))
    if os.path.exists(parent_cand):
        return parent_cand
    # try stripping leading cwd basename (e.g., "AgenticStudyAssistant/demo/...")
    base = os.path.basename(cwd)
    prefix = base + os.sep
    if ref.startswith(prefix):
        trimmed = ref[len(prefix) :]
        trimmed_cand = os.path.abspath(os.path.join(cwd, trimmed))
        if os.path.exists(trimmed_cand):
            return trimmed_cand
    return cand


def load_json(ref: str):
    if ref.startswith("http://") or ref.startswith("https://"):
        r = requests.get(ref, timeout=30)
        r.raise_for_status()
        return r.json()
    path = resolve_local_path(ref)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_text(ref: str):
    if ref.startswith("http://") or ref.startswith("https://"):
        r = requests.get(ref, timeout=30)
        r.raise_for_status()
        return r.text
    path = resolve_local_path(ref)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_cohort_catalog_csv(ref: str):
    rows = []
    if ref.startswith("http://") or ref.startswith("https://"):
        r = requests.get(ref, timeout=30)
        r.raise_for_status()
        content = r.text.splitlines()
    else:
        path = resolve_local_path(ref)
        with open(path, "r", encoding="utf-8") as f:
            content = f.readlines()
    reader = csv.DictReader(content)
    for row in reader:
        rows.append(
            {
                "cohortId": int(row.get("cohortId") or 0),
                "cohortName": row.get("cohortNameLong") or row.get("cohortName") or row.get("name") or "",
                "logicDescription": row.get("logicDescription") or "",
            }
        )
    return rows


def _filter_catalog_recs(recs, catalog_rows, max_results):
    """Keep only catalog-backed cohortIds; fill missing names."""
    allowed = {r["cohortId"]: r for r in catalog_rows if r.get("cohortId")}
    cleaned = []
    for rec in recs or []:
        cid = rec.get("cohortId")
        if cid not in allowed:
            continue
        info = allowed[cid]
        cleaned.append(
            {
                "cohortId": cid,
                "cohortName": rec.get("cohortName") or info.get("cohortName") or "",
                "justification": rec.get("justification") or "Model justification not provided.",
                "confidence": rec.get("confidence"),
            }
        )
        if len(cleaned) >= max_results:
            break
    return cleaned


def _coerce_rec_ids_from_llm(raw):
    """Best-effort parse of simple list/CSV ids returned by a non-compliant LLM."""
    ids = []
    if isinstance(raw, list):
        for v in raw:
            try:
                ids.append(int(v))
            except Exception:
                continue
    elif isinstance(raw, str):
        parts = raw.replace("\n", ",").split(",")
        for p in parts:
            p = p.strip()
            if not p:
                continue
            try:
                ids.append(int(p))
            except Exception:
                continue
    return ids


def _cohort_id_from_ref(ref: str):
    """Best-effort extraction of cohortId from filename (e.g., 33_name.json)."""
    base = os.path.basename(ref or "")
    if not base:
        return None
    digits = []
    for ch in base:
        if ch.isdigit():
            digits.append(ch)
        else:
            if digits:
                break
    if digits:
        try:
            return int("".join(digits))
        except ValueError:
            return None
    return None


def _run_cli_model(cmd: str, prompt: str, label: str):
    """Run a CLI that accepts prompt via stdin and returns JSON text."""
    try:
        args = shlex.split(cmd)
        log_lines(f"{label} OUTGOING TEXT > ", prompt)
        p = subprocess.run(args, input=prompt, capture_output=True, check=True, text=True)
        txt = (p.stdout or "").strip()
        if p.stderr:
            log_lines(f"{label} STDERR > ", p.stderr.strip())
        log_lines(f"{label} INCOMING TEXT > ", txt or "<empty>")
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(txt[start : end + 1])
    except Exception as e:  # pragma: no cover
        print(f"[{label.lower()}-warning] {e}", file=sys.stderr)
    return None


def _chat_openwebui(prompt: str):
    api_url = os.getenv("OPENWEBUI_API_URL", "http://localhost:3000/api/chat/completions")
    api_key = os.getenv("OPENWEBUI_API_KEY")
    llm_model = os.getenv("OPENWEBUI_MODEL", "agentstudyassistant")
    if not api_key:
        return None
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": llm_model, "messages": [{"role": "user", "content": prompt}]}
    log_lines("OPENWEBUI OUTGOING TEXT > ", prompt)
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=60)
    except Exception as e:  # pragma: no cover
        print(f"[openwebui-error] request failed: {e}", file=sys.stderr)
        return None
    if resp.status_code >= 300:
        print(f"[openwebui-error] http {resp.status_code}: {resp.text}", file=sys.stderr)
        return None
    raw_txt = resp.text.strip()
    log_lines("OPENWEBUI INCOMING RAW > ", raw_txt or "<empty>")
    try:
        data = resp.json()
    except Exception as e:
        print(f"[openwebui-error] json decode failed: {e}", file=sys.stderr)
        data = None
    content_txt = None
    if isinstance(data, dict):
        choices = data.get("choices") or []
        if choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if msg and isinstance(msg, dict):
                content_txt = msg.get("content")
        if content_txt is None:
            content_txt = raw_txt
    else:
        content_txt = raw_txt
    if not content_txt:
        return None
    start = content_txt.find("{")
    end = content_txt.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(content_txt[start : end + 1])
        except Exception as e:
            print(f"[openwebui-error] failed to parse JSON object: {e}", file=sys.stderr)
            return None
    return None


def maybe_call_model(prompt: str):
    if os.getenv("OPENWEBUI_API_KEY"):
        res = _chat_openwebui(prompt)
        if res is not None:
            return res
    cli_cmd = os.getenv("ACP_MODEL_CMD")
    if cli_cmd:
        return _run_cli_model(cli_cmd, prompt, label="ACP MODEL")
    return None


def canonicalize_concept_items(cs):
    items = []
    if isinstance(cs, dict) and "items" in cs:
        src_items = cs.get("items", [])
    elif isinstance(cs, list):
        src_items = cs
    else:
        src_items = []
    for it in src_items:
        concept = (it.get("concept") if isinstance(it, dict) else None) or {}
        items.append(
            {
                "conceptId": concept.get("conceptId") or concept.get("CONCEPT_ID"),
                "domainId": concept.get("domainId") or concept.get("DOMAIN_ID"),
                "conceptClassId": concept.get("conceptClassId") or concept.get("CONCEPT_CLASS_ID"),
                "includeDescendants": it.get("includeDescendants"),
                "raw": it,
            }
        )
    return items, src_items


def apply_set_include_descendants(cs, where, value=True):
    items, src_items = canonicalize_concept_items(cs)
    preview = []
    for idx, info in enumerate(items):
        if info["conceptId"] is None:
            continue
        if where.get("domainId") and (info.get("domainId") != where["domainId"]):
            continue
        if where.get("conceptClassId") and (info.get("conceptClassId") != where["conceptClassId"]):
            continue
        if where.get("includeDescendants") is not None:
            inc = bool(info.get("includeDescendants") or False)
            if inc != bool(where["includeDescendants"]):
                continue
        preview.append(
            {
                "conceptId": info["conceptId"],
                "from": {"includeDescendants": bool(info.get("includeDescendants") or False)},
                "to": {"includeDescendants": bool(value)},
            }
        )
        raw_item = src_items[idx]
        if isinstance(raw_item, dict):
            raw_item["includeDescendants"] = bool(value)
    return cs, preview


@app.post("/actions/execute_llm")
def execute_llm_actions():
    """
    Execute model-proposed actions safely using deterministic ops.
    Currently supports concept-set actions only.
    """
    body = request.get_json(force=True)
    ref = body.get("artifactRef")
    actions = body.get("actions", [])
    write = bool(body.get("write", False))
    overwrite = bool(body.get("overwrite", False))
    backup = bool(body.get("backup", True))

    if not isinstance(actions, list):
        return jsonify({"error": "actions must be a list"}), 400

    raw = load_json(ref)
    if not isinstance(raw, (dict, list)):
        return jsonify({"error": "only concept-set actions are supported in this prototype"}), 400

    total_applied = 0
    preview_changes = []
    ignored = []
    cs = raw

    for act in actions:
        atype = act.get("type") or act.get("op")
        if atype == "set_include_descendants":
            where = act.get("where", {}) if isinstance(act, dict) else {}
            allowed_keys = {"domainId", "conceptClassId", "includeDescendants"}
            where = {k: v for k, v in where.items() if k in allowed_keys}
            value = bool(act.get("value", True))
            before = len(preview_changes)
            cs, changed = apply_set_include_descendants(cs, where=where, value=value)
            preview_changes.extend(changed)
            if len(preview_changes) > before:
                total_applied += 1
            else:
                ignored.append({"type": atype, "reason": "no items matched filter"})
        else:
            ignored.append({"type": atype, "reason": "unsupported action type"})

    written_to = None
    applied = False
    if write:
        target = ref
        try:
            written_to, backup_file = write_json(target, cs, backup=backup, overwrite=overwrite or False)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        applied = True
    else:
        backup_file = None

    return jsonify(
        {
            "plan": f"Execute LLM actions ({total_applied} applied, {len(ignored)} ignored).",
            "preview_changes": preview_changes,
            "counts": {"applied": total_applied, "changed": len(preview_changes), "ignored": len(ignored)},
            "ignored": ignored,
            "artifact": ref,
            "applied": applied,
            "written_to": written_to,
            "backup_file": backup_file,
        }
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/tools/propose_concept_set_diff")
def propose_concept_set_diff():
    body = request.get_json(force=True)
    ref = body.get("conceptSetRef")
    study_intent = body.get("studyIntent", "")
    cs = load_json(ref)

    canon_items, _src = canonicalize_concept_items(cs)
    # include includeDescendants and conceptClassId for model visibility
    items = [
        {
            "conceptId": it.get("conceptId"),
            "domainId": it.get("domainId"),
            "conceptClassId": it.get("conceptClassId"),
            "includeDescendants": bool(it.get("includeDescendants") or False),
        }
        for it in canon_items
    ]

    findings = []
    patches = []
    actions = []
    risk_notes = []
    plan = f"Review concept set for gaps and inconsistencies given the study intent: {study_intent[:160]}..."

    concept_ids = [x.get("conceptId") for x in items if x.get("conceptId") is not None]
    duplicates = [cid for cid in concept_ids if concept_ids.count(cid) > 1]
    if len(items) == 0:
        findings.append({"id": "empty_concept_set", "severity": "high", "impact": "design", "message": "Concept set is empty."})
    if duplicates:
        findings.append({"id": "duplicate_concepts", "severity": "medium", "impact": "design", "message": f"Duplicate conceptIds: {sorted(set(duplicates))}"})

    domains = set([x.get("domainId") for x in items if x.get("domainId")])
    if len(domains) > 1:
        findings.append({"id": "mixed_domains", "severity": "low", "impact": "portability", "message": f"Multiple domains detected: {sorted(domains)}"})

    # deterministic check: drug/ingredient lacking descendants
    no_desc = [
        it
        for it in items
        if (it.get("domainId") or "").lower() == "drug"
        and (it.get("conceptClassId") or "").lower() == "ingredient"
        and not bool(it.get("includeDescendants") or False)
    ]
    if no_desc:
        findings.append(
            {
                "id": "suggest_descendants_concept_set",
                "severity": "medium",
                "impact": "design",
                "message": "Drug ingredient concepts missing includeDescendants; consider enabling for coverage.",
            }
        )
        actions.append(
            {
                "type": "set_include_descendants",
                "where": {"domainId": "Drug", "conceptClassId": "Ingredient", "includeDescendants": False},
                "value": True,
            }
        )

    prompt = f"""You are checking an OHDSI concept set for study design issues.
Study intent: {study_intent}
First 20 items: {json.dumps(items[:20])}
Return JSON with fields: findings[], patches[]. Return both high-level notes and any relevant action patches.
"""
    llm = maybe_call_model(prompt)
    if llm:
        for f in llm.get("findings", []):
            if f not in findings:
                findings.append(f)
        for p in llm.get("patches", []):
            if p not in patches:
                patches.append(p)
        if isinstance(llm.get("actions"), list):
            actions = llm["actions"]

    return jsonify({"plan": plan, "findings": findings, "patches": patches, "actions": actions, "risk_notes": risk_notes})


@app.post("/tools/cohort_lint")
def cohort_lint():
    body = request.get_json(force=True)
    ref = body.get("cohortRef")
    cohort = load_json(ref)

    plan = "Review cohort JSON for general design issues (washout/time-at-risk, inverted windows, empty or conflicting criteria)."
    findings, patches, actions, risk_notes = [], [], [], []

    pc = cohort.get("PrimaryCriteria", {}) if isinstance(cohort, dict) else {}
    washout = pc.get("ObservationWindow", {})

    if not washout or washout.get("PriorDays") in (None, 0):
        findings.append({"id": "missing_washout", "severity": "medium", "impact": "validity", "message": "No or zero-day washout; consider >= 365 days."})
        patches.append({"artifact": ref, "type": "jsonpatch", "ops": [{"op": "note", "path": "/PrimaryCriteria/ObservationWindow", "value": {"ProposedPriorDays": 365}}]})

    irules = cohort.get("InclusionRules", []) if isinstance(cohort, dict) else []
    for i, r in enumerate(irules):
        w = r.get("window", {}) if isinstance(r, dict) else {}
        start = w.get("start", 0)
        end = w.get("end", 0)
        if w and isinstance(start, (int, float)) and isinstance(end, (int, float)) and start > end:
            findings.append({"id": f"inverted_window_{i}", "severity": "high", "impact": "validity", "message": f"InclusionRule[{i}] has inverted window (start > end)."})

    prompt = f"""You are reviewing an OHDSI cohort JSON for general design risks.
Return JSON fields findings[], patches[] (return all relevant information and action patches).
Cohort excerpt: {json.dumps({k: cohort.get(k) for k in list(cohort.keys())[:5]})}
"""
    llm = maybe_call_model(prompt)
    if llm:
        for f in llm.get("findings", []):
            if f not in findings:
                findings.append(f)
        for p in llm.get("patches", []):
            if p not in patches:
                patches.append(p)
        if isinstance(llm.get("actions"), list):
            actions = llm["actions"]

    return jsonify({"plan": plan, "findings": findings, "patches": patches, "actions": actions, "risk_notes": risk_notes})


@app.post("/actions/concept_set_edit")
def concept_set_edit():
    body = request.get_json(force=True)
    ref = body.get("artifactRef")
    ops = body.get("ops", [])
    write = bool(body.get("write", False))
    backup = bool(body.get("backup", False))
    output_path = body.get("outputPath")
    overwrite = bool(body.get("overwrite", True))

    cs = load_json(ref)
    all_preview = []

    for op in ops:
        if op.get("op") == "set_include_descendants":
            where = op.get("where", {})
            value = op.get("value", True)
            cs, preview = apply_set_include_descendants(cs, where=where, value=value)
            all_preview.extend(preview)

    written_to = None
    applied = False
    backup_file = None
    if write:
        target = output_path or ref
        try:
            written_to, backup_file = write_json(target, cs, backup=backup, overwrite=overwrite)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        applied = True

    plan = "Set includeDescendants=true for Drug/Ingredient entries that lack it."
    return jsonify(
        {
            "plan": plan,
            "preview_changes": all_preview,
            "applied": applied,
            "written_to": written_to,
            "backup_file": backup_file,
            "ops": ops,
        }
    )


@app.post("/tools/phenotype_recommendations")
def phenotype_recommendations():
    body = request.get_json(force=True)
    protocol_ref = body.get("protocolRef")
    catalog_ref = body.get("cohortsCatalogRef")
    max_results = int(body.get("maxResults") or 5)

    if not protocol_ref or not catalog_ref:
        return jsonify({"error": "protocolRef and cohortsCatalogRef are required"}), 400

    protocol_text = load_text(protocol_ref)
    catalog_rows = load_cohort_catalog_csv(catalog_ref)

    plan = "Suggest relevant phenotypes from catalog for the study intent (stub if no LLM)."
    recs = []

    prompt = f"""You are selecting OHDSI phenotypes for a study (phenotype_recommendations). Return ONLY JSON with keys: plan, phenotype_recommendations[] according to the instructions you were given in the system prompt.
Constraints:
- Choose up to {max_results} items.
- Only choose cohortId values from this allowed list: {[r['cohortId'] for r in catalog_rows]}
Study intent (truncated): {protocol_text[:2000]}
Catalog preview (id, name, logicDescription, first 200 rows max): {json.dumps(catalog_rows[:200])}
Constraints:
    - JSON ONLY. No prose or markdown in the response!!
"""
    llm = maybe_call_model(prompt)
    mode = "llm"
    if llm and isinstance(llm.get("phenotype_recommendations"), list):
        recs = _filter_catalog_recs(llm.get("phenotype_recommendations"), catalog_rows, max_results)
        if llm.get("plan"):
            plan = llm["plan"]
    elif llm and llm.get("phenotype_recommendations") is None:
        ids = _coerce_rec_ids_from_llm(llm)
        if ids:
            # treat the whole object as an id list if parseable
            recs = _filter_catalog_recs([{"cohortId": cid} for cid in ids], catalog_rows, max_results)
    else:
        mode = "stub"
        for row in catalog_rows[:max_results]:
            recs.append(
                {
                    "cohortId": row.get("cohortId"),
                    "cohortName": row.get("cohortName"),
                    "justification": "Stub recommendation from deterministic fallback (no LLM).",
                    "confidence": None,
                }
            )

    return jsonify(
        {
            "plan": plan,
            "phenotype_recommendations": recs,
            "mode": mode,
            "artifact": {"protocolRef": protocol_ref, "cohortsCatalogRef": catalog_ref},
        }
    )


@app.post("/tools/phenotype_improvements")
def phenotype_improvements():
    body = request.get_json(force=True)
    protocol_ref = body.get("protocolRef")
    cohort_refs = body.get("cohortRefs") or []
    characterization_refs = body.get("characterizationRefs") or []

    if not protocol_ref or not isinstance(cohort_refs, list) or len(cohort_refs) == 0:
        return jsonify({"error": "protocolRef and cohortRefs[] are required"}), 400

    protocol_text = load_text(protocol_ref)
    cohorts = []
    for ref in cohort_refs:
        try:
            cohorts.append({"ref": ref, "cohort": load_json(ref)})
        except Exception as e:
            return jsonify({"error": f"failed to load cohort {ref}: {e}"}), 400

    allowed_ids = []
    for c in cohorts:
        cid = c["cohort"].get("id") if isinstance(c.get("cohort"), dict) else None
        if cid is None:
            cid = _cohort_id_from_ref(c.get("ref"))
        if isinstance(cid, (int, float)):
            allowed_ids.append(int(cid))
    allowed_ids = sorted(list(set(allowed_ids)))

    plan = "Review selected phenotypes for improvements against study intent (stub if no LLM)."
    prompt = f"""You are reviewing OHDSI phenotype definitions against a study intent.
Return ONLY JSON with keys: plan, phenotype_improvements[], code_suggestion (optional).
phenotype_improvements item schema: {{
  "targetCohortId": <int from provided list>,
  "summary": "<=220 chars>",
  "actions": [{{"type":"note","path":"<string>","value":"<string>"}}]  # advisory only
}}
code_suggestion (optional): {{"language":"R","summary":"<string>","snippet":"<code>"}}.
Constraints:
- Use only cohortIds from: {allowed_ids or '[ids provided in inputs]'}
- JSON ONLY. No prose or markdown in the response!!
Study intent (truncated): {protocol_text[:2000]}
Phenotype names: {json.dumps([{'ref': c['ref'], 'name': c['cohort'].get('name') or c['cohort'].get('Name')} for c in cohorts])}
Characterization summaries (optional paths): {characterization_refs}
"""
    llm = maybe_call_model(prompt)
    mode = "llm"
    improvements = []
    code_suggestion = None
    if llm:
        raw_improvements = llm.get("phenotype_improvements") or []
        if allowed_ids:
            improvements = [imp for imp in raw_improvements if imp.get("targetCohortId") in allowed_ids]
        else:
            improvements = raw_improvements
        code_suggestion = llm.get("code_suggestion")
        if llm.get("plan"):
            plan = llm["plan"]
    else:
        mode = "stub"
        improvements = []

    return jsonify(
        {
            "plan": plan,
            "phenotype_improvements": improvements,
            "code_suggestion": code_suggestion,
            "mode": mode,
            "artifact": {"protocolRef": protocol_ref, "cohortRefs": cohort_refs, "characterizationRefs": characterization_refs},
        }
    )


if __name__ == "__main__":
    port = int(os.getenv("ACP_PORT", "7777"))
    app.run(host="127.0.0.1", port=port)
