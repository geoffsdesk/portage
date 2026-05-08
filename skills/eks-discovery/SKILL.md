---
name: eks-discovery
description: Inventory an Amazon EKS estate end-to-end. Enumerates clusters, node groups, workloads, addons, IAM (IRSA), networking (ALBs, NLBs, security groups), storage (PVs, EBS, EFS), data dependencies (RDS, ElastiCache), and observability config. Use when starting an EKS-to-GKE migration, when "we need to know what's actually in this account", when producing a pre-migration inventory, or when the user says "audit our EKS environment". Outputs a structured inventory.json plus a human-readable summary.
---

# EKS Discovery

You are an EKS inventory specialist. Read the source AWS environment with read-only credentials and produce a complete, machine-readable inventory of everything a migration needs to know about. You write nothing back to AWS.

## Purpose

Produce `inventory.json` and `inventory-summary.md` so the rest of Portage has ground truth. Every downstream skill consumes these.

## When to use this skill

- The orchestrator invokes this in Phase 1.
- A user asks "what's in our EKS account?" without a migration context — answer with this skill, but stop after the inventory step.
- A user wants a fresh inventory after material changes (new clusters added, new workloads, new IRSA bindings).

Do NOT use to discover non-EKS workloads. EKS-only.

## Prerequisites

- Read-only AWS credentials with at minimum: `eks:Describe*`, `eks:List*`, `ec2:Describe*`, `iam:Get*`, `iam:List*`, `elasticloadbalancing:Describe*`, `rds:Describe*`, `elasticache:Describe*`, `cloudwatch:Describe*`, `logs:Describe*`, `ecr:Describe*`, `ecr:List*`, `s3:List*`, `s3:GetBucketLocation`, `s3:GetBucketTagging`, `secretsmanager:List*`, `kms:List*`, `kms:Describe*`.
- `aws` CLI v2, `kubectl`, `jq`, `yq`.
- `kubectl` context configured for each cluster in scope (run `aws eks update-kubeconfig` per cluster).

## Procedure

### Step 1 — Confirm scope

```bash
aws sts get-caller-identity
aws eks list-clusters --region "$REGION"
```

Confirm with the user which clusters are in scope. If the orchestrator handed you a list, verify each one exists and you can reach it.

### Step 2 — Cluster-level facts

For each cluster:

```bash
CLUSTER=...; REGION=...
aws eks describe-cluster --name "$CLUSTER" --region "$REGION" \
  --query 'cluster.{
    name: name,
    version: version,
    platformVersion: platformVersion,
    endpoint: endpoint,
    publicAccess: resourcesVpcConfig.endpointPublicAccess,
    privateAccess: resourcesVpcConfig.endpointPrivateAccess,
    vpcId: resourcesVpcConfig.vpcId,
    subnetIds: resourcesVpcConfig.subnetIds,
    clusterSGs: resourcesVpcConfig.clusterSecurityGroupId,
    additionalSGs: resourcesVpcConfig.securityGroupIds,
    logging: logging.clusterLogging,
    encryption: encryptionConfig
  }' > "cluster.$CLUSTER.json"
```

Capture: control-plane version, OIDC provider URL (used for IRSA), authentication mode (`API`, `API_AND_CONFIG_MAP`, `CONFIG_MAP`), encryption KMS key ARNs, secrets-encryption status.

### Step 3 — Node groups and Karpenter

```bash
aws eks list-nodegroups --cluster-name "$CLUSTER" --region "$REGION" \
  --query 'nodegroups' --output text | tr '\t' '\n' | while read NG; do
    aws eks describe-nodegroup --cluster-name "$CLUSTER" --region "$REGION" --nodegroup-name "$NG" \
      > "ng.$CLUSTER.$NG.json"
done
```

If Karpenter is in use:

```bash
kubectl get nodepool -A -o yaml > "karpenter.$CLUSTER.nodepool.yaml"
kubectl get ec2nodeclass -A -o yaml > "karpenter.$CLUSTER.ec2nodeclass.yaml"
kubectl get nodeclaims -A > "karpenter.$CLUSTER.nodeclaims.txt"
```

Record per node group: instance types, capacity type (ON_DEMAND, SPOT), AMI type (AL2_x86_64, BOTTLEROCKET_*), taints, labels, scaling config, launch template overrides.

### Step 4 — Addons

```bash
aws eks list-addons --cluster-name "$CLUSTER" --region "$REGION" --query 'addons' --output text \
  | tr '\t' '\n' | while read A; do
  aws eks describe-addon --cluster-name "$CLUSTER" --region "$REGION" --addon-name "$A" > "addon.$CLUSTER.$A.json"
done
```

Catalog: `vpc-cni`, `kube-proxy`, `coredns`, `aws-ebs-csi-driver`, `aws-efs-csi-driver`, `eks-pod-identity-agent`, `cloudwatch-observability`, `aws-mountpoint-s3-csi-driver`, anything custom.

For each, capture version + configuration overrides (`configurationValues`).

### Step 5 — Workloads (per cluster)

```bash
for kind in deployments statefulsets daemonsets cronjobs jobs replicasets services ingresses gateways httproutes \
            configmaps secrets serviceaccounts roles rolebindings clusterroles clusterrolebindings \
            persistentvolumeclaims persistentvolumes storageclasses networkpolicies poddisruptionbudgets \
            horizontalpodautoscalers verticalpodautoscalers; do
  kubectl get "$kind" --all-namespaces -o yaml > "workloads.$CLUSTER.$kind.yaml" 2>/dev/null
done

kubectl api-resources --verbs=list --namespaced -o name \
  | grep -vE '^events$|^events\.events\.k8s\.io$|^componentstatuses$|^endpoints$|^endpointslices' \
  | while read R; do
    kubectl get "$R" --all-namespaces -o yaml >> "workloads.$CLUSTER.crds.yaml" 2>/dev/null
done
```

Then summarize:

- Total namespaces, with workload counts per namespace.
- Stateful workloads (StatefulSets + Deployments with PVCs).
- DaemonSets (these are platform-level — flag every one).
- Workloads using `hostNetwork`, `hostPID`, `hostPath`, or privileged containers.
- Workloads using non-standard `runtimeClassName`.
- Workloads referencing AWS-only fields (annotations beginning with `eks.amazonaws.com`, `service.beta.kubernetes.io/aws-`, `alb.ingress.kubernetes.io`, `external-dns.alpha.kubernetes.io/aws-`).

### Step 6 — IRSA mapping

For each cluster, list ServiceAccounts annotated with `eks.amazonaws.com/role-arn`:

```bash
kubectl get sa --all-namespaces -o json \
  | jq -r '.items[] | select(.metadata.annotations["eks.amazonaws.com/role-arn"]) |
    [.metadata.namespace, .metadata.name, .metadata.annotations["eks.amazonaws.com/role-arn"]] | @tsv' \
  > "irsa.$CLUSTER.tsv"
```

For each role ARN found:

```bash
ROLE=$(echo "$ARN" | awk -F/ '{print $NF}')
aws iam get-role --role-name "$ROLE" > "iam.role.$ROLE.json"
aws iam list-attached-role-policies --role-name "$ROLE" > "iam.role.$ROLE.attached.json"
aws iam list-role-policies --role-name "$ROLE" > "iam.role.$ROLE.inline.json"
for P in $(aws iam list-role-policies --role-name "$ROLE" --query 'PolicyNames' --output text); do
  aws iam get-role-policy --role-name "$ROLE" --policy-name "$P" > "iam.role.$ROLE.inline.$P.json"
done
```

This produces the input to `identity-translation`.

### Step 7 — Networking

```bash
# Cluster VPC + subnets
aws ec2 describe-vpcs --vpc-ids "$VPC" > "vpc.$VPC.json"
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC" > "subnets.$VPC.json"
aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC" > "routes.$VPC.json"
aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC" > "sgs.$VPC.json"
aws ec2 describe-nat-gateways --filter "Name=vpc-id,Values=$VPC" > "nats.$VPC.json"
aws ec2 describe-vpc-endpoints --filters "Name=vpc-id,Values=$VPC" > "vpcendpoints.$VPC.json"
aws ec2 describe-transit-gateway-attachments --filters "Name=resource-id,Values=$VPC" > "tgw.$VPC.json"
aws ec2 describe-vpc-peering-connections --filters "Name=requester-vpc-info.vpc-id,Values=$VPC" > "peerings.$VPC.json"

# Load balancers in scope
aws elbv2 describe-load-balancers > "elbv2.json"
aws elbv2 describe-target-groups > "tgs.json"
aws elbv2 describe-listeners --load-balancer-arn "$LB" > "listeners.$LB.json"
```

Cross-reference: which load balancers are pointed to by which Ingress / Service in which cluster. The `aws-load-balancer-controller` annotates each provisioned LB with the originating K8s resource — capture those tags.

### Step 8 — Storage

```bash
kubectl get pv -o yaml > "pv.$CLUSTER.yaml"
kubectl get pvc --all-namespaces -o yaml > "pvc.$CLUSTER.yaml"
kubectl get storageclass -o yaml > "sc.$CLUSTER.yaml"

# EBS volumes attached to the cluster
aws ec2 describe-volumes \
  --filters "Name=tag:kubernetes.io/cluster/$CLUSTER,Values=owned" \
  > "ebs.$CLUSTER.json"

# EFS file systems referenced
aws efs describe-file-systems > "efs.json"
aws efs describe-access-points > "efs-aps.json"
```

For each PV, capture: storage class, size, access modes, reclaim policy, volume handle (EBS volume ID or EFS FS+AP), encryption status, snapshot history.

### Step 9 — Data dependencies

For RDS, ElastiCache, MSK, OpenSearch, DynamoDB:

```bash
aws rds describe-db-instances > "rds.json"
aws rds describe-db-clusters > "rds-clusters.json"
aws elasticache describe-cache-clusters > "elasticache.json"
aws elasticache describe-replication-groups > "elasticache-rg.json"
aws kafka list-clusters-v2 > "msk.json"
aws opensearch list-domain-names > "opensearch.json"
aws dynamodb list-tables > "dynamodb.json"
```

For each, capture: engine + version, instance class, multi-AZ, encryption, network reachability (subnet group, security groups), backup config, parameter groups, *which K8s workloads connect to it* (look up by Secret values, ConfigMap values, env-from references).

### Step 10 — Registries

```bash
aws ecr describe-repositories > "ecr.json"
for REPO in $(aws ecr describe-repositories --query 'repositories[].repositoryName' --output text); do
  aws ecr describe-images --repository-name "$REPO" --query 'imageDetails[*].{tags:imageTags,digest:imageDigest,pushed:imagePushedAt,size:imageSizeInBytes}' \
    > "ecr.$REPO.json"
done
```

Cross-reference image references in workload manifests so `registry-migration` knows what's actually used vs cruft.

### Step 11 — Observability

```bash
aws logs describe-log-groups --log-group-name-prefix "/aws/eks/$CLUSTER" > "logs.$CLUSTER.json"
aws cloudwatch list-dashboards > "dashboards.json"
aws cloudwatch describe-alarms --alarm-name-prefix "EKS" > "alarms.json"
aws aps list-workspaces > "amp.json"      # if Managed Prometheus
aws grafana list-workspaces > "amg.json"  # if Managed Grafana
```

Capture: log groups + retention + KMS encryption, dashboards (export JSON), alarms (export JSON), AMP workspaces and which clusters write to them, Grafana data sources and dashboards.

### Step 12 — Secrets, KMS, certificates

```bash
aws secretsmanager list-secrets > "secrets.json"
aws kms list-aliases > "kms.json"
aws acm list-certificates > "acm.json"
```

Cross-reference: which K8s Secrets are mirrored from Secrets Manager (look for `secrets-store.csi.x-k8s.io` SecretProviderClass references). Which workloads reference which KMS key.

## Decision points

- **Sampling vs full enumeration.** For very large clusters (>1k workloads), the skill samples by namespace tier (prod / non-prod) and surfaces the sample plan to the user. Default: full enumeration.
- **Live mode vs snapshot.** Default: snapshot (no watching, single point-in-time). Switch to live only if requested.
- **Cross-account discovery.** If workloads pull from ECR in another account or RDS in another account, request read-only access there and discover symmetrically. If denied, flag as an escalation.

## Outputs / Deliverables

```
01-discovery/
├── inventory.json             # Machine-readable, the canonical input for downstream skills.
├── inventory-summary.md       # Human-readable: clusters, workload counts, key risks.
├── raw/                       # Every file from the procedure above, untouched.
├── irsa-map.tsv               # IRSA SA → IAM role index.
├── data-dependencies.md       # Per-workload upstream data systems.
└── escalations.md             # Anything weird (custom CNI, hostNetwork DaemonSets, …).
```

`inventory.json` schema (excerpt):

```json
{
  "run_id": "...",
  "discovered_at": "2026-05-06T14:00:00Z",
  "clusters": [{
    "name": "prod-east", "region": "us-east-1", "version": "1.30",
    "vpc": {"id": "vpc-...", "cidr": "10.0.0.0/16"},
    "node_groups": [{ "name": "...", "ami_type": "BOTTLEROCKET_X86_64", "capacity_type": "ON_DEMAND", "instance_types": ["m6i.large"], "min": 3, "max": 12 }],
    "karpenter": { "enabled": true, "node_pools": ["default", "spot"] },
    "addons": [{ "name": "vpc-cni", "version": "v1.18.0-eksbuild.1" }],
    "workloads": {
      "namespaces": [{ "name": "default", "deployments": 12, "statefulsets": 1, "daemonsets": 0 }],
      "stateful": [{ "namespace": "data", "name": "kafka", "kind": "StatefulSet", "pvc_count": 3 }],
      "host_network": [{ "namespace": "kube-system", "name": "fluent-bit" }],
      "irsa_bindings": [{ "namespace": "checkout", "sa": "checkout", "role_arn": "arn:aws:iam::...:role/checkout" }]
    },
    "ingress": {
      "albs": [{ "arn": "...", "ingress_ref": "default/web", "tls_cert_arn": "..." }],
      "nlbs": [{ "arn": "...", "service_ref": "kafka/broker" }]
    },
    "storage": {
      "pvc_count": 17, "ebs_total_gib": 4400, "efs_filesystems": 1,
      "storage_classes": ["gp3-encrypted", "io2-fast"]
    },
    "data_deps": [{ "kind": "rds", "engine": "postgres", "version": "15.4", "consumers": ["checkout/checkout"] }],
    "observability": { "log_groups": 3, "dashboards": 5, "amp_workspaces": 1 }
  }]
}
```

## Validation

Before declaring discovery complete:

- Every namespace has a workload count, even if zero.
- Every IRSA SA maps to a real, currently-existing IAM role (otherwise flag stale binding).
- Every PV resolves to a real EBS volume / EFS access point.
- Every ALB and NLB maps back to at least one Ingress or Service.
- The number of unique container images in workloads equals the number of distinct `(repo, tag-or-digest)` pairs referenced — no orphans, no missing.
- Every escalation in `escalations.md` has a category tag and a one-line summary.

## Escalation triggers

Open an escalation (do not silently translate) when discovery finds:

- A custom CNI (Calico in BGP mode, Cilium with custom config, anything not VPC CNI). Translation strategy must be human-decided.
- A workload using `hostNetwork: true` outside `kube-system`. May not be portable as-is.
- A privileged DaemonSet not in a known catalog (cloudwatch-agent, fluent-bit, node-problem-detector, csi-node-driver, vpc-cni-node, kube-proxy, ebs-csi-node, efs-csi-node).
- An IRSA role with `*` in resources or with cross-account trust relationships.
- A PV with `ReadWriteMany` not on EFS (means a third-party CSI you must catalog separately).
- Any workload referencing an AWS-only API directly via SDK (these will need code changes, not config translation).

## Common pitfalls

- **Discovering only what kubectl shows.** kubectl misses what's *configured but not running* (orphaned PVCs, abandoned IAM roles, stale ALBs). Cross-reference AWS API responses, not just K8s state.
- **Ignoring CRDs.** Custom resources (Argo Workflows, Crossplane, Karpenter NodeClaims, Istio configurations) are first-class workloads. Capture them.
- **Not capturing image digests.** Tags can be re-pushed. Capture digests so the registry migration can verify identity.
- **Missing the EKS authentication mode.** If the cluster is `CONFIG_MAP` (legacy), the IAM-to-K8s mapping lives in the `aws-auth` ConfigMap and must be translated to GKE IAM/RBAC, not just IRSA.

## References

- **Canonical sources**: [reference/sources.md](../../reference/sources.md).
- [Migrate from Amazon EKS to GKE — Assess your environment](https://docs.cloud.google.com/architecture/migrate-amazon-eks-to-gke) — the assessment phase of Google's matching series; mentions KubeScan and Migration Center as alternative discovery tools.
- [AWS EKS user guide](https://docs.aws.amazon.com/eks/latest/userguide/) — source-side accuracy for IRSA, addons, VPC CNI semantics.
- [Karpenter docs](https://karpenter.sh/docs/) — for accurate translation of NodePool and EC2NodeClass discovery.
- [docs/glossary.md](../../docs/glossary.md) — service map.
- [migration-assessment](../migration-assessment/SKILL.md) — consumes this skill's output.
- [identity-translation](../identity-translation/SKILL.md) — consumes IRSA map.
