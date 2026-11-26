"""Purchasing Assistant server.

Start it with:  python app.py
Then open:      http://localhost:8000

It serves the chat page (index.html) and one API endpoint that passes questions
between an AI model and the read-only reports in sap_tools.py.

The AI model is any service with an OpenAI-style API. Set it in .env:
  Azure OpenAI:     LLM_BASE_URL=https://YOUR-RESOURCE.openai.azure.com/openai/v1
  Gemini:           LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
  Ollama (local):   LLM_BASE_URL=http://localhost:11434/v1
"""
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

load_dotenv()
import sap_tools  # noqa: E402  (reads DATABASE_URL from .env, so load it first)

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gemini-flash-latest")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
LOG_FILE = os.getenv("LOG_FILE", "question_log.jsonl")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
PAGE = Path(__file__).parent / "index.html"
# Free plans limit how much text you can send per minute, so tool results are kept short.
MAX_RESULT_CHARS = int(os.getenv("MAX_RESULT_CHARS", "6000"))


class ModelError(Exception):
    """An error to show the user as-is."""


def system_prompt() -> str:
    return f"""You help a purchasing team answer questions about purchase orders, vendors,
spend, deliveries and materials. Today is {date.today().isoformat()}.
{sap_tools.SCHEMA}
Rules:
- Get every number from a tool. Never guess PO numbers, prices or dates.
- Use the ready-made reports first if there are any. Otherwise query the data directly.
- If a tool returns an error, fix the input and try again.
- Reply with a one sentence answer, then a short markdown table if it helps.
- Show vendor names and money with 2 decimals and the currency.
- Say what you assumed, such as the date range.
- People may attach photos, such as a quote, invoice, packing slip or part label. Read the
  details that matter (part numbers, prices, quantities, PO numbers, vendor) and then check
  them against the data with the tools. For example, compare a quoted price with price_history.
- You can only read data. For creating or changing a PO, tell them to use SAP (ME21N or ME22N)."""


def call_model(messages: list) -> dict:
    """Send the conversation to the AI service and return its reply message."""
    if not LLM_API_KEY and "localhost" not in LLM_BASE_URL:
        raise ModelError("No API key set. Add LLM_API_KEY to .env and restart.")
    payload = {"model": MODEL, "messages": messages, "tools": sap_tools.tool_definitions(),
               "temperature": 0.1, "max_tokens": 1500}
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "api-key": LLM_API_KEY}  # api-key is what Azure uses

    for attempt in range(2):
        try:
            r = requests.post(f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers, timeout=120)
        except requests.ConnectionError:
            raise ModelError(f"Can't reach the AI service at {LLM_BASE_URL}. Check the internet connection.")
        if r.status_code == 429:
            wait = float(r.headers.get("retry-after", "10") or 10)
            if attempt == 0 and wait <= 20:
                time.sleep(wait)  # free plan limit hit, wait once and retry
                continue
            raise ModelError("The free AI plan's limit was reached. Wait a minute and try again.")
        if r.status_code in (401, 403):
            raise ModelError("The AI service rejected the API key. Check LLM_API_KEY in .env.")
        if r.status_code >= 400:
            try:
                detail = r.json().get("error", {}).get("message", r.text)
            except ValueError:
                detail = r.text
            raise ModelError(f"The AI service returned an error: {detail[:300]}")
        return r.json()["choices"][0]["message"]
    raise ModelError("The AI service is busy. Try again in a minute.")


def to_model_messages(history: list) -> list:
    """Chat history in the OpenAI format. Photos only go with the newest question,
    which keeps follow-ups fast. Earlier answers already describe older photos."""
    history = history[-20:]
    messages = [{"role": "system", "content": system_prompt()}]
    for i, msg in enumerate(history):
        text = msg.get("content", "")
        images = msg.get("images") or []
        if images and i == len(history) - 1:
            parts = [{"type": "text", "text": text}]
            parts += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in images]
            messages.append({"role": msg["role"], "content": parts})
        else:
            if images:
                text += f"\n(The user attached {len(images)} photo(s) here.)"
            messages.append({"role": msg["role"], "content": text})
    return messages


def ask_model(history: list) -> tuple[str, list]:
    """Send the chat to the model. Run any tools it asks for. Repeat until it answers.
    Returns the answer and a list of the reports that were run."""
    messages = to_model_messages(history)
    steps = []
    for _ in range(6):
        message = call_model(messages)
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            answer = message.get("content") or ""
            answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)  # hide reasoning text
            return answer.strip(), steps

        messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})
        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = sap_tools.run_tool(name, args)
            steps.append({"tool": name, "inputs": args,
                          "result": result.get("error") or f"{result['row_count']} rows"})
            content = json.dumps(result)
            if len(content) > MAX_RESULT_CHARS:
                content = content[:MAX_RESULT_CHARS] + ' ... (cut short, use SUM, COUNT or GROUP BY for fewer rows)"'
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
    return "That took too many steps. Try asking a narrower question.", steps


app = FastAPI()


@app.get("/")
def page():
    return FileResponse(PAGE)


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/api/status")
def status():
    problem = getattr(sap_tools, "ODATA_ERROR", "")
    if not LLM_API_KEY and "localhost" not in LLM_BASE_URL:
        problem = "No AI API key is set. Add LLM_API_KEY to the .env file, then restart app.py."
    data = (sap_tools.SAP_ODATA_URL.split("/")[-1] + " (live SAP)") if sap_tools.SAP_ODATA_URL \
        else sap_tools.DATABASE_URL.split("@")[-1].split("/")[-1]
    return {"model": MODEL, "ready": not problem, "problem": problem, "data": data,
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
    except ModelError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": f"Something went wrong: {e}"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    print(f"Purchasing Assistant running at http://localhost:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
