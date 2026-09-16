"""Build static JSON reports from the CFS TSV."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TSV = next(ROOT.glob("Calls For Service Incidents*.tsv"))
OUT = ROOT / "public" / "data"
AGENT = Path(
    r"C:\Users\pfaus\.cursor\projects\c-Dev-github-projects-burbank-police-incidents\agent-tools"
)

MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def parse_date(s: str) -> datetime | None:
    parts = s.strip().split("-")
    if len(parts) != 3 or parts[0] not in MONTHS:
        return None
    try:
        return datetime(int(parts[2]), MONTHS[parts[0]], int(parts[1]))
    except ValueError:
        return None


def extract_label(ct: str) -> str:
    m = re.search(r"\(([^)]+)\)", ct)
    return (m.group(1) if m else ct).strip()


def normalize_addr(addr: str) -> str:
    return re.sub(r",\s*BURBANK\s*$", "", addr.strip(), flags=re.I)


def street_key(addr: str) -> str:
    a = normalize_addr(addr)
    if " / " in a:
        return a
    return re.sub(r"^\d+\s+(BLOCK\s+)?", "", a, flags=re.I)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    total = 0
    by_month: Counter[str] = Counter()
    by_year: Counter[int] = Counter()
    by_dow: Counter[str] = Counter()
    by_hour = [0] * 24
    by_type: Counter[str] = Counter()
    by_cleared: Counter[str] = Counter()
    by_addr: Counter[str] = Counter()
    by_street: Counter[str] = Counter()
    daily: Counter[str] = Counter()
    unique_days: set[str] = set()
    test_calls = 0
    unique_raw_types: set[str] = set()

    with TSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            total += 1
            dt = parse_date(row.get("Call Date", ""))
            if dt is None:
                continue
            unique_days.add(dt.strftime("%Y-%m-%d"))
            by_month[dt.strftime("%Y-%m")] += 1
            by_year[dt.year] += 1
            by_dow[dt.strftime("%A")] += 1
            daily[dt.strftime("%Y-%m-%d")] += 1
            try:
                by_hour[int(row.get("Time", "0").split(":")[0])] += 1
            except ValueError:
                pass
            raw_type = row.get("Final Call Type", "").strip()
            unique_raw_types.add(raw_type)
            label = extract_label(raw_type)
            by_type[label] += 1
            if "TEST CALL" in raw_type.upper():
                test_calls += 1
            by_cleared[row.get("Cleared By", "").strip() or "(blank)"] += 1
            addr = normalize_addr(row.get("Address", ""))
            if addr:
                by_addr[addr] += 1
                street = street_key(row.get("Address", ""))
                if street:
                    by_street[street] += 1

    month_keys = sorted(by_month)
    jan_aug_2025 = sum(by_month[k] for k in month_keys if k.startswith("2025-") and k[5:7] <= "08")
    jan_aug_2026 = sum(by_month[k] for k in month_keys if k.startswith("2026-") and k[5:7] <= "08")

    type_notes = {
        "200 N THIRD ST": "Police station — transports, advisals, tests",
        "1300 N VICTORY PL": "Heavy petty-theft and traffic-stop volume",
        "2600 N HOLLYWOOD WAY": "Hollywood Burbank Airport",
        "2500 N HOLLYWOOD WAY": "Airport-adjacent",
    }

    crime_groups = [
        ("Petty theft (occurred, report, in progress)", ["PETTY THEFT JUST OCCURRED", "PETTY THEFT REPORT", "PETTY THEFT IN PROGRESS"]),
        ("Battery (occurred, report, in progress)", ["BATTERY JUST OCCURED", "BATTERY REPORT", "BATTERY IN PROGRESS"]),
        ("Stolen vehicle report", ["STOLEN VEH - RPT"]),
        ("Identity theft report", ["IDENTITY THEFT REPORT"]),
        ("Vandalism (report, occurred, in progress)", ["VANDALISM REPORT", "VANDALISM JUST OCCURRED", "VANDALISM IN PROGRESS"]),
        ("Grand theft report", ["GRAND THEFT REPORT"]),
        ("Vehicle burglary report", ["VEH BURG-RPT"]),
        ("Residential burglary report / in progress", ["RESIDENTIAL BURGLARY REPORT", "RESIDENTIAL BURGLARY IN PROGRESS", "RESIDENTIAL BURGLARY HOT PROWL", "RESIDENTIAL BURGLARY JUST OCCURED"]),
        ("Business burglary report / in progress", ["BUSINESS BURGLARY REPORT", "BUSINESS BURGLARY IN PROGRESS"]),
        ("Robbery (occurred + report)", ["ROBBERY JUST OCCURED", "ROBBERY REPORT"]),
        ("ADW in progress / report", ["ASSAULT WITH A DEADLY WEAPON IN PROGRESS", "ASSAULT WITH A DEADLY WEAPON REPORT"]),
        ("Shots fired just occurred", ["SHOTS FIRED JUST OCCURRED"]),
    ]

    summary = {
        "source": TSV.name,
        "total": total,
        "uniqueDays": len(unique_days),
        "avgPerDay": round(total / len(unique_days), 1) if unique_days else 0,
        "uniqueTypes": len(unique_raw_types),
        "uniqueAddresses": len(by_addr),
        "testCalls": test_calls,
        "dateMin": min(unique_days),
        "dateMax": max(unique_days),
        "byYear": {str(k): v for k, v in sorted(by_year.items())},
        "janAug2025": jan_aug_2025,
        "janAug2026": jan_aug_2026,
        "months": {
            "labels": month_keys,
            "values": [by_month[k] for k in month_keys],
            "completeMonthAvg": round(
                sum(by_month[k] for k in month_keys if k not in ("2024-06", "2026-09"))
                / max(1, len([k for k in month_keys if k not in ("2024-06", "2026-09")]))
            ),
        },
        "weekday": {"labels": [d[:3] for d in DOW], "values": [by_dow[d] for d in DOW]},
        "hour": {
            "labels": [
                "12a", "1a", "2a", "3a", "4a", "5a", "6a", "7a", "8a", "9a", "10a", "11a",
                "12p", "1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p", "10p", "11p",
            ],
            "values": by_hour,
        },
        "topTypes": [{"label": k, "count": v} for k, v in by_type.most_common(20)],
        "crimeGroups": [
            {"label": name, "count": sum(by_type[x] for x in keys)} for name, keys in crime_groups
        ],
        "alarms": {
            "business": by_type["BUSINESS BURGLARY ALARM"],
            "residential": by_type["RESIDENTIAL BURGLARY ALARM"],
        },
        "cleared": [{"label": k, "count": v} for k, v in by_cleared.most_common()],
        "topAddresses": [
            {"label": k, "count": v, "note": type_notes.get(k, "")}
            for k, v in by_addr.most_common(15)
        ],
        "topStreets": [{"label": k, "count": v} for k, v in by_street.most_common(15)],
        "busiestDays": [
            {"date": d, "count": c, "note": note}
            for (d, c), note in zip(
                daily.most_common(5),
                [
                    "Highest single day in the file",
                    "Second-highest; 2026 summer peak",
                    "",
                    "",
                    "",
                ],
            )
        ],
        "quietestDays": [
            {"date": d, "count": c}
            for d, c in sorted(daily.items(), key=lambda x: x[1])[:5]
        ],
    }

    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("wrote", OUT / "summary.json")

    compact_src = AGENT / "map_bins_compact.json"
    poly_src = AGENT / "burbank_polygon.json"
    if compact_src.exists():
        compact = json.loads(compact_src.read_text(encoding="utf-8"))
        if poly_src.exists() and (not compact.get("p") or len(compact.get("p", [])) < 10):
            compact["p"] = json.loads(poly_src.read_text(encoding="utf-8"))
        compact.setdefault(
            "l",
            [
                {"name": "PD", "lon": -118.3085, "lat": 34.1829},
                {"name": "Airport", "lon": -118.3488, "lat": 34.1959},
                {"name": "Victory Pl", "lon": -118.3236, "lat": 34.188},
                {"name": "Magnolia", "lon": -118.347, "lat": 34.167},
                {"name": "N Glenoaks", "lon": -118.305, "lat": 34.208},
            ],
        )
        (OUT / "map.json").write_text(json.dumps(compact, separators=(",", ":")), encoding="utf-8")
        print("wrote", OUT / "map.json", "bins", len(compact.get("c", [])))
    else:
        print("map source missing; skip map.json")


if __name__ == "__main__":
    main()
