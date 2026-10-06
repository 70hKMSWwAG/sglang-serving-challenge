"""Build the 1-head + 4-worker logical Ray cluster for HW3 target 3.

Uses ray.cluster_utils.Cluster: no containers, no sudo. Each logical worker
node advertises exactly one "replica_slot" custom resource, and each Serve
replica requests one, so replicas land one per worker and never on the head.
Run inside deploy_app.py before deployment.
"""

from ray.cluster_utils import Cluster

HEAD_NUM_CPUS = 4
WORKER_NUM_CPUS = 8


def create_cluster(num_workers: int = 4) -> Cluster:
    cluster = Cluster()
    cluster.add_node(num_cpus=HEAD_NUM_CPUS, resources={"replica_slot": 0})
    for _ in range(num_workers):
        cluster.add_node(num_cpus=WORKER_NUM_CPUS, resources={"replica_slot": 1})
    return cluster
