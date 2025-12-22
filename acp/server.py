import os, json, subprocess, sys, shlex
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

LOG_MODEL = os.getenv("ACP_MODEL_LOG", "1") == "1"


def log_lines(prefix: str, text: str):
    if LOG_MODEL:
        for line in text.splitlines():
            print(f"{prefix}{line}", file=sys.stderr)


def load_json(ref: str):
    if ref.startswith("http://") or ref.startswith("https://"):
        r = requests.get(ref, timeout=30)
        r.raise_for_status()
        return r.json()
    with open(ref, "r", encoding="utf-8") as f:
        return json.load(f)


def _run_cli_model(cmd: str, prompt: str, label: str):
    """Run a CLI that accepts prompt via stdin and returns JSON text."""
    try:
        args = shlex.split(cmd)
        log_lines(f"{label} OUTGOING TEXT > ", prompt)
        p = subprocess.run(
            args,
            input=prompt,
            capture_output=True,
            check=True,
            text=True,
        )
        txt = (p.stdout or "").strip()
        if p.stderr:
            log_lines(f"{label} STDERR > ", p.stderr.strip())
        log_lines(f"{label} INCOMING TEXT > ", txt or "<empty>")
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(txt[start : end + 1])
    except Exception as e:  # pragma: no cover - defensive logging
        print(f"[{label.lower()}-warning] {e}", file=sys.stderr)
    return None


def _chat_openwebui(prompt: str):
    api_url = os.getenv("OPENWEBUI_API_URL", "http://localhost:3000/api/chat/completions")
    api_key = os.getenv("OPENWEBUI_API_KEY")
    llm_model = os.getenv("OPENWEBUI_MODEL", "agentstudyassistant")
    if not api_key:
        print("[openwebui-warning] OPENWEBUI_API_KEY not set; skipping", file=sys.stderr)
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": llm_model,
        "messages": [{"role": "user", "content": prompt}],
    }
    log_lines("OPENWEBUI OUTGOING TEXT > ", prompt)
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=60)
    except Exception as e:  # pragma: no cover - network failure
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
        if choices and isinstance(choices, list):
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if msg and isinstance(msg, dict):
                content_txt = msg.get("content")
        if content_txt is None:
            # fall back to entire payload serialized
            content_txt = raw_txt
    else:
        content_txt = raw_txt

    if not content_txt:
        print("[openwebui-warning] empty content from model", file=sys.stderr)
        return None

    # Try to parse the JSON object from the content
    start = content_txt.find("{")
    end = content_txt.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(content_txt[start : end + 1])
        except Exception as e:
            print(f"[openwebui-error] failed to parse JSON object: {e}", file=sys.stderr)
            return None
    print("[openwebui-warning] no JSON object found in model response", file=sys.stderr)
    return None


def maybe_call_model(prompt: str):
    # Prefer OpenWebUI HTTP backend when configured
    if os.getenv("OPENWEBUI_API_KEY"):
        res = _chat_openwebui(prompt)
        if res is not None:
            return res

    cli_cmd = os.getenv("ACP_MODEL_CMD")
    if cli_cmd:
        return _run_cli_model(cli_cmd, prompt, label="ACP MODEL")
    return None


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/tools/propose_concept_set_diff")
def propose_concept_set_diff():
    body = request.get_json(force=True)
    ref = body.get("conceptSetRef")
    study_intent = body.get("studyIntent", "")
    cs = load_json(ref)

    items = []
    if isinstance(cs, dict) and "items" in cs:
        for it in cs.get("items", []):
            c = it.get("concept") or {}
            items.append(
                {
                    "conceptId": c.get("conceptId") or c.get("CONCEPT_ID"),
                    "domainId": c.get("domainId") or c.get("DOMAIN_ID"),
                }
            )
    elif isinstance(cs, list):
        for it in cs:
            items.append(
                {"conceptId": it.get("conceptId") or it.get("CONCEPT_ID"), "domainId": it.get("domainId") or it.get("DOMAIN_ID")}
            )

    findings = []
    patches = []
    risk_notes = []
    plan = f"Review concept set for gaps and inconsistencies given the study intent: {study_intent[:160]}..."

    concept_ids = [x.get("conceptId") for x in items if x.get("conceptId") is not None]
    duplicates = [cid for cid in concept_ids if concept_ids.count(cid) > 1]
    if len(items) == 0:
        findings.append(
            {"id": "empty_concept_set", "severity": "high", "impact": "design", "message": "Concept set is empty."}
        )
    if duplicates:
        findings.append(
            {"id": "duplicate_concepts", "severity": "medium", "impact": "design", "message": f"Duplicate conceptIds: {sorted(set(duplicates))}"}
        )

    domains = set([x.get("domainId") for x in items if x.get("domainId")])
    if len(domains) > 1:
        findings.append(
            {"id": "mixed_domains", "severity": "low", "impact": "portability", "message": f"Multiple domains detected: {sorted(domains)}"}
        )

    if duplicates:
        ops = [{"op": "note", "path": "/items", "value": {"removeDuplicatesOf": sorted(set(duplicates))}}]
        patches.append({"artifact": ref, "type": "jsonpatch", "ops": ops})

    prompt = f"""You are checking an OHDSI concept set for study design issues.
Study intent: {study_intent}
First 20 items: {json.dumps(items[:20])}
Return JSON with fields: findings[], patches[]. Keep patches high-level notes, not executable.
"""
    llm = maybe_call_model(prompt)
    if llm:
        for f in llm.get("findings", []):
            if f not in findings:
                findings.append(f)
        for p in llm.get("patches", []):
            if p not in patches:
                patches.append(p)

    return jsonify({"plan": plan, "findings": findings, "patches": patches, "risk_notes": risk_notes})


@app.post("/tools/cohort_lint")
def cohort_lint():
    body = request.get_json(force=True)
    ref = body.get("cohortRef")
    cohort = load_json(ref)

    plan = "Review cohort JSON for general design issues (washout/time-at-risk, inverted windows, empty or conflicting criteria)."
    findings, patches, risk_notes = [], [], []

    pc = cohort.get("PrimaryCriteria", {}) if isinstance(cohort, dict) else {}
    washout = pc.get("ObservationWindow", {})

    if not washout or washout.get("PriorDays") in (None, 0):
        findings.append(
            {"id": "missing_washout", "severity": "medium", "impact": "validity", "message": "No or zero-day washout; consider >= 365 days."}
        )
        patches.append(
            {"artifact": ref, "type": "jsonpatch", "ops": [{"op": "note", "path": "/PrimaryCriteria/ObservationWindow", "value": {"ProposedPriorDays": 365}}]}
        )

    irules = cohort.get("InclusionRules", []) if isinstance(cohort, dict) else []
    for i, r in enumerate(irules):
        w = r.get("window", {}) if isinstance(r, dict) else {}
        start = w.get("start", 0)
        end = w.get("end", 0)
        if w and isinstance(start, (int, float)) and isinstance(end, (int, float)) and start > end:
            findings.append(
                {"id": f"inverted_window_{i}", "severity": "high", "impact": "validity", "message": f"InclusionRule[{i}] has inverted window (start > end)."}
            )

    prompt = f"""You are reviewing an OHDSI cohort JSON for general design risks.
Return JSON fields findings[], patches[] (patches are notes, not executable).
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

    return jsonify({"plan": plan, "findings": findings, "patches": patches, "risk_notes": risk_notes})


if __name__ == "__main__":
    port = int(os.getenv("ACP_PORT", "7777"))
    from flask import Flask

    app.run(host="127.0.0.1", port=port)
