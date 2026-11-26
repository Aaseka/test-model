"""Load SAP exports (Excel or CSV) into a database the assistant can read.

1. In SAP, run a report such as ME2N, then export it:
   List > Export > Spreadsheet (or Ctrl + Shift + F7) and save as .xlsx.
2. Put the file(s) in the sap_exports folder.
3. Run:  python load_sap_export.py
4. In .env set:  DATABASE_URL=sqlite:///sap_data.db   and restart app.py.

Each file becomes one table, named after the file (ME2N_open_POs.xlsx -> me2n_open_pos).
Run this again whenever you export fresh data.
"""
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd

FOLDER = Path(__file__).parent / "sap_exports"
DB = Path(__file__).parent / "sap_data.db"


def clean_name(text: str) -> str:
    """'Net Order Value' -> 'net_order_value'"""
    text = re.sub(r"[^0-9a-zA-Z]+", "_", str(text)).strip("_").lower()
    return text or "column"


def unique(names: list) -> list:
    seen, out = {}, []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    return out


def read_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, sep=None, engine="python", encoding_errors="replace")
    else:
        df = pd.read_excel(path)
    df = df.dropna(how="all").dropna(axis=1, how="all")

    # Some SAP exports have a title line above the real header. If the first row looks
    # like the header (all text, no blanks) and the current header is mostly "Unnamed", shift it.
    if sum(str(c).startswith("Unnamed") for c in df.columns) > len(df.columns) / 2:
        df.columns = df.iloc[0]
        df = df.iloc[1:]

    df.columns = unique([clean_name(c) for c in df.columns])

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
        elif df[col].dtype == object or pd.api.types.is_string_dtype(df[col]):
            # Turn text numbers like "1,234.50" into real numbers when the whole column fits.
            as_num = pd.to_numeric(df[col].astype(str).str.replace(",", "").str.strip(), errors="coerce")
            if as_num.notna().sum() == df[col].notna().sum() and df[col].notna().any():
                df[col] = as_num
            # Turn text dates like "26.11.2026" or "2026-11-26" into yyyy-mm-dd.
            elif df[col].astype(str).str.match(r"^\d{1,4}[./-]\d{1,2}[./-]\d{2,4}$").mean() > 0.9:
                dates = pd.to_datetime(df[col], errors="coerce", dayfirst="." in str(df[col].dropna().iloc[0]))
                df[col] = dates.dt.strftime("%Y-%m-%d")
    return df


def main():
    FOLDER.mkdir(exist_ok=True)
    files = sorted(p for p in FOLDER.iterdir() if p.suffix.lower() in (".xlsx", ".xls", ".csv"))
    if not files:
        sys.exit(f"No .xlsx or .csv files found in {FOLDER}. Export from SAP and put them there first.")

    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    for path in files:
        table = clean_name(path.stem)
        try:
            df = read_file(path)
        except Exception as e:
            print(f"Skipped {path.name}: {e}")
            continue
        df.to_sql(table, con, index=False)
        print(f"{path.name} -> table '{table}': {len(df)} rows")
        print("   columns: " + ", ".join(df.columns))
    con.close()
    print(f"\nDone. Set DATABASE_URL=sqlite:///sap_data.db in .env, then restart app.py.")


if __name__ == "__main__":
    main()
