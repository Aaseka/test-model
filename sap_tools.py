"""Read-only access to purchasing data, plus the tools the AI model can call.

Works with any database SQLAlchemy can reach. Set DATABASE_URL in .env:
  demo:         sqlite:///demo_purchasing.db
  SAP HANA:     hana://READONLY_USER:password@host:30015     (pip install sqlalchemy-hana)
  Postgres:     postgresql://user:password@host/db            (pip install psycopg2-binary)

The tables use SAP purchasing names: EKKO, EKPO, EKET, LFA1, MAKT.
If your real system uses different names, edit SCHEMA and the SQL in REPORTS below.
"""
import os
import re
from datetime import date

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///demo_purchasing.db")
MAX_ROWS = int(os.getenv("MAX_ROWS", "200"))

# Open the demo SQLite file in read-only mode. For a real database, use a login
# that only has SELECT rights. That is the real protection.
if DATABASE_URL.startswith("sqlite:///"):
    _path = os.path.abspath(DATABASE_URL[len("sqlite:///"):])
    engine = create_engine(f"sqlite:///file:{_path}?mode=ro&uri=true")
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)


# What the model reads to understand the data.
SCHEMA = """
Tables (SAP purchasing names, dates are yyyy-mm-dd, currency CAD):
  LFA1  vendors:          LIFNR vendor id, NAME1 vendor name, LAND1 country, ORT01 city
  MAKT  materials:        MATNR material number, MAKTX description, MATKL material group, MEINS unit
  EKKO  PO header:        EBELN PO number, LIFNR vendor, BEDAT PO date, EKGRP buyer group, WAERS currency, STATUS OPEN or CLOSED
  EKPO  PO lines:         EBELN, EBELP line number, MATNR, MENGE quantity, NETPR unit price, NETWR line value, WERKS plant
  EKET  delivery dates:   EBELN, EBELP, EINDT promised date, WEMNG quantity received, LAST_GR_DATE last goods receipt
Joins: EKKO.EBELN = EKPO.EBELN, EKPO (EBELN, EBELP) = EKET (EBELN, EBELP),
       EKKO.LIFNR = LFA1.LIFNR, EKPO.MATNR = MAKT.MATNR
Definitions: open line = WEMNG < MENGE. Overdue = open line and EINDT before today. Spend = SUM(NETWR).
"""


# Ready-made reports. Small local models pick these far more reliably than
# they write SQL. Add one for every question your team asks often.
# :name values are filled in safely from the model's inputs.
REPORTS = {
    "overdue_po_lines": {
        "description": "PO lines past their promised delivery date that are not fully received.",
        "inputs": {"vendor": "Optional. Part of a vendor name."},
        "sql": """
            SELECT k.EBELN AS po, p.EBELP AS line, l.NAME1 AS vendor, m.MAKTX AS material,
                   p.MENGE AS ordered, e.WEMNG AS received, e.EINDT AS promised, p.WERKS AS plant
            FROM EKPO p
            JOIN EKKO k ON k.EBELN = p.EBELN
            JOIN EKET e ON e.EBELN = p.EBELN AND e.EBELP = p.EBELP
            JOIN LFA1 l ON l.LIFNR = k.LIFNR
            LEFT JOIN MAKT m ON m.MATNR = p.MATNR
            WHERE e.WEMNG < p.MENGE AND e.EINDT < :today
              AND (:vendor IS NULL OR UPPER(l.NAME1) LIKE '%' || UPPER(:vendor) || '%')
            ORDER BY e.EINDT""",
    },
    "spend_by_vendor": {
        "description": "Total PO spend per vendor, highest first, for an optional PO date range.",
        "inputs": {"from_date": "Optional. yyyy-mm-dd", "to_date": "Optional. yyyy-mm-dd"},
        "sql": """
            SELECT l.NAME1 AS vendor, COUNT(DISTINCT k.EBELN) AS pos, ROUND(SUM(p.NETWR), 2) AS spend_cad
            FROM EKPO p
            JOIN EKKO k ON k.EBELN = p.EBELN
            JOIN LFA1 l ON l.LIFNR = k.LIFNR
            WHERE (:from_date IS NULL OR k.BEDAT >= :from_date)
              AND (:to_date IS NULL OR k.BEDAT <= :to_date)
            GROUP BY l.NAME1
            ORDER BY spend_cad DESC""",
    },
    "on_time_delivery": {
        "description": "On-time delivery rate per vendor, worst first.",
        "inputs": {},
        "sql": """
            SELECT l.NAME1 AS vendor, COUNT(*) AS deliveries,
                   ROUND(100.0 * SUM(CASE WHEN e.LAST_GR_DATE <= e.EINDT THEN 1 ELSE 0 END) / COUNT(*), 1) AS on_time_pct
            FROM EKET e
            JOIN EKKO k ON k.EBELN = e.EBELN
            JOIN LFA1 l ON l.LIFNR = k.LIFNR
            WHERE e.LAST_GR_DATE IS NOT NULL
            GROUP BY l.NAME1
            ORDER BY on_time_pct""",
    },
    "price_history": {
        "description": "Prices paid for a material over time, newest first. Use for 'what did we last pay for X'.",
        "inputs": {"material": "Material number or part of its description."},
        "sql": """
            SELECT k.BEDAT AS po_date, k.EBELN AS po, l.NAME1 AS vendor, p.MATNR AS material,
                   m.MAKTX AS description, p.NETPR AS unit_price, p.MENGE AS quantity
            FROM EKPO p
            JOIN EKKO k ON k.EBELN = p.EBELN
            JOIN LFA1 l ON l.LIFNR = k.LIFNR
            LEFT JOIN MAKT m ON m.MATNR = p.MATNR
            WHERE p.MATNR = :material OR UPPER(m.MAKTX) LIKE '%' || UPPER(:material) || '%'
            ORDER BY k.BEDAT DESC""",
    },
    "po_details": {
        "description": "Every line of one purchase order with vendor, price and delivery status.",
        "inputs": {"po_number": "The PO number, for example 4500000105."},
        "sql": """
            SELECT k.EBELN AS po, k.BEDAT AS po_date, k.STATUS AS status, l.NAME1 AS vendor,
                   p.EBELP AS line, m.MAKTX AS material, p.MENGE AS quantity, p.NETPR AS unit_price,
                   p.NETWR AS line_value, e.EINDT AS promised, e.WEMNG AS received
            FROM EKKO k
            JOIN EKPO p ON p.EBELN = k.EBELN
            JOIN LFA1 l ON l.LIFNR = k.LIFNR
            LEFT JOIN EKET e ON e.EBELN = p.EBELN AND e.EBELP = p.EBELP
            LEFT JOIN MAKT m ON m.MATNR = p.MATNR
            WHERE k.EBELN = :po_number
            ORDER BY p.EBELP""",
    },
}

_WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|exec|execute|call|attach|pragma)\b",
    re.IGNORECASE,
)


def _run(sql: str, params: dict | None = None) -> dict:
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            columns = list(result.keys())
            rows = result.fetchmany(MAX_ROWS + 1)
    except Exception as e:
        return {"error": str(e).split("\n")[0][:500]}
    return {
        "columns": columns,
        "rows": [[v if isinstance(v, (int, float, str, type(None))) else str(v) for v in r] for r in rows[:MAX_ROWS]],
        "row_count": min(len(rows), MAX_ROWS),
        "truncated": len(rows) > MAX_ROWS,
    }


def run_custom_sql(sql: str) -> dict:
    """Fallback for questions no report covers. One SELECT only."""
    sql = sql.strip().rstrip(";").strip()
    if ";" in sql:
        return {"error": "Only one statement is allowed."}
    if not re.match(r"^(select|with)\b", sql, re.IGNORECASE) or _WRITE_WORDS.search(sql):
        return {"error": "Only read-only SELECT queries are allowed."}
    return _run(sql)


def run_tool(name: str, args: dict) -> dict:
    """Called by app.py when the model asks for a tool."""
    args = args or {}
    if name == "custom_query":
        return run_custom_sql(args.get("sql", ""))
    if name in REPORTS:
        params = {key: (args.get(key) or None) for key in REPORTS[name]["inputs"]}
        params["today"] = date.today().isoformat()
        return _run(REPORTS[name]["sql"], params)
    return {"error": f"Unknown tool: {name}"}


def tool_definitions() -> list:
    """The tool list in the format Ollama expects."""
    tools = []
    for name, report in REPORTS.items():
        tools.append({"type": "function", "function": {
            "name": name,
            "description": report["description"],
            "parameters": {
                "type": "object",
                "properties": {k: {"type": "string", "description": d} for k, d in report["inputs"].items()},
                "required": [k for k, d in report["inputs"].items() if not d.startswith("Optional")],
            },
        }})
    tools.append({"type": "function", "function": {
        "name": "custom_query",
        "description": f"Run one read-only SQL SELECT when no other tool fits. Returns at most {MAX_ROWS} rows, "
                       "so use SUM, COUNT and GROUP BY rather than pulling raw rows.",
        "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
    }})
    return tools
