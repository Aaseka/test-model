"""Purchasing Assistant server.

Start it with:  python app.py
Then open:      http://localhost:8000

It serves the chat page (index.html) and one API endpoint that passes questions
between the AI model (Ollama) and the read-only reports in sap_tools.py.
"""
import json
import os
from datetime import date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

load_dotenv()
import sap_tools  # noqa: E402  (reads DATABASE_URL from .env, so load it first)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3-vl:8b")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
LOG_FILE = os.getenv("LOG_FILE", "question_log.jsonl")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
PAGE = Path(__file__).parent / "index.html"


def system_prompt() -> str:
    return f"""You help a purchasing team answer questions about purchase orders, vendors,
spend, deliveries and materials. Today is {date.today().isoformat()}.
{sap_tools.SCHEMA}
Rules:
- Get every number from a tool. Never guess PO numbers, prices or dates.
- Use the ready-made reports first. Use custom_query only if none of them fits.
- If a tool returns an error, fix the input and try again.
- Reply with a one sentence answer, then a short markdown table if it helps.
- Show vendor names and money with 2 decimals and the currency.
- Say what you assumed, such as the date range.
- People may attach photos, such as a quote, invoice, packing slip or part label. Read the
  details that matter (part numbers, prices, quantities, PO numbers, vendor) and then check
  them against the data with the tools. For example, compare a quoted price with price_history.
- You can only read data. For creating or changing a PO, tell them to use SAP (ME21N or ME22N)."""


def call_ollama(messages: list) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": sap_tools.tool_definitions(),
        "stream": False,
        "think": False,  # skip the slow "thinking" step on models that have one
        "options": {"temperature": 0.1, "num_ctx": 16384},
    }
    response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
    if response.status_code == 400 and "think" in response.text:
        del payload["think"]  # this model has no thinking step
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
    if response.status_code >= 400:
        raise RuntimeError(response.json().get("error", response.text))
    return response.json()["message"]


def ask_model(history: list) -> tuple[str, list]:
    """Send the chat to the model. Run any tools it asks for. Repeat until it answers.
    Returns the answer and a list of the reports that were run."""
    messages = [{"role": "system", "content": system_prompt()}]
    for i, msg in enumerate(history[-20:]):
        entry = {"role": msg["role"], "content": msg.get("content", "")}
        images = msg.get("images") or []
        if images and i == len(history[-20:]) - 1:
            entry["images"] = images  # photos only go with the newest question
        elif images:
            entry["content"] += f"\n(The user attached {len(images)} photo(s) here.)"
        messages.append(entry)

    steps = []
    for _ in range(8):
        message = call_ollama(messages)
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return (message.get("content") or "").strip(), steps

        messages.append(message)
        for call in tool_calls:
            name = call["function"]["name"]
            args = call["function"].get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            result = sap_tools.run_tool(name, args)
            steps.append({"tool": name, "inputs": args,
                          "result": result.get("error") or f"{result['row_count']} rows"})
            messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result)[:30000]})
    return "That took too many steps. Try asking a narrower question.", steps


def ollama_is_running() -> bool:
    try:
        return requests.get(OLLAMA_URL, timeout=2).ok
    except requests.RequestException:
        return False


app = FastAPI()


@app.get("/")
def page():
    return FileResponse(PAGE)


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/api/status")
def status():
    return {"model": MODEL, "model_running": ollama_is_running(),
            "data": sap_tools.DATABASE_URL.split("@")[-1].split("/")[-1],
            "password_required": bool(APP_PASSWORD)}


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    if APP_PASSWORD and body.get("password") != APP_PASSWORD:
        return JSONResponse({"error": "Wrong team password."}, status_code=401)

    history = body.get("messages", [])
    question = history[-1].get("content", "") if history else ""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"),
                            "name": body.get("name", "local"), "question": question,
                            "photos": len(history[-1].get("images") or []) if history else 0}) + "\n")
    try:
        answer, steps = ask_model(history)
        return {"answer": answer, "steps": steps}
    except requests.ConnectionError:
        return JSONResponse({"error": "Can't reach the AI model. Check that Ollama is running."}, status_code=503)
    except Exception as e:
        return JSONResponse({"error": f"The model returned an error: {e}"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    print(f"Purchasing Assistant running at http://localhost:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
