---
name: observability-translation
description: Translate EKS observability stacks to GKE — CloudWatch Logs and Metrics to Cloud Logging and Cloud Monitoring, Managed Prometheus (AMP) to Google Managed Service for Prometheus (GMP), CloudWatch Container Insights to GKE-native dashboards, X-Ray to Cloud Trace, and CloudWatch alarms to alerting policies. Produces translated alerting rules, dashboard JSON, log routing, and SLO definitions. Use when "translate observability", "set up monitoring on GKE", or as part of Phase 3 of a Portage migration.
---

# Observability Translation

You translate the observability surface — logs, metrics, traces, dashboards, alerts, SLOs — from EKS/CloudWatch/AMP into GKE/Cloud Operations/GMP. You produce translated configurations and a parity report.

## Purpose

Every signal an operator needs to see on EKS must be visible on GKE before traffic shifts. Without parity, no one will trust the cutover.

## When to use this skill

- Phase 3 of a Portage migration.
- The user asks to "translate dashboards", "convert alarms", "set up SLOs on GKE".

## Prerequisites

- `01-discovery/inventory.json` observability section.
- `03-landing-zone/plan.md` with the `obs-<env>` project provisioned.
- Access to the source CloudWatch dashboards (export JSON), AMP workspace, Grafana workspaces, X-Ray groups.

## Procedure

### Step 1 — Set up the metrics scope

In the `obs-<env>` project, create a metrics scope that includes the cluster project(s):

```bash
gcloud projects update obs-prod \
  --update-labels="role=observability-scope"

# Add the cluster project as a monitored project of obs-prod
gcloud monitoring metrics-scopes create \
  projects/gke-prod-clusters \
  --project=obs-prod
```

Cloud Monitoring queries against `obs-prod` now see metrics from `gke-prod-clusters`. Same pattern for `nonprod`.

### Step 2 — Confirm GKE-native ingest is on

Cloud Logging and Cloud Monitoring are enabled as part of the cluster spec in `gke-landing-zone`. Verify:

```bash
gcloud container clusters describe prod-primary --location us-central1 \
  --format='value(loggingConfig.componentConfig.enableComponents)'
# Expect: SYSTEM_COMPONENTS;WORKLOADS;API_SERVER;SCHEDULER;CONTROLLER_MANAGER

gcloud container clusters describe prod-primary --location us-central1 \
  --format='value(monitoringConfig.componentConfig.enableComponents,monitoringConfig.managedPrometheusConfig.enabled)'
```

GKE Container Insights equivalents (workload metrics, pod CrashLoopBackOff, image pull failures) are produced natively when these components are enabled.

### Step 3 — Translate AMP / Prometheus

Managed Service for Prometheus (GMP) is enabled by the cluster's `managedPrometheusConfig.enabled = true`. Translate Prometheus configurations:

- **Scrape configs**: rewrite as `PodMonitoring` and `ClusterPodMonitoring` CRs.

```yaml
apiVersion: monitoring.googleapis.com/v1
kind: PodMonitoring
metadata:
  name: payments-api
  namespace: payments
spec:
  selector:
    matchLabels:
      app: payments-api
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```

- **Recording rules / alerting rules**: keep PromQL unchanged. Convert files to `Rules` CRs:

```yaml
apiVersion: monitoring.googleapis.com/v1
kind: Rules
metadata:
  name: payments-recording
  namespace: payments
spec:
  groups:
    - name: payments
      interval: 30s
      rules:
        - record: payments:request_rate:rate5m
          expr: sum(rate(http_requests_total{job="payments-api"}[5m])) by (status)
```

- **Long-term retention**: GMP stores 24 months by default. If AMP had different retention, surface that.
- **Federation**: any external Prometheus federating from AMP needs to be re-pointed at the GMP query endpoint. Adjust scrape configs and authentication (use Workload Identity for in-cluster, OAuth + service account for external).

### Step 4 — Translate Grafana

Two paths:

1. **Self-host Grafana on GKE**: deploy from upstream chart, configure two data sources (`Prometheus → GMP query endpoint` and `Cloud Monitoring`). Import existing dashboards JSON; rewrite metric names where they differ (CloudWatch metric translation table below).
2. **Use Cloud Monitoring dashboards natively**: convert each Grafana dashboard panel to a Cloud Monitoring widget. PromQL panels work; metric names like `aws.ec2.cpuutilization` need translation.

CloudWatch → Cloud Monitoring metric translation (most common):

| CloudWatch metric                                      | Cloud Monitoring metric                                |
|--------------------------------------------------------|--------------------------------------------------------|
| `AWS/EKS:cluster_failed_request_count`                 | `kubernetes.io/container/restart_count` (closest), plus apiserver metrics in `kubernetes.io/api/...` |
| `AWS/EKS:apiserver_request_total`                      | Direct via GMP if you scrape, else apiserver Cloud Monitoring metrics |
| `AWS/EBS:VolumeReadOps`                                | `compute.googleapis.com/instance/disk/read_ops_count`   |
| `AWS/RDS:CPUUtilization`                               | `cloudsql.googleapis.com/database/cpu/utilization`      |
| `AWS/ELBv2:RequestCount`                               | `loadbalancing.googleapis.com/https/request_count`      |
| `AWS/ApplicationELB:HTTPCode_ELB_5XX_Count`            | `loadbalancing.googleapis.com/https/backend_request_count` filter `response_code_class=500` |

Build a `metric-map.md` table for the workloads in scope.

### Step 5 — Translate logs

CloudWatch Log Groups → Cloud Logging buckets / log routes.

For each log group:

1. Identify the source (cluster control plane, container logs, application).
2. Map to its Cloud Logging counterpart:
   - Control plane logs → automatically in Cloud Logging (`resource.type="k8s_cluster"` and `resource.type="k8s_control_plane_component"`).
   - Container logs → `resource.type="k8s_container"`.
3. If you have downstream sinks (Splunk, Datadog, custom S3) on EKS, set up equivalent Log Router (formerly Log Sink) targets:

```bash
gcloud logging sinks create payments-to-splunk \
  --log-filter='resource.type="k8s_container" AND resource.labels.namespace_name="payments"' \
  pubsub.googleapis.com/projects/obs-prod/topics/splunk-ingest
```

For sinks to other AWS S3 buckets during co-existence: route Cloud Logging → Pub/Sub → Cloud Run job that uploads to S3 (rare; usually retire the AWS sink at cutover).

### Step 6 — Translate alarms to alerting policies

For each CloudWatch alarm:

1. Find the metric in the metric map.
2. Translate the threshold and evaluation window.
3. Write a Cloud Monitoring alerting policy:

```yaml
displayName: "Payments API — 5xx error rate > 1%"
combiner: OR
conditions:
  - displayName: "5xx > 1%"
    conditionThreshold:
      filter: |
        metric.type="loadbalancing.googleapis.com/https/backend_request_count"
        AND resource.type="https_lb_rule"
        AND resource.labels.matched_url_path_rule="payments-api"
      aggregations:
        - alignmentPeriod: 60s
          perSeriesAligner: ALIGN_RATE
          crossSeriesReducer: REDUCE_SUM
          groupByFields: ["metric.labels.response_code_class"]
      comparison: COMPARISON_GT
      thresholdValue: 0.01
      duration: 300s
notificationChannels:
  - "projects/obs-prod/notificationChannels/<id>"
documentation:
  content: "Runbook: https://runbooks/.../payments-5xx"
  mimeType: text/markdown
```

Use a Terraform module for repeatability. Don't hand-craft 80 policies in the console.

### Step 7 — Translate X-Ray to Cloud Trace

Workloads using AWS X-Ray SDK either:

- Stay on X-Ray during co-existence (the SDK accepts traces from anywhere with credentials), and switch to Cloud Trace at cutover.
- Move now to OpenTelemetry: replace AWS X-Ray SDK with OTel SDK, configure exporter for Cloud Trace.

OTel is the recommended target. Produce a per-app migration note: SDK swap, exporter config, sampling rate parity.

### Step 8 — Define / re-confirm SLOs

If the EKS estate had SLOs defined, translate them as Cloud Monitoring `Service` and `ServiceLevelObjective` resources. If not, take the opportunity to define basic ones for tier-0 services:

```yaml
apiVersion: monitoring.googleapis.com/v3
kind: ServiceLevelObjective
service: services/payments
displayName: "Payments — availability"
goal: 0.995
rollingPeriod: 2592000s   # 30 days
serviceLevelIndicator:
  requestBased:
    goodTotalRatio:
      goodServiceFilter: "..."
      totalServiceFilter: "..."
```

### Step 9 — Output

```
09-observability-translation/
├── obs-design.md
├── manifests/
│   ├── podmonitorings/
│   ├── clusterpodmonitorings/
│   └── rules/
├── terraform/
│   ├── alerting-policies.tf
│   ├── slo.tf
│   ├── log-sinks.tf
│   └── notification-channels.tf
├── dashboards/
│   ├── grafana/                # if hosting Grafana on GKE
│   └── cloud-monitoring/       # if porting to Cloud Monitoring
├── metric-map.md
├── alarm-translation.md        # Per-alarm before/after
└── escalations.md
```

## Decision points

| Decision                                | Default                  | When to deviate |
|-----------------------------------------|--------------------------|-----------------|
| Grafana host vs Cloud Monitoring native | Cloud Monitoring native  | Self-host Grafana if dashboards are deeply customized OR org-wide Grafana standardization |
| GMP vs self-managed Prometheus          | GMP                      | Self-managed only when you need Thanos / specific operator features GMP doesn't yet expose |
| X-Ray retention vs OTel migration       | OTel migration           | Stay on X-Ray briefly only if SDK swap is a long pole |
| Alarm severity mapping                  | P1=PagerDuty, P2=ticket  | Use existing org severity matrix |

## Outputs / Deliverables

```
09-observability-translation/
├── obs-design.md
├── manifests/
├── terraform/
├── dashboards/
├── metric-map.md
├── alarm-translation.md
└── escalations.md
```

## Validation

- Every CloudWatch alarm in `inventory.json` has a row in `alarm-translation.md` with target alerting policy ID.
- Every dashboard panel has either a port to Cloud Monitoring or a Grafana equivalent with confirmed metric.
- Cluster control plane logs visible in Cloud Logging within 2 minutes.
- Container logs visible in Cloud Logging within 30 seconds.
- GMP scrapes return data: `kubectl -n payments port-forward svc/payments-api 9090:metrics` and `gcloud monitoring metrics list --project obs-prod --filter 'metric.type=~"prometheus.*payments"'` returns rows.
- One end-to-end SLO query returns expected ratio.
- An alerting policy fires in test (force-throw an error, confirm pager).

## Escalation triggers

- Custom CloudWatch metrics published from EC2 SDK (not from K8s) — those need to be re-emitted from GKE workloads, often a small code change.
- Grafana dashboards using AWS-only data sources (CloudWatch source, Athena source). Replace data sources, not dashboards.
- AMG-specific features (data source proxying via AMG) without GCP analogue — evaluate self-host or alternative.

## Common pitfalls

- **Two writers, double-counting metrics.** During co-existence, both EKS and GKE workloads can emit the same metric. Tag them with cluster labels and aggregate appropriately.
- **Log volume surprise.** Cloud Logging defaults to no retention enforcement; default GKE-managed buckets store at the project level. Watch ingestion cost.
- **Alerting policies without runbook links.** The migrated alerts should keep their runbook URLs; translate the documentation field.
- **Dashboards with hardcoded AWS account IDs.** They show empty after migration. Sweep dashboards for these strings before declaring parity.
- **Sampling drift in tracing.** X-Ray defaults differ from OTel defaults. Confirm sampling rate before cutover, not after.

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [Managed Service for Prometheus](https://cloud.google.com/stackdriver/docs/managed-prometheus).
- [Migrating from CloudWatch to Cloud Operations](https://cloud.google.com/architecture/migration-to-google-cloud-monitoring-from-cloudwatch) — has the metric-name translation table.
- [SLO monitoring](https://cloud.google.com/stackdriver/docs/solutions/slo-monitoring).
- [Cloud Trace + OpenTelemetry on GKE](https://cloud.google.com/trace/docs/setup/opentelemetry).
- [docs/glossary.md](../../docs/glossary.md) — observability mapping.
- [reference/api-translation.md](../../reference/api-translation.md) — selectors and labels.
- [post-migration-ops](../post-migration-ops/SKILL.md) — golden-signals dashboard standardization.
