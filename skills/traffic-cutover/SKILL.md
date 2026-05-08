---
name: traffic-cutover
description: Shift production traffic from EKS to GKE per workload with weighted DNS, gateway-level traffic split, or service-mesh routing — including pre-cutover validation, gradual ramp (1% → 10% → 50% → 100%), SLO-tied auto-rollback gates, and post-cutover soak. Produces a per-workload cutover runbook with explicit go/no-go gates. Use when "plan the traffic cutover", "shift traffic gradually to GKE", or "execute the move for service X".
---

# Traffic Cutover

You execute the actual production traffic shift, one workload at a time, with SLO-tied gates that pause or roll back the cutover automatically.

## Purpose

Move user traffic from EKS to GKE for each workload safely. Default to gradual weighted shifts. Watch SLOs. Pause on regression. Roll back on threshold breach.

## When to use this skill

- Phase 4 of a Portage migration, after `data-migration` for any stateful workload.
- The user asks to "cut over traffic", "shift X% to GKE", "execute the migration for service Y".

Do NOT use to plan; cutover plans are part of `migration-assessment` + per-workload runbooks. This skill *executes*.

## Prerequisites

- The workload exists and is healthy on GKE: `kubectl rollout status` is `Available`, smoke tests pass.
- `04-network-translation/manifests/` Gateway has been applied; the Gateway has an external address.
- Cloud Armor, Cloud Logging, Cloud Monitoring all wired up per `09-observability-translation/`.
- Per-workload SLO is defined (or, if not, a basic availability + latency SLO is established for the cutover window).
- DNS or routing layer is under your control (Cloud DNS routing policy, traffic-mirroring proxy, or service-mesh routing).

## Procedure

### Step 1 — Pre-flight: confirm GKE side is healthy

```bash
# Workload health
kubectl -n <ns> rollout status deploy/<name> --timeout=120s

# Gateway/HTTPRoute is programmed
kubectl -n <ns> describe httproute <name> | grep -E 'Status:|Programmed'
kubectl -n <ns> describe gateway <gateway-name>

# A direct curl through the GKE Gateway succeeds for a representative request
curl -sS https://<gke-gateway-host>/healthz | jq .
```

If any of these fail, stop. Do not initiate traffic shift.

### Step 2 — Define gates before shifting

Define explicit numeric gates the cutover will not cross:

| Gate                                | Threshold                       | Window  | Action on breach |
|-------------------------------------|---------------------------------|---------|-------------------|
| 5xx rate (GKE side)                 | ≤ 0.5% over baseline             | 5 min   | Pause; alert      |
| p95 latency (GKE side)              | ≤ 1.5× baseline                  | 5 min   | Pause; alert      |
| p99 latency (GKE side)              | ≤ 2.0× baseline                  | 10 min  | Pause; alert      |
| Backend health                      | < 95% targets healthy            | 1 min   | Auto-rollback     |
| Cross-cloud egress error rate       | ≤ 1%                             | 5 min   | Pause; alert      |
| Custom (per workload)               | as defined in readiness report   | …       | …                 |

These map to alerting policies. The cutover script consults the alerting state before each ramp.

### Step 3 — Pick a routing mechanism

| Mechanism                                  | Use when                                             |
|--------------------------------------------|------------------------------------------------------|
| Cloud DNS weighted routing policy          | DNS is under your control; clients respect TTL; non-stateful HTTP |
| Hand-rolled at the edge (CDN / WAF / global LB ahead) | When you have a global edge layer that can split                |
| Service mesh routing (Anthos Service Mesh) | When both EKS and GKE are mesh-joined                |
| L7 proxy (Envoy / NGINX / HAProxy fronting both) | When DNS TTLs are too long to use DNS shifting        |
| Per-client config flag                     | For internal services with client-side service discovery |

Whichever you choose, it must support **weighted backends** with safe ramp increments.

### Step 4 — Ramp pattern

Default ramp:

```
1%  → soak 15 min → check gates → 10%  →
10% → soak 30 min → check gates → 50%  →
50% → soak 60 min → check gates → 100% →
100% → soak 24 hours → declare cutover stable
```

For lower-risk workloads, use a faster ramp (10% → 50% → 100% with shorter soaks). For tier-0, use a slower ramp (1% → 5% → 25% → 50% → 75% → 100% with longer soaks).

The agent runs the ramp by:

1. Updating routing weights via the chosen mechanism.
2. Polling the alerting/metric API every 60s.
3. If a gate breaches: pause, surface alert, ask the user. Do not auto-revert at this stage unless you are at "auto-rollback" gates (backend health < 95%).
4. If 100% is reached and gates pass for 24 hours, declare stable.

### Step 5 — Cutover script (Cloud DNS example)

```bash
#!/usr/bin/env bash
set -euo pipefail

ZONE=example-com
DOMAIN=api.example.com
EKS_TARGET=k8s-prod-web-...elb.amazonaws.com
GKE_TARGET=34.117.x.x
RUN_DIR=portage-output/.../11-cutover/api-example-com

declare -A WEIGHTS=( [step1]="99 1" [step2]="90 10" [step3]="50 50" [step4]="0 100" )
SOAKS=( [step1]=900 [step2]=1800 [step3]=3600 [step4]=86400 )

for STEP in step1 step2 step3 step4; do
  EKS_W=${WEIGHTS[$STEP]%% *}
  GKE_W=${WEIGHTS[$STEP]##* }

  echo "[${STEP}] EKS=${EKS_W}% GKE=${GKE_W}%"
  gcloud dns record-sets transaction start --zone="$ZONE"
  gcloud dns record-sets transaction remove "$DOMAIN" --zone="$ZONE" --type=A --ttl=60 || true
  gcloud dns record-sets transaction add \
    --zone="$ZONE" --name="$DOMAIN." --ttl=60 --type=A \
    --routing-policy-type=WRR \
    --routing-policy-data="${EKS_W}=${EKS_TARGET}@${EKS_AS_IP};${GKE_W}=${GKE_TARGET}"
  gcloud dns record-sets transaction execute --zone="$ZONE"

  date "+%FT%TZ" >> "$RUN_DIR/execution.log"
  echo "step=${STEP} eks=${EKS_W} gke=${GKE_W}" >> "$RUN_DIR/execution.log"

  bash "$RUN_DIR/check-gates.sh" || { echo "Gates failed at ${STEP}"; exit 1; }
  echo "[${STEP}] gates green; soaking ${SOAKS[$STEP]}s"
  sleep "${SOAKS[$STEP]}"
done

echo "Cutover complete; soak passed at 100% for 24h."
```

`check-gates.sh` queries Cloud Monitoring for the configured alerting policies' incident state. Non-zero exit if any policy is firing or any threshold is breached.

### Step 6 — Identity / data state at each step

At each step, the agent verifies:

- The fraction of requests landing on GKE matches the intended weight (sample server logs).
- Workload Identity is correctly resolved for the GKE replicas (no spike in 401/403 from upstream services that authenticate via WI).
- Data writes from the GKE side land in the target data system (not the source). For workloads where the source is still authoritative during co-existence, the GKE side should be in read-only or proxied mode — surface to the user before starting.

### Step 7 — Final cutover and source freeze

When 100% is reached and 24-hour soak is green:

1. Update DNS: remove the EKS target entirely (TTL respected; old clients will drain).
2. Mark the EKS Deployment as scaled to 0 replicas (do not delete; rollback path).
3. Set source data system (RDS/Memorystore/etc.) to read-only if applicable, or keep as warm fallback per data-migration plan.
4. Record the cutover timestamp. Begin the 14-day cool-down clock.

### Step 8 — Output

```
11-cutover/
├── per-workload-runbooks/
│   └── <workload>.md
├── execution-logs/
│   └── <workload>.log
├── gates/
│   └── <workload>-gates.yaml      # The configured thresholds
├── ramp-evidence/                  # Screenshots of dashboards mid-ramp (optional)
└── escalations.md
```

## Decision points

| Decision                                  | Default                                | When to deviate                          |
|-------------------------------------------|----------------------------------------|------------------------------------------|
| Routing mechanism                         | Cloud DNS WRR                          | Service mesh if both clusters are joined |
| Ramp speed                                | 1% / 10% / 50% / 100% with soaks       | Faster for non-tier-0; slower for tier-0 |
| Auto-rollback at backend-health gate      | On                                     | Off only with explicit user opt-out      |
| Window timing                             | Off-peak                               | Anytime if traffic is low                |
| Big-bang (no ramp)                        | Off                                    | Only with explicit confirmation, written postmortem-readiness, and a tested rollback |

## Outputs / Deliverables

```
11-cutover/
├── per-workload-runbooks/
├── execution-logs/
├── gates/
├── ramp-evidence/
└── escalations.md
```

## Validation

For each cut-over workload:

- Ramp completed with no breached gates (or all breaches were resolved without rollback).
- 24-hour soak at 100% green.
- DNS TTL respected; legacy resolvers fully drained.
- EKS replica count = 0; workload status `Stopped`.
- Data writes flowing only to target.

## Escalation triggers

- A gate trips at >50% traffic. Even if it self-resolves, surface for human review before continuing.
- Two consecutive gate trips at any weight. Halt and review.
- Cross-cloud latency rises during co-existence to a level that violates downstream SLOs.
- Workload depends on an EKS-side service that has not yet cut over and exhibits flapping reachability. Pause the dependent workload's cutover.

## Common pitfalls

- **DNS TTL discipline.** Set TTLs to 60s before starting weighted shifts. Long TTLs make ramps statistically wobbly.
- **Sticky sessions.** If load balancing has session affinity, ramping by weight does not give linear shift. Plan accordingly (or drop affinity for the cutover window if safe).
- **Crossing cluster identity.** A weighted ramp at the LB layer can route an authenticated session to the wrong cluster mid-flight if state is local. Stateful sessions need a different mechanism (cookie-based stickiness + per-cookie cluster pin).
- **Treating the soak as optional.** It's not. The soak is what catches the slow leaks (memory, file descriptors, connection pools).
- **Forgetting to remove the old EKS DNS record.** Old clients will follow stale TTLs forever. Final step: explicit removal.
- **JVM workloads cache DNS forever by default.** Setting the LB DNS TTL to 60s does nothing if the JVM caches the first answer for the process lifetime. Mandate `networkaddress.cache.ttl=5` (or similar) per-workload before any DNS-weighted ramp. See [LFF-03](../../reference/lessons-from-the-field.md#lff-03--default-jvm-caches-dns-forever-aws-sdk-for-java-recommends-a-5-second-ttl).
- **Long-lived WebSocket / IoT clients ignore DNS TTLs entirely.** Plan a forwarding tail on the source side for 30+ days post-cutover for any workload with persistent client connections from heterogeneous fleets. See [LFF-04](../../reference/lessons-from-the-field.md#lff-04--long-lived-websocket-clients-on-heterogeneous-devices-ignore-dns-ttls).
- **gRPC pins to original pods**; `MaxConnectionAge` must be set on the server side to force periodic re-resolution. Treat gRPC and websocket workloads as a separate cutover cohort. See [LFF-05](../../reference/lessons-from-the-field.md#lff-05--grpc-and-round-robin-client-policy-can-syn-flood-targets-during-a-rollover).

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [Cloud DNS routing policies](https://cloud.google.com/dns/docs/zones/manage-routing-policies) — the WRR mechanism the cutover script uses.
- [GKE Gateway traffic splitting](https://cloud.google.com/kubernetes-engine/docs/how-to/gateway-traffic-splitting) — alternative routing mechanism.
- [Anthos Service Mesh multi-cluster](https://cloud.google.com/service-mesh/docs/managed/multi-cluster) — mesh-routing path.
- [SRE Workbook — Canarying Releases](https://sre.google/workbook/canarying-releases/).
- [SRE Workbook — Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/) — burn-rate alerting model behind the gates.
- [data-migration](../data-migration/SKILL.md) — must complete before stateful cutover.
- [rollback-playbook](../rollback-playbook/SKILL.md) — invoked when gates breach.
- [observability-translation](../observability-translation/SKILL.md) — sources the gates' metric data.
