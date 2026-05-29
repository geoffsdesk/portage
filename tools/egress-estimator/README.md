# Cross-cloud egress estimator

A tiny, dependency-free model of the cross-cloud data-transfer bill an EKS → GKE
migration incurs during its co-existence window — and whether a
[Cross-Cloud Interconnect](https://cloud.google.com/network-connectivity/docs/interconnect)
(CCI) circuit is cheaper than open-internet egress.

It operationalizes lesson **LFF-01** in
[`reference/lessons-from-the-field.md`](../../reference/lessons-from-the-field.md):
cross-cloud egress during co-existence routinely runs 5–10× the unbudgeted estimate and
is the most common source of a surprise five-figure migration invoice. Run it during the
`migration-assessment` phase and paste the output into Section 7 of the readiness report.

## Why it exists

Open-internet egress is billed **per GB** (~$0.08–0.12/GB). A dedicated interconnect
charges a flat circuit fee with **no per-GB transfer cost**. Above a break-even volume the
circuit is cheaper — and that break-even is far lower than teams assume, which is exactly
why the bill surprises them. This tool makes the trade-off explicit and auditable.

## Usage

```bash
# Built-in demo, no input needed:
python3 egress_estimator.py --demo

# Your estate (see sample-workloads.csv for the schema):
python3 egress_estimator.py --input sample-workloads.csv --window-days 21

# Override pricing and emit JSON for downstream tooling:
python3 egress_estimator.py --input wl.csv --internet-rate 0.09 --cci-monthly 9000 --format json
```

Requires only Python 3.8+ standard library. No network calls.

### Input CSV schema

| Column | Required | Meaning |
|---|---|---|
| `workload` | yes | Workload name |
| `gb_per_day` | yes | Steady-state cross-cloud data rate, GB/day |
| `window_days` | no | Per-workload co-existence window (falls back to `--window-days`) |
| `seed_tib` | no | One-time bulk seed transferred at cutover start, TiB |

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--window-days` | `21` | Default co-existence window |
| `--internet-rate` | `0.10` | Internet egress $/GB |
| `--cci-monthly` | `9000` | CCI circuit $/month (~10 Gbps) |
| `--cci-nrc` | `0` | CCI one-time non-recurring charge $ |
| `--format` | `md` | `md` or `json` |

## Caveats

The default unit costs are **indicative** and meant to be overridden with your own contracted
rates. The model assumes a single shared circuit covers all listed workloads in parallel; for
multi-region or multi-circuit topologies, run it once per circuit. It does not (yet) model
intra-region vs inter-region nuances or tiered egress discounts — contributions welcome.
