# Purchasing Assistant

A chat page where the purchasing team asks questions like "which PO lines are overdue?"
and gets answers from live data. It runs on free tools (Ollama and Python), stays on your
own network, and can only read data. People can also attach photos of quotes, invoices or
part labels.

## Files

| File | What it is |
|---|---|
| `.env` | Settings: model, database, port, team password |
| `sap_tools.py` | The database connection and the reports the AI can run |
| `app.py` | The server: runs the page and passes questions between the model and the reports |
| `index.html` | The chat page (plain HTML, CSS and JavaScript) |
| `seed_demo_db.py` | Creates `demo_purchasing.db`, fake data that uses SAP table names |
| `requirements.txt`, `Dockerfile`, `docker-compose.yml` | For installing, and for IT later |

## Run it on your laptop

1. Install Python 3.11 or newer and Ollama (ollama.com).
2. Download the model: `ollama pull qwen3-vl:8b`
3. In this folder:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python seed_demo_db.py
python app.py
```

Then open http://localhost:8000. To stop it, press Ctrl + C in the terminal.

On a Mac, use `source .venv/bin/activate` instead.
If Windows says "running scripts is disabled", run
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once.

## Let coworkers use it from your machine

In `.env`, set `HOST=0.0.0.0` and a team password in `APP_PASSWORD`, then restart.
Coworkers open `http://<your-computer's-IP>:8000`. Find the IP with `ipconfig`.

## Add a report

Open `sap_tools.py` and add an entry to `REPORTS`: a description (the AI picks reports by
reading it), the inputs it needs, and the SQL. Restart `app.py`. Check `question_log.jsonl`
to see what people ask most, then add reports for those questions.

## Use real SAP data

Ask IT for read-only access, either a database login (SAP HANA, a reporting copy, a nightly
export) or SAP's OData web API. For a database, change `DATABASE_URL` in `.env`. If the
table or column names differ from the demo, update `SCHEMA` and the SQL in `sap_tools.py`.

## Handing it to IT

Send the folder without `.venv` and without real passwords in `.env`. IT runs:

```
docker compose up -d
docker compose exec ollama ollama pull qwen3-vl:8b
```

People then open `http://<server>:8000`. Set `APP_PASSWORD` in `.env` so only the team
can use it. For quick answers with 5 to 10 users, the server needs an NVIDIA GPU with
12 to 16 GB of memory. Without one it works, but answers take 20 to 60 seconds.
