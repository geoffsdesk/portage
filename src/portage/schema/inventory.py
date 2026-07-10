from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class WorkloadItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(..., description="Name of the workload or microservice")
    namespace: str = Field(..., description="Kubernetes namespace in EKS")
    kind: str = Field(..., description="Resource kind (Deployment, StatefulSet, DaemonSet, Job, etc.)")
    replicas: Optional[int] = Field(None, description="Number of replicas")
    service_account: Optional[str] = Field(None, description="Service account name")
    annotations: Dict[str, str] = Field(default_factory=dict, description="Resource annotations")


class DatabaseStore(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="Unique system ID (e.g., prod-payments-db)")
    engine: str = Field(..., description="Store engine (Postgres, MySQL, Redis, S3, Kafka, Secrets, etc.)")
    source_details: str = Field(..., description="Source AWS details (instance type, version, storage size)")
    target_engine: Optional[str] = Field(None, description="Target GCP engine (Cloud SQL, Memorystore, GCS, etc.)")
    rpo_target: Optional[str] = Field(None, description="Recovery Point Objective target")
    rto_target: Optional[str] = Field(None, description="Recovery Time Objective target")
    public_dns_or_ip: Optional[bool] = Field(False, description="Whether source is accessible via public IP/DNS")


class Inventory(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = Field(default="1.0", description="Inventory schema version")
    source_account_id: str = Field(..., description="AWS account ID")
    cluster_name: str = Field(..., description="EKS cluster name")
    workloads: List[WorkloadItem] = Field(default_factory=list, description="Discovered workloads")
    data_stores: List[DatabaseStore] = Field(default_factory=list, description="Discovered data systems")
