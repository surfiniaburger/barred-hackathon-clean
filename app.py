"""BARRED Hackathon Clean — thin live-run UI over the v13 pipeline.

Bootstraps foundation at build time. At runtime starts the debate stack
(A2A agents) then serves this FastAPI app. POST /api/run invokes
foundation/scenarios/debate/run_batch.py with curated seed + options and
returns the attempt record JSON.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
FOUNDATION = ROOT / "foundation"

app = FastAPI(title="BARRED Live Run", version="0.1.0")

RUNS: Dict[str, Dict[str, Any]] = {}


class RunRequest(BaseModel):
    seed: str = Field("safe_copy", description="safe_copy or gdImageJpegPtr")
    halt_on_con_win: bool = True
    slice_judge: bool = True
    reflector: bool = True
    reflector_mode: str = "symmetric"
    escalate_pareto: bool = True
    max_concurrency: int = 1


SEED_MAP = {
    "safe_copy": 0,       # row 0 of smoke_2gate
    "gdImageJpegPtr": 1,  # row 1 of smoke_2gate
}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "foundation_exists": FOUNDATION.exists()}


@app.post("/api/run")
async def create_run(req: RunRequest) -> Dict[str, Any]:
    run_id = str(uuid.uuid4())[:8]
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    attempts_path = run_dir / "attempts.jsonl"
    manifest_path = run_dir / "manifest.json"
    output_path = run_dir / "corpus.jsonl"
    gepa_dir = run_dir / "gepa"

    # Build run_batch.py args
    seed_index = SEED_MAP.get(req.seed, 0)
    # We only run the selected seed by using --seeds with a single-row file
    seed_file = FOUNDATION / "scenarios" / "debate" / "cve_seeds_smoke_2gate.jsonl"
    # Create a single-seed file
    lines = seed_file.read_text().strip().splitlines()
    selected_line = lines[seed_index]
    single_seed_file = run_dir / "seed.jsonl"
    single_seed_file.write_text(selected_line + "\n")

    cmd = [
        "uv", "run", "python", "scenarios/debate/run_batch.py",
        "--seeds", str(single_seed_file),
        "--run-id", f"live-{run_id}",
        "--output", str(output_path),
        "--gepa-dir", str(gepa_dir),
        "--attempts-out", str(attempts_path),
        "--manifest-out", str(manifest_path),
        "--seed", "42",
        "--mode", "record",
        "--max-concurrency", str(req.max_concurrency),
        "--counter-evidence-validation-mode", "enforce_deterministic",
    ]
    if req.slice_judge:
        cmd.append("--slice-judge")
    if req.reflector:
        cmd.append("--reflector")
        cmd.append("--reflector-in-process")
        cmd.append("--reflector-mode")
        cmd.append(req.reflector_mode)
    if req.escalate_pareto:
        cmd.append("--escalate-pareto")
    if req.halt_on_con_win:
        cmd.append("--halt-on-con-win")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(FOUNDATION) + ":" + env.get("PYTHONPATH", "")
    # Baseten config
    env.setdefault("DEBATER_MODEL", "openai/meta-models/muse-spark-open-1026")
    env.setdefault("VERIFIER_MODEL", "openai/meta-models/muse-spark-open-1026")
    env.setdefault("GENERATOR_MODEL", "openai/meta-models/muse-spark-open-1026")
    env.setdefault("JUDGE_MODEL", "openai/meta-models/muse-spark-open-1026")
    env.setdefault("OPENAI_API_BASE", "https://inference.baseten.co/v1")
    env.setdefault("OPENAI_API_KEY", os.getenv("BASETEN_API_KEY", ""))
    env.setdefault("LLM_SAMPLING_PROFILE", "env")
    env.setdefault("LLM_MAX_TOKENS", "4096")
    env.setdefault("SEND_MESSAGE_TIMEOUT", "1800")
    env.setdefault("LITELLM_REQUEST_TIMEOUT", "360")

    RUNS[run_id] = {"status": "running", "run_id": run_id, "seed": req.seed}

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(FOUNDATION),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        log = stdout.decode("utf-8", errors="replace") if stdout else ""

        if proc.returncode != 0:
            RUNS[run_id] = {"status": "error", "run_id": run_id, "log": log[-2000:]}
            raise HTTPException(status_code=500, detail=f"run_batch failed: {log[-500:]}")

        # Read attempt record
        attempt = None
        if attempts_path.exists():
            lines = attempts_path.read_text().strip().splitlines()
            if lines:
                attempt = json.loads(lines[-1])

        RUNS[run_id] = {
            "status": "complete",
            "run_id": run_id,
            "seed": req.seed,
            "attempt": attempt,
            "log": log[-1000:],
        }
        return RUNS[run_id]
    except Exception as e:
        RUNS[run_id] = {"status": "error", "run_id": run_id, "error": str(e)}
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/run/{run_id}")
def get_run(run_id: str) -> Dict[str, Any]:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    return RUNS[run_id]


# Inline HTML (curated-run console)
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BARRED — Live Run Console</title>
<style>
:root { --bg:#0b0f14; --panel:#131922; --panel-2:#1a2230; --border:#2a3444; --text:#e6edf3; --muted:#8b98a5; --accent:#58a6ff; --green:#3fb950; --red:#f85149; --yellow:#d29922; }
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; background:var(--bg); color:var(--text); line-height:1.5; }
.wrap { max-width:900px; margin:0 auto; padding:24px; }
h1 { color:var(--accent); margin:0 0 4px; font-size:22px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:20px; }
.card { background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:18px; margin-bottom:16px; }
.card h2 { margin:0 0 12px; font-size:15px; color:var(--accent); }
.row { display:flex; gap:16px; margin-bottom:12px; flex-wrap:wrap; }
.field { flex:1; min-width:200px; }
.field label { display:block; font-size:12px; color:var(--muted); margin-bottom:4px; text-transform:uppercase; letter-spacing:.5px; }
.field select, .field input { width:100%; background:var(--panel-2); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:8px 10px; font-size:13px; }
.checkbox { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
.checkbox input { width:auto; }
.checkbox label { text-transform:none; margin:0; font-size:13px; color:var(--text); }
.btn { padding:12px 24px; border-radius:6px; border:1px solid var(--accent); cursor:pointer; font-size:14px; font-weight:600; background:var(--accent); color:#0b0f14; }
.btn:disabled { opacity:.5; cursor:not-allowed; }
.status { font-size:13px; color:var(--muted); margin:10px 0; min-height:20px; }
.badge { display:inline-block; padding:4px 12px; border-radius:4px; font-size:13px; font-weight:800; letter-spacing:.5px; }
.badge.PASS { background:rgba(63,185,80,.15); color:var(--green); border:1px solid var(--green); }
.badge.BLOCKED { background:rgba(248,81,73,.15); color:var(--red); border:1px solid var(--red); }
.badge.UNRESOLVED { background:rgba(210,153,34,.15); color:var(--yellow); border:1px solid var(--yellow); }
.badge.running { background:rgba(88,166,255,.15); color:var(--accent); border:1px solid var(--accent); }
.result-box { background:var(--panel-2); border:1px solid var(--border); border-radius:8px; padding:14px; margin-top:12px; }
.result-box h3 { font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; margin:10px 0 4px; }
.result-box .trace { font-family:monospace; font-size:12px; background:var(--bg); padding:8px; border-radius:4px; border:1px solid var(--border); word-break:break-word; margin:4px 0; }
.checks { list-style:none; padding:0; margin:4px 0; }
.checks li { display:flex; justify-content:space-between; padding:2px 0; font-size:12px; font-family:monospace; }
.ok { color:var(--green); } .fail { color:var(--red); }
</style>
</head>
<body>
<div class="wrap">
  <h1>BARRED — Live Run Console</h1>
  <div class="sub">Curated-run console: select a seed, toggle options, run the real v13 pipeline (Baseten Muse Spark Open). Live inference ~10-15s per seed.</div>

  <div class="card">
    <h2>1. Configure Run</h2>
    <div class="row">
      <div class="field">
        <label>Seed</label>
        <select id="seed">
          <option value="safe_copy">safe_copy (upper-bound guard → PASS)</option>
          <option value="gdImageJpegPtr">gdImageJpegPtr (wrapper → UNRESOLVED)</option>
        </select>
      </div>
    </div>
    <div class="checkbox"><input type="checkbox" id="haltOnConWin" checked><label for="haltOnConWin">Halt on Con win</label></div>
    <div class="checkbox"><input type="checkbox" id="sliceJudge" checked><label for="sliceJudge">Slice judge</label></div>
    <div class="checkbox"><input type="checkbox" id="reflector" checked><label for="reflector">Reflector / escalation</label></div>
    <button class="btn" id="runBtn" onclick="runLive()">Run Live</button>
    <div class="status" id="status">Ready.</div>
  </div>

  <div class="card" id="resultCard" style="display:none;">
    <h2>2. Result</h2>
    <div id="result"></div>
  </div>
</div>

<script>
async function runLive() {
  const btn = document.getElementById('runBtn');
  const status = document.getElementById('status');
  btn.disabled = true;
  status.innerHTML = '<span class="badge running">RUNNING</span> Invoking pipeline…';
  document.getElementById('resultCard').style.display = 'none';

  const body = {
    seed: document.getElementById('seed').value,
    halt_on_con_win: document.getElementById('haltOnConWin').checked,
    slice_judge: document.getElementById('sliceJudge').checked,
    reflector: document.getElementById('reflector').checked,
  };

  const t0 = Date.now();
  try {
    const res = await fetch('/api/run', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const data = await res.json();
    const elapsed = ((Date.now()-t0)/1000).toFixed(1);
    if (!res.ok) { status.textContent = 'Error: ' + (data.detail||res.statusText); return; }
    const a = data.attempt || {};
    const je = a.judge_eval || {};
    const outcome = je.outcome === 'con_win' ? 'PASS' : (je.outcome === 'pro_win' ? 'BLOCKED' : 'UNRESOLVED');
    // Actually map properly
    const mappedOutcome = (a.decision === 'accepted') ? 'PASS' : (je.outcome === 'pro_win' ? 'BLOCKED' : 'UNRESOLVED');
    const checks = a.soft_checks || {};
    let checksHtml = '';
    // Show counter_evidence_validation checks if available
    const cev = a.counter_evidence_validation;
    if (cev && cev.checks) {
      checksHtml = Object.entries(cev.checks).map(([k,v]) => `<li><span>${k}</span><span class="${v?'ok':'fail'}">${v?'✓':'✗'}</span></li>`).join('');
    }

    let html = `<div style="margin-bottom:10px;"><span class="badge ${mappedOutcome}">${mappedOutcome}</span> <span style="color:var(--muted);font-size:12px;">(${elapsed}s)</span></div>`;
    html += `<div style="font-size:12px;color:var(--muted);margin-bottom:8px;">Seed: ${data.seed} · Run: ${data.run_id}</div>`;
    if (a.judge_eval) html += `<h3>Judge Outcome</h3><div class="trace">${JSON.stringify(a.judge_eval, null, 2)}</div>`;
    if (a.counter_evidence_validation) html += `<h3>Counter-Evidence Validation</h3><div class="trace">${JSON.stringify(a.counter_evidence_validation, null, 2)}</div>`;
    if (checksHtml) html += `<h3>AST Checks</h3><ul class="checks">${checksHtml}</ul>`;
    if (a.reject_reason) html += `<h3>Reject Reason</h3><div class="trace">${a.reject_reason}</div>`;
    if (a.llm_usage && a.llm_usage.totals) {
      const t = a.llm_usage.totals;
      html += `<h3>Timing / Usage</h3><div class="trace">calls: ${t.calls} · tokens: ${t.total_tokens} · ${t.total_duration_ms}ms · cost: $${t.cost_usd}</div>`;
    }
    document.getElementById('result').innerHTML = html;
    document.getElementById('resultCard').style.display = 'block';
    status.innerHTML = `<span class="badge ${mappedOutcome}">${mappedOutcome}</span> Complete in ${elapsed}s.`;
  } catch(e) {
    status.textContent = 'Error: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
