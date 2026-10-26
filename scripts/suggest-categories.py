#!/usr/bin/env python3
# Run on any LAN machine against a transaction CSV (Actual: All accounts > menu > Export,
# or a bank export) to get a category set before creating any in Actual.
#   ./scripts/suggest-categories.py transactions.csv --ollama http://LAN_IP:11434
# Pass 1 proposes groups/categories from the top payees; pass 2 files every payee into
# that fixed set, so the totals show whether the set is right. Nothing is written to Actual.
import argparse
import csv
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime

# Same model as paperless-gpt, so Ollama keeps its single runner loaded.
MODEL = "qwen3-vl:8b-instruct"
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%Y/%m/%d")

TAXONOMY_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "categories": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "covers": {"type": "string"}},
                            "required": ["name", "covers"],
                        },
                    },
                },
                "required": ["name", "categories"],
            },
        }
    },
    "required": ["groups"],
}


def col(header: list[str], *names: str) -> int | None:
    lower = [h.strip().lower() for h in header]
    for n in names:
        if n in lower:
            return lower.index(n)
    return None


def money(s: str) -> float:
    s = s.strip().replace("$", "").replace(",", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return float(s) if s else 0.0


def parse_date(s: str) -> datetime | None:
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), f)
        except ValueError:
            pass
    return None


def load(path: str) -> tuple[dict, float]:
    """Spending per payee: {payee: {"total", "count", "notes"}}, plus months covered."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header, rows = rows[0], rows[1:]
    payee = col(header, "payee", "description", "name", "merchant")
    notes = col(header, "notes", "memo")
    date = col(header, "date", "posted date", "transaction date")
    amount = col(header, "amount")
    outflow = col(header, "outflow", "debit", "withdrawal")
    inflow = col(header, "inflow", "credit", "deposit")
    if payee is None or (amount is None and outflow is None):
        sys.exit(f"can't find payee/amount columns in header: {header}")

    payees: dict = defaultdict(lambda: {"total": 0.0, "count": 0, "notes": set()})
    dates = []
    for r in rows:
        if not r or len(r) < len(header):
            continue
        name = r[payee].strip()
        # Actual exports transfers between your own accounts as "Transfer : <account>".
        if not name or name.lower().startswith("transfer"):
            continue
        if amount is not None:
            spent = -money(r[amount])
        else:
            spent = money(r[outflow]) - (money(r[inflow]) if inflow is not None else 0.0)
        if spent <= 0:
            continue
        p = payees[name]
        p["total"] += spent
        p["count"] += 1
        if notes is not None and r[notes].strip() and len(p["notes"]) < 2:
            p["notes"].add(r[notes].strip()[:60])
        if date is not None and (d := parse_date(r[date])):
            dates.append(d)
    months = max(1.0, (max(dates) - min(dates)).days / 30.44) if dates else 1.0
    return payees, months


def ask(url: str, prompt: str, schema: dict) -> dict:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "format": schema,
        "stream": False,
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        f"{url.rstrip('/')}/api/chat", json.dumps(body).encode(), {"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(json.load(resp)["message"]["content"])


def line(name: str, p: dict) -> str:
    extra = f" (notes: {'; '.join(p['notes'])})" if p["notes"] else ""
    return f"- {name}: {p['count']} txns, ${p['total']:.0f}{extra}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv")
    ap.add_argument("--ollama", default="http://localhost:11434")
    ap.add_argument("--top", type=int, default=150, help="payees shown to the model in pass 1")
    ap.add_argument("--batch", type=int, default=40, help="payees per request in pass 2")
    ap.add_argument("--out", default="categories.json")
    args = ap.parse_args()

    payees, months = load(args.csv)
    ranked = sorted(payees.items(), key=lambda kv: kv[1]["total"], reverse=True)
    print(f"{len(payees)} payees over {months:.1f} months", file=sys.stderr)

    print("pass 1: proposing categories", file=sys.stderr)
    taxonomy = ask(
        args.ollama,
        "You are setting up a household budget. The goal is to see monthly totals for bills, "
        "groceries, dining out and similar everyday questions.\n"
        "Propose 5-7 category groups with 15-20 categories in total. Each category must be "
        "mutually exclusive with the others and named plainly (e.g. 'Groceries', 'Dining Out', "
        "'Utilities'). Do not create a category for a single merchant. Include one 'Misc' category. "
        "In 'covers', say in a few words what belongs there.\n\n"
        "Payees by total spending:\n" + "\n".join(line(n, p) for n, p in ranked[: args.top]),
        TAXONOMY_SCHEMA,
    )
    names = [f"{g['name']} / {c['name']}" for g in taxonomy["groups"] for c in g["categories"]]
    guide = "\n".join(
        f"- {g['name']} / {c['name']}: {c['covers']}" for g in taxonomy["groups"] for c in g["categories"]
    )

    print("pass 2: filing payees", file=sys.stderr)
    assignments: dict[str, str] = {}
    for i in range(0, len(ranked), args.batch):
        chunk = ranked[i : i + args.batch]
        print(f"  {i + len(chunk)}/{len(ranked)}", file=sys.stderr)
        # Enum-constrained output: the model can only answer with an existing category.
        schema = {
            "type": "object",
            "properties": {n: {"type": "string", "enum": names} for n, _ in chunk},
            "required": [n for n, _ in chunk],
        }
        assignments |= ask(
            args.ollama,
            "Assign each payee to exactly one of these categories:\n" + guide + "\n\nPayees:\n"
            + "\n".join(line(n, p) for n, p in chunk),
            schema,
        )

    totals: dict = defaultdict(lambda: {"total": 0.0, "payees": []})
    for name, p in ranked:
        cat = assignments.get(name, "Unassigned")
        totals[cat]["total"] += p["total"]
        totals[cat]["payees"].append(name)

    for g in taxonomy["groups"]:
        cats = [f"{g['name']} / {c['name']}" for c in g["categories"]]
        group_total = sum(totals[c]["total"] for c in cats)
        print(f"\n{g['name']}  ${group_total / months:,.0f}/mo")
        for c, cdef in zip(cats, g["categories"]):
            t = totals[c]
            top = ", ".join(t["payees"][:5]) + (" ..." if len(t["payees"]) > 5 else "")
            print(f"  {cdef['name']:<22} ${t['total'] / months:>8,.0f}/mo  {cdef['covers']}")
            if top:
                print(f"  {'':<22} {top}")
    if totals["Unassigned"]["payees"]:
        print(f"\nUnassigned: {', '.join(totals['Unassigned']['payees'])}")

    with open(args.out, "w") as f:
        json.dump({"taxonomy": taxonomy, "assignments": assignments}, f, indent=2)
    print(f"\nfull payee -> category map written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
