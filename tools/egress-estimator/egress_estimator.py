#!/usr/bin/env python3
"""
Portage cross-cloud egress estimator
====================================

Operationalizes lesson LFF-01 ("Cross-cloud egress during co-existence routinely
runs 5-10x the unbudgeted estimate") from reference/lessons-from-the-field.md.

During an EKS->GKE migration there is usually a co-existence window in which traffic
and/or data replication crosses between AWS and GCP. That cross-cloud traffic is
billed per-GB on the open internet and is the single most common source of a surprise
five-figure invoice. A dedicated Cross-Cloud Interconnect (CCI) circuit charges a flat
hourly/bandwidth fee with NO per-GB transfer cost, so above a (surprisingly low)
break-even volume it is cheaper than the internet path.

This tool models both paths per workload over the co-existence window, reports the
break-even volume, and recommends a path. It feeds Section 7 of the readiness report.

Auditable by design: pure Python standard library, no network calls, every
assumption is an explicit, overridable flag printed in the output.

Usage
-----
    # Built-in demo (no input file required):
    python3 egress_estimator.py --demo

    # From a CSV of workloads (see sample-workloads.csv):
    python3 egress_estimator.py --input sample-workloads.csv --window-days 21

    # Override pricing / output format:
    python3 egress_estimator.py --input wl.csv --internet-rate 0.09 \
        --cci-monthly 9000 --format md

CSV schema (header row required; per-workload window_days and seed_tib optional):
    workload,gb_per_day,window_days,seed_tib
    payments-api,120,21,0
    analytics-cdc,400,30,8

Pricing defaults are indicative (verify against current AWS/GCP rate cards):
  * internet egress  : $0.10 / GB   (AWS data-transfer-out to internet is ~$0.09/GB;
                        GCP internet egress ~$0.08-0.12/GB depending on destination)
  * CCI circuit       : $9,000 / month for a ~10 Gbps link (no per-GB charge)
  * CCI one-time NRC  : $0 by default (set with --cci-nrc if your contract has one)
"""

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field

GIB_PER_TIB = 1024


@dataclass
class Workload:
    name: str
    gb_per_day: float
    window_days: int
    seed_tib: float = 0.0
    total_gb: float = field(init=False)

    def __post_init__(self):
        self.total_gb = (self.gb_per_day * self.window_days) + (self.seed_tib * GIB_PER_TIB)


def load_workloads(path, default_window):
    out = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"workload", "gb_per_day"}
        if not required.issubset({c.strip() for c in (reader.fieldnames or [])}):
            sys.exit(f"error: CSV must have at least columns: {', '.join(sorted(required))}")
        for row in reader:
            if not row.get("workload"):
                continue
            out.append(Workload(
                name=row["workload"].strip(),
                gb_per_day=float(row["gb_per_day"]),
                window_days=int(row["window_days"]) if row.get("window_days") else default_window,
                seed_tib=float(row["seed_tib"]) if row.get("seed_tib") else 0.0,
            ))
    if not out:
        sys.exit("error: no workloads found in input")
    return out


def demo_workloads(default_window):
    return [
        Workload("payments-api", 120, default_window, 0),
        Workload("orders-service", 60, default_window, 0),
        Workload("analytics-cdc", 400, 30, 8),      # heavy continuous CDC + 8 TiB seed
        Workload("media-uploads", 250, default_window, 2),
    ]


def estimate(workloads, internet_rate, cci_monthly, cci_nrc):
    total_gb = sum(w.total_gb for w in workloads)
    max_window = max(w.window_days for w in workloads)
    months = max_window / 30.0

    internet_total = total_gb * internet_rate
    cci_total = cci_monthly * months + cci_nrc
    break_even_gb = (cci_monthly * months + cci_nrc) / internet_rate if internet_rate else float("inf")

    rows = []
    for w in workloads:
        rows.append({
            "workload": w.name,
            "gb_per_day": w.gb_per_day,
            "window_days": w.window_days,
            "seed_tib": w.seed_tib,
            "total_gb": round(w.total_gb, 1),
            "internet_cost_usd": round(w.total_gb * internet_rate, 2),
        })

    recommend = "Cross-Cloud Interconnect" if total_gb > break_even_gb else "Internet egress"
    savings = internet_total - cci_total
    return {
        "rows": rows,
        "summary": {
            "total_gb": round(total_gb, 1),
            "max_window_days": max_window,
            "internet_total_usd": round(internet_total, 2),
            "cci_total_usd": round(cci_total, 2),
            "break_even_gb": round(break_even_gb, 1),
            "recommendation": recommend,
            "savings_if_recommended_usd": round(abs(savings), 2),
        },
        "assumptions": {
            "internet_rate_usd_per_gb": internet_rate,
            "cci_monthly_usd": cci_monthly,
            "cci_one_time_nrc_usd": cci_nrc,
        },
    }


def fmt_money(x):
    return f"${x:,.2f}"


def render_md(result):
    s = result["summary"]
    a = result["assumptions"]
    lines = []
    lines.append("## Cross-cloud egress estimate (co-existence window)")
    lines.append("")
    lines.append(f"_Models lesson LFF-01. Recommendation over a {s['max_window_days']}-day window._")
    lines.append("")
    lines.append("| Workload | GB/day | Window (d) | Seed (TiB) | Total GB | Internet egress |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for r in result["rows"]:
        lines.append(
            f"| {r['workload']} | {r['gb_per_day']:.0f} | {r['window_days']} | "
            f"{r['seed_tib']:.0f} | {r['total_gb']:,.0f} | {fmt_money(r['internet_cost_usd'])} |"
        )
    lines.append("")
    lines.append("### Path comparison")
    lines.append("")
    lines.append("| Path | Cost over window | Notes |")
    lines.append("|---|--:|---|")
    lines.append(f"| Open-internet egress | {fmt_money(s['internet_total_usd'])} | "
                 f"billed at {fmt_money(a['internet_rate_usd_per_gb'])}/GB |")
    lines.append(f"| Cross-Cloud Interconnect | {fmt_money(s['cci_total_usd'])} | "
                 f"{fmt_money(a['cci_monthly_usd'])}/mo circuit, no per-GB charge |")
    lines.append("")
    lines.append(f"- **Break-even volume:** {s['break_even_gb']:,.0f} GB over the window. "
                 f"Above this, the interconnect is cheaper.")
    lines.append(f"- **Total cross-cloud volume modeled:** {s['total_gb']:,.0f} GB.")
    lines.append(f"- **Recommendation: {s['recommendation']}** "
                 f"(~{fmt_money(s['savings_if_recommended_usd'])} cheaper over the window).")
    lines.append("")
    lines.append("> Reminder (LFF-01): teams routinely under-model this 5-10x. Set a budget "
                 "alert at 80%/100% of the co-existence budget and monitor egress in near "
                 "real time; treat residual cross-cloud egress as a decommission blocker.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Portage cross-cloud egress estimator (LFF-01).")
    ap.add_argument("--input", help="CSV of workloads (workload,gb_per_day[,window_days,seed_tib])")
    ap.add_argument("--demo", action="store_true", help="Run with built-in sample workloads")
    ap.add_argument("--window-days", type=int, default=21, help="Default co-existence window (days)")
    ap.add_argument("--internet-rate", type=float, default=0.10, help="Internet egress $/GB")
    ap.add_argument("--cci-monthly", type=float, default=9000.0, help="CCI circuit $/month (~10 Gbps)")
    ap.add_argument("--cci-nrc", type=float, default=0.0, help="CCI one-time non-recurring charge $")
    ap.add_argument("--format", choices=["md", "json"], default="md", help="Output format")
    args = ap.parse_args()

    if args.demo or not args.input:
        if not args.demo and not args.input:
            print("# (no --input given; showing --demo. Run with --input <csv> for your estate.)\n",
                  file=sys.stderr)
        workloads = demo_workloads(args.window_days)
    else:
        workloads = load_workloads(args.input, args.window_days)

    result = estimate(workloads, args.internet_rate, args.cci_monthly, args.cci_nrc)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(render_md(result))


if __name__ == "__main__":
    main()
