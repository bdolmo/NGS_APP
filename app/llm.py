import os
import requests
from flask import Blueprint, request, jsonify
from app import app, db
from sqlalchemy.orm import joinedload
from app.models import Pipeline, PipelineParam, PipelineConfig

# Config (override via env vars if you want)
OLLAMA_BASE = os.getenv("OLLAMA_URL_BASE", "http://127.0.0.1:11434")
OLLAMA_GEN  = f"{OLLAMA_BASE}/api/generate"
# MODEL_NAME  = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
MODEL_NAME  = os.getenv("OLLAMA_MODEL", "gemma3:270m")

# gemma3:270m

# Sensible, CPU-friendly defaults (tweak as needed)
DEFAULT_OPTIONS = {
    "num_ctx": 8048,       # reduce if you're tight on RAM; 512–1024 is fine for short prompts
    "num_predict": 8048,    # cap output length
    "temperature": 0.2,
    "num_thread": 8,       # try 6–10 on your EPYC; benchmark a bit
}
TIMEOUT_SECS = 180

def ask_llm(prompt: str, model: str = MODEL_NAME, options: dict | None = None) -> dict:
    """Send a single-turn prompt to Ollama and return response + basic meta."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {**DEFAULT_OPTIONS, **(options or {})},
        # keep the model in RAM for faster subsequent calls
        "keep_alive": "30m",
    }
    r = requests.post(OLLAMA_GEN, json=payload, timeout=TIMEOUT_SECS)
    r.raise_for_status()
    data = r.json()
    # Ollama returns fields like: response, total_duration, load_duration, eval_count, prompt_eval_count
    return {
        "text": data.get("response", "").strip(),
        "meta": {
            "eval_count": data.get("eval_count"),
            "prompt_eval_count": data.get("prompt_eval_count"),
            "total_duration": data.get("total_duration"),
            "load_duration": data.get("load_duration"),
            "model": model,
        },
    }

@app.route("/llm/ask", methods=["POST"])
def llm_ask():
    """
    JSON body:
    {
      "question": "string",
      "model": "qwen2.5:0.5b",     // optional
      "options": { "num_ctx": 512 }  // optional
    }
    """
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Missing 'question'"}), 400

    model = body.get("model") or MODEL_NAME
    options = body.get("options") or {}

    try:
        result = ask_llm(question, model=model, options=options)
        return jsonify({"answer": result["text"], "meta": result["meta"]})
    except requests.RequestException as e:
        return jsonify({"error": "Ollama request failed", "details": str(e)}), 502
