# Purchasing Assistant

An AI agent for the purchasing team. People ask questions like "which POs from Nordic Steel
are still open?" in a chat page (or a Teams tab), and the AI looks up the answer in SAP.
It can only read data. People can also attach photos of quotes, invoices or part labels.

The proof of concept is free: fake purchasing data plus Google Gemini's free API. Because the
data is fake, it doesn't matter that Gemini's free tier may use what it is sent. For real SAP
data, IT changes a few lines in `.env` to an approved AI service and the SAP link.

## Files

| File | What it is |
|---|---|
| `.env` | All settings: AI key, SAP link and login, team password |
| `app.py` | The server: runs the chat page and the AI agent loop |
| `index.html` | The chat page |
| `sap_tools.py` | How the AI reads data: live SAP (OData), SAP exports, or the demo database |
| `load_sap_export.py` | Loads SAP Excel exports, if you don't have the OData link yet |
| `seed_demo_db.py`, `demo_purchasing.db` | Fake data with SAP table names, for testing |
| `Dockerfile`, `docker-compose.yml` | For IT, when they host it |

## 1. Run it on your PC

1. Go to aistudio.google.com, sign in with a Google account, click Get API key, and paste it
   into `.env` after `LLM_API_KEY=`. Only use it with the fake data.
2. In this folder:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

3. Open http://localhost:8000. It starts with the demo data.

## 2. Connect live SAP (the OData link), with IT

Do this only after the AI line in `.env` points to a service IT has approved for company
data (for example Azure OpenAI, or Ollama on a company server). Never send real SAP data to
the free Gemini key.


Ask IT for:
- the OData URL for purchase orders, for example
  `https://sap-server:44300/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV`
- a read-only SAP user for the app
- the SAP client number, if your system uses one

Put them in `.env` (`SAP_ODATA_URL`, `SAP_USER`, `SAP_PASSWORD`, `SAP_CLIENT`) and restart
`app.py`. The sidebar then says "live SAP". At startup the app reads the service's field list,
so the AI knows what it can ask for. If SAP uses an internal certificate and you get a
certificate error, set `SAP_VERIFY_TLS` to the path of the company certificate file (ask IT).

No data gateway is needed, because the app runs inside the company network.

## 3. Let the team use it

1. In `.env`, set `HOST=0.0.0.0` and a team password in `APP_PASSWORD`. Restart.
2. Find your PC's address with `ipconfig` (the IPv4 address, like `10.20.5.31`).
3. Coworkers open `http://10.20.5.31:8000`. They need to be on the office network or VPN.
4. To put it in Teams: in a channel, click +, choose Website, and paste that address.

Your PC has to stay on and awake while people use it. If Windows Firewall blocks coworkers,
allow Python when Windows asks.

## No OData link yet? Use SAP exports

Export a report from SAP GUI (for example ME2N, then List > Export > Spreadsheet), put the
.xlsx in `sap_exports`, run `python load_sap_export.py`, and set
`DATABASE_URL=sqlite:///sap_data.db` in `.env`. Leave `SAP_ODATA_URL` empty.

## Handing it to IT

Send the folder without `.venv`, and without real keys or passwords in `.env` (send
`.env.example` instead). IT fills in `.env` on their server and runs:

```
docker compose up -d
```

People then use `http://<server>:8000`, and the Teams tab points there instead of your PC.
The server needs no GPU, only outbound internet access to Azure OpenAI and network
access to SAP.
