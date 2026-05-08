# Annotation & API Translation Reference

The annotation-by-annotation map skills cite when translating manifests. If something isn't here, treat it as an escalation rather than guessing.

## Service / Ingress

### Service annotations

| EKS / AWS                                                                          | GKE / GCP                                                                                | Notes |
|------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|-------|
| `service.beta.kubernetes.io/aws-load-balancer-type: external`                      | drop                                                                                      | Type is implied by `Service.spec.type` and Gateway selection |
| `service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip`                 | drop                                                                                      | Use Container-native LB via NEG annotations |
| `service.beta.kubernetes.io/aws-load-balancer-scheme: internet-facing`             | drop (for Service); for L4 use Service `type: LoadBalancer` without internal annotation   |  |
| `service.beta.kubernetes.io/aws-load-balancer-scheme: internal`                    | `networking.gke.io/load-balancer-type: "Internal"`                                       |  |
| `service.beta.kubernetes.io/aws-load-balancer-cross-zone-load-balancing-enabled`   | (default behavior on GCP)                                                                | GCP regional LBs are cross-zone by default within the region |
| `service.beta.kubernetes.io/aws-load-balancer-ssl-cert: <ACM ARN>`                 | TLS via Gateway listener `tls.certificateRefs` or Certificate Manager attachment         |  |
| `service.beta.kubernetes.io/aws-load-balancer-ssl-ports: "443"`                    | Gateway listener port + protocol                                                         |  |
| `service.beta.kubernetes.io/aws-load-balancer-attributes: …`                       | `GCPBackendPolicy` (timeout, drainingTimeout, sessionAffinity, etc.)                     |  |
| `external-dns.alpha.kubernetes.io/hostname`                                        | Same — external-dns supports Cloud DNS provider; reconfigure provider                    |  |
| `external-dns.alpha.kubernetes.io/aws-…`                                           | drop; use Cloud DNS-equivalent annotations or Cloud DNS-native                            |  |

### Ingress / Gateway annotations

| EKS / AWS                                                                          | GKE / GCP                                                                                | Notes |
|------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|-------|
| `kubernetes.io/ingress.class: alb`                                                 | replace with Gateway API resources                                                       | Drop `Ingress`; create `Gateway` + `HTTPRoute` |
| `alb.ingress.kubernetes.io/scheme: internet-facing`                                | `gatewayClassName: gke-l7-global-external-managed`                                       |  |
| `alb.ingress.kubernetes.io/scheme: internal`                                       | `gatewayClassName: gke-l7-rilb`                                                          | Regional internal |
| `alb.ingress.kubernetes.io/target-type: ip`                                        | (default for NEG-based Gateway)                                                          |  |
| `alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'`                        | Gateway listener with `protocol: HTTPS`                                                  |  |
| `alb.ingress.kubernetes.io/certificate-arn: <ACM ARN>`                             | Gateway `tls.certificateRefs` to a `Secret`, or `networking.gke.io/certmap` annotation   | Re-issue cert in Certificate Manager |
| `alb.ingress.kubernetes.io/wafv2-acl-arn: …`                                       | `GCPBackendPolicy.spec.default.securityPolicy: <Cloud Armor policy>`                      |  |
| `alb.ingress.kubernetes.io/healthcheck-path: /healthz`                             | `HealthCheckPolicy.spec.default.config.httpHealthCheck.requestPath`                      |  |
| `alb.ingress.kubernetes.io/healthcheck-port: traffic-port`                         | `HealthCheckPolicy.spec.default.config.httpHealthCheck.port`                             |  |
| `alb.ingress.kubernetes.io/load-balancer-attributes`                               | `GCPBackendPolicy.spec.default.timeoutSec` and other backend fields                       |  |
| `alb.ingress.kubernetes.io/group.name`                                             | One Gateway per group; merge HTTPRoutes onto a shared Gateway                             |  |
| `alb.ingress.kubernetes.io/group.order`                                            | Use HTTPRoute rules' implicit order or explicit `match` priority                          |  |
| `alb.ingress.kubernetes.io/actions.<svc>: …`                                       | Rewrite as HTTPRoute filters (e.g., `RequestRedirect`, `URLRewrite`, `RequestHeaderModifier`) |  |
| `alb.ingress.kubernetes.io/auth-type: cognito`                                     | Identity-Aware Proxy (IAP) on the backend service via `IAPConfig`                         | Different identity provider model |
| `alb.ingress.kubernetes.io/auth-type: oidc`                                        | IAP with custom OIDC, or in-app handling                                                 |  |
| `alb.ingress.kubernetes.io/conditions.<svc>`                                       | HTTPRoute `match` block (header/query/path)                                              |  |
| `alb.ingress.kubernetes.io/load-balancer-name: <name>`                             | Static external IP and Gateway name                                                      |  |
| `alb.ingress.kubernetes.io/security-groups: <SG IDs>`                              | VPC firewall rules + Gateway frontend access control via Cloud Armor                     |  |

## ServiceAccount / Identity

| EKS / AWS                                                                | GKE / GCP                                                          | Notes |
|--------------------------------------------------------------------------|--------------------------------------------------------------------|-------|
| `eks.amazonaws.com/role-arn: arn:aws:iam::…:role/foo`                    | `iam.gke.io/gcp-service-account: foo@PROJECT.iam.gserviceaccount.com` | Identity translation |
| `eks.amazonaws.com/sts-regional-endpoints: "true"`                       | drop                                                                |  |
| `eks.amazonaws.com/audience: sts.amazonaws.com`                          | drop                                                                |  |
| `eks.amazonaws.com/token-expiration: "86400"`                            | drop                                                                |  |
| `eks.amazonaws.com/skip-containers: "init-container"`                    | drop                                                                |  |

## Pod / scheduling

### Node selectors

| EKS                                                                       | GKE                                                                                |
|---------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| `eks.amazonaws.com/nodegroup: <ng>`                                       | `cloud.google.com/gke-nodepool: <pool>`                                            |
| `karpenter.sh/capacity-type: spot`                                        | `cloud.google.com/gke-spot: "true"`                                                |
| `karpenter.sh/capacity-type: on-demand`                                   | (omit; default)                                                                    |
| `karpenter.sh/nodepool: <name>`                                           | label match against the corresponding GKE node pool                                 |
| `node.kubernetes.io/instance-type: m5.large`                              | translate to GCE machine type (e.g., `e2-standard-2`); use `cloud.google.com/machine-family` if family-only |
| `topology.kubernetes.io/region: us-east-1`                                | `topology.kubernetes.io/region: us-central1`                                       |
| `topology.kubernetes.io/zone: us-east-1a`                                 | `topology.kubernetes.io/zone: us-central1-a`                                       |
| `eks.amazonaws.com/compute-type: fargate`                                 | drop; ensure cluster is Autopilot if Fargate-equivalent is desired                 |

### Tolerations

| EKS taint                                                                | GKE taint                                                                          |
|--------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| `karpenter.sh/disruption=NoSchedule`                                     | (no equivalent; GKE Standard uses `cloud.google.com/gke-preemptible` or `gke-spot` taints when applicable) |
| Custom Karpenter NodePool taint                                          | Apply same taint name to the target GKE node pool                                  |

### Container security

| EKS / pod spec                                                            | GKE / pod spec                                                                    | Notes |
|---------------------------------------------------------------------------|-----------------------------------------------------------------------------------|-------|
| `securityContext.runAsNonRoot: true`                                      | Same; Autopilot enforces                                                          |  |
| `securityContext.privileged: true`                                        | Same on Standard; **denied on Autopilot**                                         |  |
| `hostNetwork: true`                                                       | Same on Standard; **denied on Autopilot**                                         |  |
| `hostPath` volumes                                                        | Same on Standard; **restricted on Autopilot** (only specific paths allowed)       |  |
| `runtimeClassName: crun`                                                  | Same                                                                              |  |

## Storage / PVC

| EKS                                                                       | GKE                                                                               | Notes |
|---------------------------------------------------------------------------|-----------------------------------------------------------------------------------|-------|
| StorageClass `provisioner: ebs.csi.aws.com`                               | StorageClass `provisioner: pd.csi.storage.gke.io`                                  |  |
| StorageClass parameter `type: gp3`                                        | StorageClass parameter `type: pd-balanced`                                        |  |
| StorageClass parameter `type: io2`                                        | StorageClass parameter `type: hyperdisk-extreme`                                  |  |
| StorageClass parameter `encrypted: "true" / kmsKeyId: ...`                | StorageClass parameter `disk-encryption-kms-key: projects/…/cryptoKeys/…`         |  |
| StorageClass parameter `iops: "...", throughput: "..."`                   | `provisioned-iops-on-create`, `provisioned-throughput-on-create` (Hyperdisk)      |  |
| StorageClass `provisioner: efs.csi.aws.com`                               | StorageClass `provisioner: filestore.csi.storage.gke.io`                           |  |
| StorageClass `provisioner: fsx.csi.aws.com` (Lustre)                      | StorageClass `provisioner: parallelstore.csi.storage.gke.io`                      |  |
| `volumeBindingMode: WaitForFirstConsumer`                                  | Same — required for zonal correctness                                              |  |

## Image references

| EKS                                                                       | GKE                                                                               |
|---------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| `123456789012.dkr.ecr.us-east-1.amazonaws.com/<repo>:<tag>`               | `<region>-docker.pkg.dev/<ar-project>/<repo>:<tag>`                              |
| `public.ecr.aws/<image>:<tag>`                                            | mirror to AR or use AR pull-through cache                                          |

## Logging / sidecars

| EKS                                                                       | GKE                                                                               | Notes |
|---------------------------------------------------------------------------|-----------------------------------------------------------------------------------|-------|
| Fluent Bit DaemonSet to CloudWatch                                        | drop; GKE-native logging covers it                                                 |  |
| ADOT Collector                                                            | Use the OTel Collector pointing at Cloud Trace / Cloud Monitoring                  |  |
| `eks.amazonaws.com/cloudwatch-observability` addon                        | drop; built-in                                                                     |  |

## Webhooks / cluster add-ons

| EKS                                                                       | GKE                                                                               |
|---------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| `aws-pod-identity-webhook` MutatingWebhookConfiguration                   | drop; native Workload Identity                                                    |
| `aws-load-balancer-controller` Deployment + CRDs                          | drop; native GKE Gateway controller                                               |
| `aws-ebs-csi-driver` addon                                                | drop; GKE installs PD CSI by default                                              |
| `aws-efs-csi-driver` addon                                                | replace with Filestore CSI                                                         |
| `kube-proxy` (managed addon)                                              | replaced by Dataplane V2 eBPF                                                      |
| `coredns` (managed addon)                                                 | provided by GKE                                                                    |

## CRDs of note

| Source CRD (group)                                                                        | Action |
|-------------------------------------------------------------------------------------------|--------|
| `nodepools.karpenter.sh`, `ec2nodeclasses.karpenter.k8s.aws`                              | drop; rebuild as GKE node pools (or NAP rules) in landing-zone |
| `targetgroupbindings.elbv2.k8s.aws`                                                       | drop; replace with NEG-based service backends                  |
| `appmesh.k8s.aws/Mesh, VirtualNode, VirtualService`                                       | drop; re-platform on Anthos Service Mesh                       |
| `acmpca.aws.com/AWSPCAClusterIssuer` (cert-manager external)                              | replace with `clusterissuer` for ACME via Cloud DNS or Certificate Manager attestor |
| `secrets-store.csi.x-k8s.io` SecretProviderClass with AWS provider                        | swap provider to GCP Secret Manager provider                    |
