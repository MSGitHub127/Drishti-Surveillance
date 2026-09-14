"""
Add Custom Vehicle Number Plate to Watchlist
Usage:
    python scripts/add_custom_plate.py --plate "GJ01XX1234" --name "Demo Suspect" --severity "CRITICAL"
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path

def normalize_plate(plate: str) -> str:
    return "".join(c for c in plate.upper() if c.isalnum())

def add_plate(
    plate_number: str,
    person_name: str = "Demo Registered Owner",
    category: str = "Stolen Vehicle",
    severity: str = "CRITICAL",
    notes: str = "Target vehicle added for live demonstration evaluation.",
    police_station: str = "Vastrapur Police Station, Ahmedabad",
    source_dept: str = "eGujCop"
):
    norm_plate = normalize_plate(plate_number)
    repo_root = Path(__file__).resolve().parent.parent
    seed_json_path = repo_root / "data" / "seed_watchlist.json"
    db_path = repo_root / "data" / "cctv_local.db"

    print(f"[+] Registering plate: {plate_number} (Normalized: {norm_plate})")

    # 1. Update data/seed_watchlist.json
    wl_id = f"wl-demo-{norm_plate.lower()}"
    new_entry = {
        "id": wl_id,
        "plate_number": plate_number.upper(),
        "normalized_plate": norm_plate,
        "person_name": person_name,
        "category": category,
        "source_dept": source_dept,
        "fir_number": f"FIR-2026/{norm_plate[-4:]}-DEMO",
        "police_station": police_station,
        "vehicle_make_model": "Demonstration Target Vehicle",
        "vehicle_color": "Silver/White",
        "severity": severity.upper(),
        "notes": notes,
        "active": True
    }

    if seed_json_path.exists():
        with open(seed_json_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception:
                data = []

        # Replace existing or append
        updated = False
        for i, item in enumerate(data):
            if item.get("normalized_plate") == norm_plate or item.get("plate_number") == plate_number.upper():
                data[i] = new_entry
                updated = True
                break
        if not updated:
            data.insert(0, new_entry)

        with open(seed_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"  [OK] Saved to seed watchlist file: {seed_json_path.name}")
    else:
        print(f"  [!] Seed file not found at {seed_json_path}")

    # 2. Update data/cctv_local.db if it exists
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT id FROM watchlist WHERE normalized_plate = ? OR plate_number = ?", (norm_plate, plate_number.upper()))
            row = cur.fetchone()
            if row:
                cur.execute("""
                    UPDATE watchlist 
                    SET person_name = ?, category = ?, severity = ?, notes = ?, active = 1
                    WHERE id = ?
                """, (person_name, category, severity.upper(), notes, row[0]))
                print(f"  [OK] Updated existing database record in SQLite ({row[0]})")
            else:
                cur.execute("""
                    INSERT INTO watchlist (
                        id, plate_number, normalized_plate, person_name, category,
                        source_dept, fir_number, police_station, vehicle_make_model,
                        vehicle_color, severity, notes, active, date_added
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
                """, (
                    wl_id, plate_number.upper(), norm_plate, person_name, category,
                    source_dept, f"FIR-2026/{norm_plate[-4:]}-DEMO", police_station,
                    "Demonstration Target Vehicle", "Silver/White", severity.upper(), notes
                ))
                print(f"  [OK] Inserted new record into SQLite database ({wl_id})")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"  [!] SQLite update note: {e}")

    print("\n" + "=" * 60)
    print(f"SUCCESS: Plate '{norm_plate}' is now an ACTIVE WATCHLIST TARGET!")
    print(f"Severity: {severity.upper()} | Category: {category}")
    print("When this plate appears in ANY camera or video feed, the system")
    print("will immediately trigger a CRITICAL audio-visual alert and map trace.")
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add custom plate to Watchlist")
    parser.add_argument("--plate", type=str, required=True, help="Vehicle registration number (e.g. GJ01AB1234)")
    parser.add_argument("--name", type=str, default="Demo Evaluation Target", help="Registered person name")
    parser.add_argument("--category", type=str, default="Stolen Vehicle", help="Category: Stolen Vehicle, Wanted Criminal, etc.")
    parser.add_argument("--severity", type=str, default="CRITICAL", help="Severity: CRITICAL, HIGH, MEDIUM")
    parser.add_argument("--notes", type=str, default="Evaluator vehicle designated for live demonstration.", help="Notes")
    args = parser.parse_args()

    add_plate(
        plate_number=args.plate,
        person_name=args.name,
        category=args.category,
        severity=args.severity,
        notes=args.notes
    )
