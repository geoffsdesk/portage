---
name: network-translation
description: Translate EKS network constructs to GKE equivalents. Maps ALBs/NLBs to GKE Gateways and Services, AWS Load Balancer Controller annotations to Gateway/Service annotations, Route 53 records to Cloud DNS, security groups to VPC firewall rules and NetworkPolicy, and AWS WAF rules to Cloud Armor policies. Produces translated manifests plus a network design diff. Use after gke-landing-zone, when "translate our ingress to GKE", "convert ALB ingresses to Gateway API", or "what's the network plan for the migration".
---

# Network Translation

You translate EKS networking — load balancers, ingress, services, security groups, DNS, WAF — into the GKE equivalents. You produce diff'd manifests and a network design document.

## Purpose

Every Service, Ingress, ALB/NLB, Route 53 record, security group, and WAF rule that crosses traffic into the EKS cluster needs a GKE counterpart. This skill produces that mapping with auditable manifests.

## When to use this skill

- Phase 2, after `gke-landing-zone`.
- The user asks to "translate ingress", "set up GKE Gateway equivalents", "design the GKE network".

Do NOT use to translate identity (that's `identity-translation`) or to translate workloads (that's `workload-translation`).

## Prerequisites

- `01-discovery/inventory.json` with the network section populated.
- `03-landing-zone/plan.md` with VPCs, subnets, and clusters defined.
- `gcloud` CLI; `kubectl` context for both source and target clusters.

## Procedure

### Step 1 — Build the source-side network model

From `inventory.json`, enumerate per cluster:

- ALBs: ARN, originating Ingress, hostnames (`spec.rules[].host`), TLS cert ARN, target groups, target type (instance/ip), listener rules, attached WAF.
- NLBs: ARN, originating Service, hostnames (Route 53), target groups, port mappings.
- Internal vs internet-facing.
- VPC ID and subnets the LBs live in.
- Security groups attached to LBs and to nodes.
- Route 53 records pointing at LB DNS names (and which hosted zones).
- AWS WAF web ACLs and their rules.

### Step 2 — Map LBs to GKE constructs

Default mapping:

| EKS source                                                                | GKE target                                                                                  |
|---------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| Internet-facing ALB (HTTP/S, with host/path rules)                        | `Gateway` of class `gke-l7-global-external-managed` (or `gke-l7-regional-external-managed`) plus one or more `HTTPRoute`s |
| Internal ALB                                                              | `Gateway` of class `gke-l7-rilb` (regional internal)                                        |
| Internet-facing NLB (TCP/UDP)                                             | Service `type: LoadBalancer` with `cloud.google.com/l4-rbs: "enabled"` annotation (regional external pass-through) or `gke-l4-global-external-managed` Gateway |
| Internal NLB                                                              | Service `type: LoadBalancer` with `networking.gke.io/load-balancer-type: "Internal"`        |
| Ingress with `kubernetes.io/ingress.class: alb`                           | `HTTPRoute` attached to a `Gateway`                                                         |
| `service.beta.kubernetes.io/aws-load-balancer-type: external`             | drop annotation; pick Gateway or LB Service per type                                        |

Produce one `Gateway` per (LB, scope) tuple. Multiple Ingresses fronting the same ALB merge into multiple `HTTPRoute`s attached to the same `Gateway`.

Example translation:

**Source (EKS):**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web
  namespace: storefront
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-east-1:...:certificate/...
    alb.ingress.kubernetes.io/wafv2-acl-arn: arn:aws:wafv2:us-east-1:...:regional/webacl/...
    alb.ingress.kubernetes.io/healthcheck-path: /healthz
spec:
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: { name: web, port: { number: 80 } }
```

**Target (GKE):**

```yaml
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: storefront-external
  namespace: storefront
  annotations:
    networking.gke.io/certmap: storefront-cert-map        # if using Certificate Manager
spec:
  gatewayClassName: gke-l7-global-external-managed
  listeners:
    - name: https
      protocol: HTTPS
      port: 443
      tls:
        mode: Terminate
        certificateRefs:
          - kind: Secret
            name: shop-example-com-tls   # OR use Google-managed cert via certmap
      allowedRoutes:
        namespaces: { from: Same }
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: web
  namespace: storefront
spec:
  parentRefs:
    - name: storefront-external
  hostnames: [ "shop.example.com" ]
  rules:
    - matches:
        - path: { type: PathPrefix, value: / }
      backendRefs:
        - name: web
          port: 80
---
apiVersion: networking.gke.io/v1
kind: HealthCheckPolicy
metadata:
  name: web
  namespace: storefront
spec:
  default:
    config:
      type: HTTP
      httpHealthCheck:
        port: 80
        requestPath: /healthz
  targetRef:
    group: ""
    kind: Service
    name: web
---
apiVersion: networking.gke.io/v1
kind: GCPBackendPolicy
metadata:
  name: web
  namespace: storefront
spec:
  default:
    securityPolicy: shop-armor   # Cloud Armor policy
  targetRef:
    group: ""
    kind: Service
    name: web
```

### Step 3 — TLS / certificates

Decide per hostname:

- **Google-managed certificate** (Certificate Manager) — preferred for any hostname you control via Cloud DNS or you can prove with DNS01.
- **Self-managed certificate** — when the cert needs to come from your CA, or when ACME issuance is centralized elsewhere.

Plan the migration of every ACM-issued cert: usually re-issue in Certificate Manager rather than export/import (private keys can't always be exported).

### Step 4 — Cloud Armor (replaces AWS WAF)

> **No Google-published AWS WAF → Cloud Armor mapping exists.** Both [Cloud Armor preconfigured WAF rules](https://docs.cloud.google.com/armor/docs/waf-rules) and [Cloud Armor rule tuning](https://docs.cloud.google.com/armor/docs/rule-tuning) reference OWASP CRS lineage, not AWS Managed Rule Groups. The mappings below are **tool-opinionated** heuristics derived from the OWASP coverage of each side. Validate against real traffic; do not present them to a customer as Google guidance.

#### Step 4.1 — Pick the CRS version

Cloud Armor publishes preconfigured rules from three CRS versions:

| CRS | Suffix | Notes |
|---|---|---|
| 4.22 | `-v422-stable`, `-v422-canary` | Recommended by Google. The `nodejs` rule from v3.3 was reclassified as `generic` in v4.22 (same `934`-prefixed IDs). |
| 3.3 | `-v33-stable`, `-v33-canary` | Has separate `java` and `nodejs` rules. Useful for JSON-SQLi pre-filters (see Step 4.4). |
| 3.0 | `-stable`, `-canary` (no version suffix) | Legacy. Avoid for new policies. |

Default to v4.22. Choose canary for new tunings; promote to stable after a soak.

#### Step 4.2 — Map AWS Managed Rule Groups (heuristic)

| AWS WAF managed group | Closest Cloud Armor preconfigured rules | Notes |
|---|---|---|
| `AWSManagedRulesCommonRuleSet` | `xss-v422-stable`, `lfi-v422-stable`, `protocolattack-v422-stable`, `scannerdetection-v422-stable`, `methodenforcement-v422-stable` | Common ruleset spans many categories; combine multiples |
| `AWSManagedRulesKnownBadInputsRuleSet` | `protocolattack-v422-stable`, `scannerdetection-v422-stable` | Known-bad inputs and scanners |
| `AWSManagedRulesSQLiRuleSet` | `sqli-v422-stable` (+ `json-sqli-canary` if JSON bodies) | See JSON-SQLi note in Step 4.4 |
| `AWSManagedRulesPHPRuleSet` | `php-v422-stable` | |
| `AWSManagedRulesUnixRuleSet` | `rce-v422-stable`, `lfi-v422-stable` | RCE + LFI cover Unix attack surface |
| `AWSManagedRulesWindowsRuleSet` | `rce-v422-stable` | No Windows-specific group; RCE covers OS injection |
| `AWSManagedRulesLinuxRuleSet` | `rce-v422-stable`, `lfi-v422-stable` | |
| `AWSManagedRulesAnonymousIpList` | (No 1:1) — use Cloud Armor `origin.region_code` + IP allow-lists | Heuristic; consider Cloud Armor Adaptive Protection |
| `AWSManagedRulesAmazonIpReputationList` | (No 1:1) — Adaptive Protection + custom CEL deny | |
| `AWSManagedRulesBotControlRuleSet` | reCAPTCHA Enterprise integration with Cloud Armor | Different UX; surface as design decision |
| Custom regex / string-match rules | CEL expression(s) on the security policy | Translate each rule individually |
| Rate-based rules | `rate_limit_options` (action `rate_based_ban` or `throttle`) | Not a preconfigured-rule expression |

Surface this mapping in the network-design doc explicitly as "heuristic — review per workload."

#### Step 4.3 — Tuning level (paranoia)

Sensitivity is the OWASP CRS *paranoia level*: `0`–`4`. Lower = higher confidence, fewer false positives. Default is **4** (all signatures evaluated). Selecting `N` opts in all signatures with sensitivity `<= N`.

CEL syntax:

```
evaluatePreconfiguredWaf('sqli-v422-stable', {'sensitivity': 1})
```

Production starting points (tool-opinionated):

- `xss-v422-stable` at sensitivity 2.
- `sqli-v422-stable` at sensitivity 2; also enable `json-sqli-canary` if API accepts JSON bodies.
- `lfi-v422-stable`, `rfi-v422-stable`, `rce-v422-stable` at sensitivity 2.
- `protocolattack-v422-stable` at sensitivity 2.
- `methodenforcement-v422-stable` at sensitivity 1.
- `scannerdetection-v422-stable` at sensitivity 1 (3+ produces noise).

Opt-out specific noisy signatures with `opt_out_rule_ids` rather than dropping the whole rule:

```
evaluatePreconfiguredWaf('sqli-v422-stable', {
  'sensitivity': 4,
  'opt_out_rule_ids': ['owasp-crs-v042200-id942350-sqli', 'owasp-crs-v042200-id942360-sqli']
})
```

The signature-ID prefix must match the CRS version of the rule set (`v042200` for v4.22, `v030301` for v3.3, `v030001` for v3.0).

#### Step 4.4 — JSON-SQLi (Cloud Armor's known WAF-bypass)

Bodies must be JSON-parsed for SQLi to be caught in JSON. Google's recommended pattern is to use both:

```
evaluatePreconfiguredWaf('json-sqli-canary', {'sensitivity':0, 'opt_in_rule_ids':['owasp-crs-id942550-sqli']})
||
evaluatePreconfiguredWaf('sqli-v33-stable', {'sensitivity': 2})
```

If your application accepts JSON request bodies and any SQL-touching backend, both go in.

#### Step 4.5 — CVE rules and `cve-canary`

`cve-canary` ships canary-only and is opt-in by signature ID. Log4j and React RCE coverage:

| Signature ID | Sensitivity | What it catches |
|---|---|---|
| `owasp-crs-v030001-id044228-cve` | 1 | Base rule for CVE-2021-44228 / CVE-2021-45046 (Log4j) |
| `owasp-crs-v030001-id144228-cve` | 1 | Google enhancements for bypass / obfuscation |
| `owasp-crs-v030001-id244228-cve` | 3 | Higher-sensitivity bypass detection (some FPs) |
| `owasp-crs-v030001-id344228-cve` | 3 | Base64-encoded bypass detection (some FPs) |
| `google-mrs-v202512-id000001-rce` / `google-mrs-v202512-id000002-rce` | n/a | React RCE; gate behind a request pre-filter (below) |

React RCE recommended pre-filter (verbatim):

```
(has(request.headers['next-action']) || has(request.headers['rsc-action-id']) ||
 request.headers['content-type'].contains('multipart/form-data') ||
 request.headers['content-type'].contains('application/x-www-form-urlencoded'))
&& evaluatePreconfiguredWaf('cve-canary', {'sensitivity': 0,
   'opt_in_rule_ids': ['google-mrs-v202512-id000001-rce','google-mrs-v202512-id000002-rce']})
```

#### Step 4.6 — Terraform skeleton

```hcl
resource "google_compute_security_policy" "shop_armor" {
  project = var.cluster_project
  name    = "shop-armor"

  # OWASP CRS v4.22 baseline
  rule {
    action   = "deny(403)"
    priority = 1000
    match { expr { expression = "evaluatePreconfiguredWaf('sqli-v422-stable', {'sensitivity': 2})" } }
  }
  rule {
    action   = "deny(403)"
    priority = 1010
    match { expr { expression = "evaluatePreconfiguredWaf('xss-v422-stable', {'sensitivity': 2})" } }
  }
  rule {
    action   = "deny(403)"
    priority = 1020
    match { expr { expression = "evaluatePreconfiguredWaf('protocolattack-v422-stable', {'sensitivity': 2})" } }
  }
  rule {
    action   = "deny(403)"
    priority = 1030
    match { expr { expression = "evaluatePreconfiguredWaf('rce-v422-stable', {'sensitivity': 2})" } }
  }
  rule {
    action   = "deny(403)"
    priority = 1040
    match { expr { expression = "evaluatePreconfiguredWaf('lfi-v422-stable', {'sensitivity': 2})" } }
  }

  # Rate limiting (per-IP throttle)
  rule {
    action   = "rate_based_ban"
    priority = 2000
    rate_limit_options {
      rate_limit_threshold { count = 200, interval_sec = 60 }
      enforce_on_key       = "IP"
      ban_duration_sec     = 600
      conform_action       = "allow"
      exceed_action        = "deny(429)"
    }
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
  }

  # Default allow
  rule {
    action      = "allow"
    priority    = 2147483647
    match { versioned_expr = "SRC_IPS_V1" config { src_ip_ranges = ["*"] } }
    description = "default rule"
  }
}
```

Attach via `GCPBackendPolicy.spec.default.securityPolicy` on the relevant Service.

#### Step 4.7 — Operational gotchas Google calls out

- Rule changes take "several minutes to propagate." Plan accordingly.
- Cloud Armor evaluates preconfigured rules against the **first 64 KB** of request body. Larger payloads are not inspected end-to-end.
- JSON parsing must be enabled to inspect JSON bodies.
- The `--request-*-to-exclude` controls (header / cookie / query / URI) cannot be used on rules with action `allow`.
- Adaptive Protection is enabled at the security-policy level (`--enable-layer7-ddos-defense`); it doesn't expose a per-rule CEL expression but ML-suggests rules in alerts.

### Step 5 — DNS

For every Route 53 record that points at an LB DNS name:

1. Plan a Cloud DNS record in the target zone (or the same zone, depending on TLD ownership). For apex hostnames, GKE Gateway gives you an IP; use an `A` record. For subdomains, you can `CNAME` to the Gateway address — but you'll need a deterministic Gateway hostname or static IP.
2. For weighted DNS (used by `traffic-cutover`), use Cloud DNS routing policies (`weighted_round_robin`) or move the records to a CDN/global LB that supports weighted backends natively.
3. If the existing zone is in Route 53 and you can't move it yet, plan delegation via NS records, or configure the cutover to update Route 53 directly during `traffic-cutover`.

Capture every DNS change as a `dns-plan.md` under the run directory.

### Step 6 — Security groups → VPC firewall + NetworkPolicy

EKS security groups attached to nodes and LBs map to:

- **Node-to-node traffic**: GKE handles intra-cluster networking via the VPC subnet's firewall rules. The Shared VPC's hierarchical firewall plus `gke-cluster-name-` rules cover most.
- **External-to-LB**: GFE health check ranges and your allow-listed CIDRs become VPC firewall `INGRESS` rules targeting the LB's network tag.
- **Pod-to-pod within cluster**: implement as Kubernetes NetworkPolicy (Dataplane V2 enforces). Translate any `aws-load-balancer-controller` annotation that restricts pod ingress into a NetworkPolicy.

Produce per-namespace NetworkPolicy YAML restricting pod ingress to known ServiceAccount selectors and ports. Default-deny in production namespaces is recommended.

### Step 7 — Egress

EKS pods typically egressed via NAT Gateway with no per-pod identity. GKE pods egress via Cloud NAT, with Workload Identity providing per-workload identity for GCP API calls.

For external (non-GCP) egress destinations:

- Static egress IPs: reserve in Cloud NAT and document.
- Allow-listed destinations on the partner side: send the partner the new IPs ahead of cutover.
- VPC peering / TGW reachability: re-create with VPC peering or NCC (Network Connectivity Center).

### Step 8 — Output the design diff

Render `04-network-translation/network-design.md` with:

- Diagram (ASCII or Mermaid) of source vs target network topologies, side by side.
- Table mapping every source LB ARN to the target Gateway/Service.
- Cert migration plan.
- Cloud Armor policy mapping table.
- DNS cutover plan (which records, which TTLs, planned change windows).
- Firewall rule changes.

Render `04-network-translation/manifests/` with one file per Gateway and HTTPRoute, plus per-namespace NetworkPolicy.

## Decision points

| Decision                                  | Default                                    | When to deviate                       |
|-------------------------------------------|--------------------------------------------|---------------------------------------|
| Gateway API vs Ingress                    | Gateway API                                | Ingress only if a controller you depend on doesn't yet support Gateway |
| Global vs regional Gateway                | Global for true multi-region traffic; regional otherwise | Regional for cost or sovereignty constraints |
| ACM cert reuse vs Certificate Manager re-issue | Certificate Manager re-issue              | Reuse only if private key export is feasible and required |
| AWS WAF preconfigured rules → Cloud Armor preconfigured | 1:1 by category                            | Custom rewrites for org-specific rules |
| NAT egress vs per-workload Cloud NAT routes | Single Cloud NAT with manual port allocation | Per-egress-destination Cloud NAT only for very high egress workloads |

## Outputs / Deliverables

```
04-network-translation/
├── network-design.md
├── manifests/
│   ├── gateways/
│   ├── httproutes/
│   ├── network-policies/
│   ├── healthcheck-policies/
│   └── backend-policies/
├── terraform/
│   ├── cloud-armor/
│   ├── certificates/
│   └── dns/
├── dns-plan.md
└── escalations.md
```

## Validation

- Every ALB/NLB in `inventory.json` has a target Gateway/Service in the manifests.
- Every host in any source Ingress is covered by exactly one target HTTPRoute.
- Every TLS cert ARN in source has a planned Certificate Manager entry or self-managed cert.
- Cloud Armor mapping has been reviewed by the user; non-trivial WAF rules have explicit acceptance.
- Apply manifests to a non-prod cluster and confirm: `kubectl describe gateway` shows `Programmed: True`; the Gateway has an external IP; `curl https://...` succeeds against a backend that already exists or against a placeholder.
- NetworkPolicy doesn't break existing flows in the soak test.

## Escalation triggers

- Workloads using `LoadBalancerSourceRanges` with overlapping or conflicting CIDRs across namespaces — surface for review.
- TLS certs that cannot be reissued (private CA chain, customer-supplied) — surface for human plan.
- Custom AWS WAF JS challenge / CAPTCHA flows — Cloud Armor reCAPTCHA Enterprise has a different UX; needs product decision.
- Egress dependencies on AWS-only endpoints (e.g., S3 VPC endpoint) — needs cross-cloud egress plan.

## Common pitfalls

- **Forgetting health check paths.** The ALB health check path is in an annotation; in GKE it's a `HealthCheckPolicy`. Skip and your backends look unhealthy.
- **Not setting `BackendConfig`/`GCPBackendPolicy`.** Timeouts default to 30s. Many workloads need longer. Translate explicitly.
- **TLS hostname mismatches.** ACM SANs migrate cleanly; ACM wildcards plus exotic SANs sometimes don't. Verify each cert.
- **Cloud Armor preconfigured WAF tuning level.** `cve-canary` is sensitive; `cve-stable` is the production default. Match severity.
- **Default-deny NetworkPolicy applied with no allow rules.** The cluster is now silent. Stage default-deny via a soak window.
- **GKE ManagedCertificate stays in `FAILED_NOT_VISIBLE` until LB IP attaches and DNS resolves to it.** Sequence the cutover so DNS is updated *before* the cert is expected to validate, not after. See [LFF-26](../../reference/lessons-from-the-field.md#lff-26--gke-managedcertificate-validates-only-after-the-lb-ip-attaches-and-dns-a-record-points-at-it).
- **ManagedCertificate doesn't work with nginx-ingress.** Decision point: Gateway+ManagedCertificate, or nginx-ingress+cert-manager. Make it up-front. See [LFF-27](../../reference/lessons-from-the-field.md#lff-27--managedcertificate-doesnt-work-with-nginx-ingress-cert-manager-is-the-alternative).
- **Gateway API on GKE expects a pre-shared SslCertificate**, not a ManagedCertificate CR. When targeting Gateway API, plan TLS via Certificate Manager from the start. See [LFF-28](../../reference/lessons-from-the-field.md#lff-28--gateway-api-on-gke-requires-pre-shared-compute-sslcertificate-not-a-managedcertificate-cr).
- **ALB `group.name` semantics don't translate to Gateway API.** Rebuild as one Gateway with multiple HTTPRoutes. See [LFF-20](../../reference/lessons-from-the-field.md#lff-20--alb-groupname-annotation-creates-a-new-alb-instead-of-mutating-the-existing-one).

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [Cloud Armor preconfigured WAF rules](https://docs.cloud.google.com/armor/docs/waf-rules) — verbatim source for rule names and CRS versions.
- [Cloud Armor rule tuning](https://docs.cloud.google.com/armor/docs/rule-tuning) — sensitivity model (paranoia 0–4).
- [GKE Gateway controller](https://cloud.google.com/kubernetes-engine/docs/concepts/gateway-api).
- [Choosing a load balancer](https://cloud.google.com/load-balancing/docs/choosing-load-balancer).
- [Certificate Manager](https://cloud.google.com/certificate-manager/docs).
- [Cloud DNS routing policies](https://cloud.google.com/dns/docs/zones/manage-routing-policies).
- [docs/glossary.md](../../docs/glossary.md) — networking translations.
- [reference/api-translation.md](../../reference/api-translation.md) — annotation-by-annotation map.
- [traffic-cutover](../traffic-cutover/SKILL.md) — uses the DNS plan output.
