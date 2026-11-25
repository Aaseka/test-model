"""Build a demo purchasing database that mirrors SAP's table names.

Tables (same names/fields SAP ECC / S/4HANA uses, simplified):
  LFA1  - vendor master
  MAKT  - material descriptions (merged with a few MARA fields)
  EKKO  - purchase order header
  EKPO  - purchase order items
  EKET  - delivery schedule (promised date, qty received)

Run:  python seed_demo_db.py   -> creates demo_purchasing.db
"""
import random
import sqlite3
from datetime import date, timedelta

random.seed(42)
DB = "demo_purchasing.db"

VENDORS = [
    ("100001", "Nordic Steel AB", "SE", "Gothenburg"),
    ("100002", "Ontario Fasteners Inc", "CA", "Mississauga"),
    ("100003", "Shenzhen ElectroParts", "CN", "Shenzhen"),
    ("100004", "Midwest Plastics LLC", "US", "Detroit"),
    ("100005", "Bavaria Thermal GmbH", "DE", "Munich"),
    ("100006", "Great Lakes Packaging", "CA", "Windsor"),
    ("100007", "Monterrey Castings SA", "MX", "Monterrey"),
    ("100008", "Kyoto Sensors KK", "JP", "Kyoto"),
]

MATERIALS = [  # MATNR, description, material group, unit, base price
    ("MAT-1001", "Aluminium tube 12mm", "RAW", "M", 4.20),
    ("MAT-1002", "Steel bracket A-type", "MECH", "EA", 1.85),
    ("MAT-1003", "M6 hex bolt zinc", "FAST", "EA", 0.06),
    ("MAT-1004", "Compressor control PCB", "ELEC", "EA", 38.00),
    ("MAT-1005", "Temperature sensor NTC", "ELEC", "EA", 2.75),
    ("MAT-1006", "HVAC hose EPDM 3/4in", "RUBB", "M", 6.10),
    ("MAT-1007", "Radiator fin stock", "RAW", "KG", 3.40),
    ("MAT-1008", "Corrugated shipping box L", "PACK", "EA", 1.10),
    ("MAT-1009", "Cast aluminium housing", "MECH", "EA", 22.50),
    ("MAT-1010", "Plastic fan shroud", "PLAS", "EA", 9.80),
    ("MAT-1011", "Expansion valve TXV", "MECH", "EA", 31.00),
    ("MAT-1012", "Wiring harness 8-pin", "ELEC", "EA", 12.40),
]

# Which vendors supply which material groups
SUPPLY = {
    "100001": ["RAW", "MECH"], "100002": ["FAST", "MECH"], "100003": ["ELEC"],
    "100004": ["PLAS", "RUBB"], "100005": ["MECH", "RAW"], "100006": ["PACK"],
    "100007": ["MECH"], "100008": ["ELEC"],
}
PLANTS = ["1000", "1100", "2000"]          # e.g. 1000=Toronto, 1100=Belleville, 2000=Michigan
PGROUPS = ["P01", "P02", "P03"]            # purchasing groups (buyers)


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.executescript("""
    DROP TABLE IF EXISTS LFA1; DROP TABLE IF EXISTS MAKT; DROP TABLE IF EXISTS EKKO;
    DROP TABLE IF EXISTS EKPO; DROP TABLE IF EXISTS EKET;
    CREATE TABLE LFA1 (LIFNR TEXT PRIMARY KEY, NAME1 TEXT, LAND1 TEXT, ORT01 TEXT);
    CREATE TABLE MAKT (MATNR TEXT PRIMARY KEY, MAKTX TEXT, MATKL TEXT, MEINS TEXT);
    CREATE TABLE EKKO (EBELN TEXT PRIMARY KEY, LIFNR TEXT, BUKRS TEXT, BEDAT DATE,
                       EKGRP TEXT, WAERS TEXT, STATUS TEXT);
    CREATE TABLE EKPO (EBELN TEXT, EBELP INTEGER, MATNR TEXT, MENGE REAL, MEINS TEXT,
                       NETPR REAL, NETWR REAL, WERKS TEXT, PRIMARY KEY (EBELN, EBELP));
    CREATE TABLE EKET (EBELN TEXT, EBELP INTEGER, EINDT DATE, WEMNG REAL, LAST_GR_DATE DATE,
                       PRIMARY KEY (EBELN, EBELP));
    """)
    cur.executemany("INSERT INTO LFA1 VALUES (?,?,?,?)", VENDORS)
    cur.executemany("INSERT INTO MAKT VALUES (?,?,?,?)", [m[:4] for m in MATERIALS])

    today = date(2026, 11, 16)
    po_num = 4500000100
    for _ in range(140):
        vendor = random.choice(VENDORS)[0]
        mats = [m for m in MATERIALS if m[2] in SUPPLY[vendor]]
        bedat = today - timedelta(days=random.randint(0, 330))
        status = "OPEN"
        cur.execute("INSERT INTO EKKO VALUES (?,?,?,?,?,?,?)",
                    (str(po_num), vendor, "CA01", bedat.isoformat(),
                     random.choice(PGROUPS), "CAD", status))
        all_received = True
        for item_no in range(10, 10 * random.randint(1, 4) + 1, 10):
            m = random.choice(mats)
            qty = random.choice([50, 100, 250, 500, 1000, 5000]) if m[4] < 5 else random.choice([10, 25, 50, 100, 200])
            price = round(m[4] * random.uniform(0.9, 1.15), 2)
            werks = random.choice(PLANTS)
            cur.execute("INSERT INTO EKPO VALUES (?,?,?,?,?,?,?,?)",
                        (str(po_num), item_no, m[0], qty, m[3], price, round(qty * price, 2), werks))
            eindt = bedat + timedelta(days=random.randint(14, 60))
            if eindt < today and random.random() < 0.8:
                late = random.random() < 0.25
                gr_date = eindt + timedelta(days=random.randint(1, 20) if late else -random.randint(0, 5))
                gr_date = min(gr_date, today)
                received = qty if random.random() < 0.9 else round(qty * random.uniform(0.3, 0.9))
            else:
                gr_date, received = None, 0
            if received < qty:
                all_received = False
            cur.execute("INSERT INTO EKET VALUES (?,?,?,?,?)",
                        (str(po_num), item_no, eindt.isoformat(), received,
                         gr_date.isoformat() if gr_date else None))
        if all_received:
            cur.execute("UPDATE EKKO SET STATUS='CLOSED' WHERE EBELN=?", (str(po_num),))
        po_num += 1
    con.commit()
    n = cur.execute("SELECT COUNT(*) FROM EKKO").fetchone()[0]
    print(f"Created {DB} with {n} purchase orders.")
    con.close()


if __name__ == "__main__":
    main()
