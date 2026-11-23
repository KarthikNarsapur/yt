"""Script-writing model.

provider "claude": your Claude Pro/Max subscription through the Claude Code CLI in headless mode
  (claude -p), authenticated with a long-lived token from `claude setup-token` in CLAUDE_CODE_OAUTH_TOKEN.
provider "ollama": a local open model on CPU (fallback). Weights are cached in S3."""
import json
import os
import subprocess
import time

import requests

from . import config as C

MODELS_DIR = os.environ.get("OLLAMA_MODELS", os.path.expanduser("~/.ollama/models"))


def _sync_from_cache(store):
    if store.local:
        return
    keys = store.list(C.MODEL_CACHE_PREFIX + "/")
    for k in keys:
        rel = k[len(C.MODEL_CACHE_PREFIX) + 1:]
        dest = os.path.join(MODELS_DIR, rel)
        if not os.path.exists(dest):
            store.download(k, dest)
    print(f"[llm] restored {len(keys)} model files from S3 cache")


def _sync_to_cache(store):
    if store.local:
        return
    n = 0
    for d, _, files in os.walk(MODELS_DIR):
        for f in files:
            p = os.path.join(d, f)
            store.upload(p, f"{C.MODEL_CACHE_PREFIX}/{os.path.relpath(p, MODELS_DIR)}")
            n += 1
    print(f"[llm] cached {n} model files to S3")


def start(store):
    if C.LLM_PROVIDER == "claude":
        if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "CHANGE_ME":
            raise RuntimeError("CLAUDE_CODE_OAUTH_TOKEN is not set - run `claude setup-token` and store it in SSM")
        return
    _start_ollama(store)


def _start_ollama(store):
    """Start `ollama serve` (if not already running) and make sure the model is present."""
    try:
        requests.get(f"{C.OLLAMA_URL}/api/tags", timeout=2)
        running = True
    except requests.RequestException:
        running = False
    if not running:
        _sync_from_cache(store)
        env = dict(os.environ, OLLAMA_MODELS=MODELS_DIR, OLLAMA_HOST=C.OLLAMA_URL.split("//")[-1])
        subprocess.Popen(["ollama", "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                requests.get(f"{C.OLLAMA_URL}/api/tags", timeout=2)
                break
            except requests.RequestException:
                time.sleep(1)
    tags = requests.get(f"{C.OLLAMA_URL}/api/tags", timeout=10).json().get("models", [])
    if not any(m["name"] in (C.OLLAMA_MODEL, C.OLLAMA_MODEL + ":latest") for m in tags):
        print(f"[llm] pulling {C.OLLAMA_MODEL} (first run only)...")
        r = requests.post(f"{C.OLLAMA_URL}/api/pull", json={"model": C.OLLAMA_MODEL, "stream": False}, timeout=3600)
        r.raise_for_status()
        _sync_to_cache(store)


def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def _claude_json(system, user, schema, retries=1):
    import tempfile
    cmd = ["claude", "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
           "--system-prompt", system, "--model", C.CLAUDE_MODEL, "--no-session-persistence",
           "--permission-mode", "dontAsk", "--max-turns", "4"]
    last = None
    for attempt in range(retries + 1):
        t0 = time.time()
        with tempfile.TemporaryDirectory() as cwd:   # empty dir: nothing for Claude Code to pick up
            r = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=cwd, timeout=C.CLAUDE_TIMEOUT)
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError:
            last = f"exit {r.returncode}: {(r.stdout or r.stderr)[-800:]}"
            print(f"[claude] unreadable output (attempt {attempt + 1}): {last}")
            continue
        if out.get("is_error") or r.returncode != 0:
            last = str(out.get("result") or out)[:800]
            print(f"[claude] error (attempt {attempt + 1}): {last}")
            if "limit" in last.lower():        # usage limit hit: let the Ollama fallback take over
                break
            continue
        data = out.get("structured_output")
        if data is None:
            try:
                data = _extract_json(out.get("result"))
            except Exception as e:
                last = f"no JSON in result: {e}"
                continue
        print(f"[claude] ok in {time.time() - t0:.0f}s")
        return data
    raise RuntimeError(f"Claude call failed: {last}")


def chat_json(system, user, schema, temperature=0.6, retries=2):
    """Ask the model for JSON matching `schema`."""
    if C.LLM_PROVIDER == "claude":
        return _claude_json(system, user, schema)
    return _ollama_json(system, user, schema, temperature, retries)


def _ollama_json(system, user, schema, temperature=0.6, retries=2):
    """Ollama structured outputs."""
    body = {
        "model": C.OLLAMA_MODEL,
        "stream": False,
        "format": schema,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": temperature, "num_ctx": 8192, "num_thread": C.OLLAMA_NUM_THREADS},
    }
    if os.environ.get("OLLAMA_THINK") is not None:     # e.g. qwen3: set OLLAMA_THINK=false
        body["think"] = os.environ["OLLAMA_THINK"].lower() == "true"
    last = None
    for attempt in range(retries + 1):
        t0 = time.time()
        r = requests.post(f"{C.OLLAMA_URL}/api/chat", json=body, timeout=1800)
        r.raise_for_status()
        content = r.json()["message"]["content"]
        try:
            out = json.loads(content)
            print(f"[llm] ok in {time.time() - t0:.0f}s")
            return out
        except json.JSONDecodeError as e:
            last = e
            print(f"[llm] bad JSON (attempt {attempt + 1}), retrying")
    raise RuntimeError(f"LLM returned invalid JSON: {last}")
