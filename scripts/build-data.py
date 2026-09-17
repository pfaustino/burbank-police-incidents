"""Build static JSON reports from the CFS TSV."""

from __future__ import annotations

import csv
import json
import math
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
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HOUR_LABELS = [
    "12a", "1a", "2a", "3a", "4a", "5a", "6a", "7a", "8a", "9a", "10a", "11a",
    "12p", "1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p", "10p", "11p",
]
LAT_MIN, LAT_MAX = 34.140, 34.228
LON_MIN, LON_MAX = -118.380, -118.268
STEP = 0.0032
INCIDENTAL = {"TRAFFIC STOP", "PARKING PROBLEM"}

TYPE_NOTES = {
    "200 N THIRD ST": "Police station — transports, advisals, tests",
    "1300 N VICTORY PL": "Heavy petty-theft and traffic-stop volume",
    "2600 N HOLLYWOOD WAY": "Hollywood Burbank Airport",
    "2500 N HOLLYWOOD WAY": "Airport-adjacent",
}
CRIME_GROUPS = [
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


def is_incidental(label: str) -> bool:
    return label.upper() in INCIDENTAL


def map_cat(label: str, raw: str) -> str:
    u = f"{label} {raw}".upper()
    if is_incidental(label):
        return "i"
    if "ALARM" in u:
        return "a"
    traffic = (
        "TRAFFIC COLLISION", "HIT AND RUN", "1010 STOP", "STALLED",
        "TRAFFIC HAZARD", "IMPOUND", "REPO",
    )
    if any(k in u for k in traffic) or raw.strip().startswith("T ") or "TCPD" in raw:
        return "t"
    if any(k in u for k in ("THEFT", "BURGLAR", "STOLEN", "VANDAL", "VEH BURG", "FRAUD", "IDENTITY")):
        return "r"
    if any(k in u for k in ("BATTERY", "ASSAULT", "ROBBERY", "WEAPON", "SHOTS", "BRANDISH")):
        return "v"
    if any(k in u for k in ("DISTURBANCE", "TRANSIENT", "TRESPASS", "DRUNK")):
        return "d"
    if any(k in u for k in ("WELL BEING", "MISSING", "MAN DOWN", "5150")):
        return "w"
    if "SUSPICIOUS" in u:
        return "s"
    if any(k in u for k in ("AREA CHECK", "SUBJECT STOP", "SCHOOL CHECK", "TERMINAL SWEEP")):
        return "p"
    return "o"


class Acc:
    def __init__(self) -> None:
        self.total = 0
        self.by_month: Counter[str] = Counter()
        self.by_year: Counter[int] = Counter()
        self.by_dow: Counter[str] = Counter()
        self.by_hour = [0] * 24
        self.by_type: Counter[str] = Counter()
        self.by_cleared: Counter[str] = Counter()
        self.by_addr: Counter[str] = Counter()
        self.by_street: Counter[str] = Counter()
        self.daily: Counter[str] = Counter()
        self.days: set[str] = set()
        self.test_calls = 0
        self.raw_types: set[str] = set()

    def add(self, dt: datetime, hour: int, raw_type: str, label: str, cleared: str, addr: str, street: str) -> None:
        self.total += 1
        day = dt.strftime("%Y-%m-%d")
        self.days.add(day)
        self.by_month[dt.strftime("%Y-%m")] += 1
        self.by_year[dt.year] += 1
        self.by_dow[dt.strftime("%A")] += 1
        self.daily[day] += 1
        self.by_hour[hour] += 1
        self.raw_types.add(raw_type)
        self.by_type[label] += 1
        if "TEST CALL" in raw_type.upper():
            self.test_calls += 1
        self.by_cleared[cleared] += 1
        if addr:
            self.by_addr[addr] += 1
        if street:
            self.by_street[street] += 1

    def to_view(self) -> dict:
        month_keys = sorted(self.by_month)
        complete = [k for k in month_keys if k not in ("2024-06", "2026-09")]
        return {
            "total": self.total,
            "uniqueDays": len(self.days),
            "avgPerDay": round(self.total / len(self.days), 1) if self.days else 0,
            "uniqueTypes": len(self.raw_types),
            "uniqueAddresses": len(self.by_addr),
            "testCalls": self.test_calls,
            "byYear": {str(k): v for k, v in sorted(self.by_year.items())},
            "janAug2025": sum(self.by_month[k] for k in month_keys if k.startswith("2025-") and k[5:7] <= "08"),
            "janAug2026": sum(self.by_month[k] for k in month_keys if k.startswith("2026-") and k[5:7] <= "08"),
            "months": {
                "labels": month_keys,
                "values": [self.by_month[k] for k in month_keys],
                "completeMonthAvg": round(sum(self.by_month[k] for k in complete) / max(1, len(complete))),
            },
            "weekday": {"labels": [d[:3] for d in DOW], "values": [self.by_dow[d] for d in DOW]},
            "hour": {"labels": HOUR_LABELS, "values": self.by_hour},
            "topTypes": [{"label": k, "count": v} for k, v in self.by_type.most_common(20)],
            "crimeGroups": [
                {"label": name, "count": sum(self.by_type[x] for x in keys)} for name, keys in CRIME_GROUPS
            ],
            "alarms": {
                "business": self.by_type["BUSINESS BURGLARY ALARM"],
                "residential": self.by_type["RESIDENTIAL BURGLARY ALARM"],
            },
            "cleared": [{"label": k, "count": v} for k, v in self.by_cleared.most_common()],
            "topAddresses": [
                {"label": k, "count": v, "note": TYPE_NOTES.get(k, "")}
                for k, v in self.by_addr.most_common(15)
            ],
            "topStreets": [{"label": k, "count": v} for k, v in self.by_street.most_common(15)],
            "busiestDays": [{"date": d, "count": c} for d, c in self.daily.most_common(5)],
            "quietestDays": [{"date": d, "count": c} for d, c in sorted(self.daily.items(), key=lambda x: x[1])[:5]],
        }


def categorize_map(label: str, raw: str) -> str:
    return map_cat(label, raw)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_view = Acc()
    core = Acc()
    traffic_stops = 0
    parking = 0
    geocoded = {}
    cache_path = AGENT / "geocode_cache.json"
    if cache_path.exists():
        geocoded = json.loads(cache_path.read_text(encoding="utf-8"))
    cells: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    mapped = unmapped = out_of_view = 0

    with TSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            dt = parse_date(row.get("Call Date", ""))
            if dt is None:
                continue
            try:
                hour = int(row.get("Time", "0").split(":")[0])
            except ValueError:
                hour = 12
            raw_type = row.get("Final Call Type", "").strip()
            label = extract_label(raw_type)
            cleared = row.get("Cleared By", "").strip() or "(blank)"
            addr = normalize_addr(row.get("Address", ""))
            street = street_key(row.get("Address", ""))
            all_view.add(dt, hour, raw_type, label, cleared, addr, street)
            if is_incidental(label):
                if label.upper() == "TRAFFIC STOP":
                    traffic_stops += 1
                else:
                    parking += 1
            else:
                core.add(dt, hour, raw_type, label, cleared, addr, street)

            pt = geocoded.get(row.get("Address", "").strip())
            if not pt:
                unmapped += 1
                continue
            lon, lat = pt
            if not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX):
                out_of_view += 1
                continue
            tod = "D" if 6 <= hour < 18 else "N"
            cat = categorize_map(label, raw_type)
            gx = int(math.floor((lon - LON_MIN) / STEP))
            gy = int(math.floor((lat - LAT_MIN) / STEP))
            cell = cells[(gx, gy)]
            cell["n"] += 1
            key = f"{str(dt.year)[2:]}{cat}{tod}"
            cell[key] += 1
            mapped += 1

    days = sorted(all_view.days)
    summary = {
        "source": TSV.name,
        "dateMin": days[0],
        "dateMax": days[-1],
        "incidental": {
            "trafficStops": traffic_stops,
            "parking": parking,
            "total": traffic_stops + parking,
        },
        "all": all_view.to_view(),
        "core": core.to_view(),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("wrote", OUT / "summary.json", "all", all_view.total, "core", core.total)

    bins = []
    for (gx, gy), counts in cells.items():
        bins.append({
            "x": round(LON_MIN + (gx + 0.5) * STEP, 5),
            "y": round(LAT_MIN + (gy + 0.5) * STEP, 5),
            "n": counts["n"],
            **{k: v for k, v in counts.items() if k != "n"},
        })
    bins.sort(key=lambda b: -b["n"])

    polygon = []
    existing = OUT / "map.json"
    poly_src = AGENT / "burbank_polygon.json"
    if existing.exists():
        polygon = json.loads(existing.read_text(encoding="utf-8")).get("p") or []
    if (not polygon) and poly_src.exists():
        raw_poly = json.loads(poly_src.read_text(encoding="utf-8"))
        polygon = [[round(x, 5), round(y, 5)] for x, y in raw_poly]

    payload = {
        "b": [LON_MIN, LAT_MIN, LON_MAX, LAT_MAX],
        "m": mapped,
        "u": unmapped,
        "p": polygon,
        "c": bins,
        "l": [
            {"name": "Police station", "lon": -118.3085, "lat": 34.1829},
            {"name": "Airport", "lon": -118.3488, "lat": 34.1959},
            {"name": "Downtown", "lon": -118.309, "lat": 34.18},
        ],
    }
    (OUT / "map.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print("wrote", OUT / "map.json", "bins", len(bins), "mapped", mapped)


if __name__ == "__main__":
    main()
