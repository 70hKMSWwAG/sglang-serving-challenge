"""Deploy the HW3 target-3 Ray Serve application for one experiment group.

One deployment of 4 replicas; each replica forwards to exactly one SGLang
backend and returns its identity in X-Ray-Replica-ID / X-Ray-Node-ID /
X-SGLang-Backend. Groups differ only in the router and in the replicas'
max_ongoing_requests:

  A  p2c, 5                -> default request router, default admission
  B1/B2  p2c, 16/32        -> default request router, candidate admission
  C  consistent_hash, B    -> ray.serve.experimental.ConsistentHashRouter,
                              strict affinity (num_fallback_replicas=0)
  D  affinity_load, B      -> our AffinityLoadAwareRouter (see routers.py)

Keep this process running while the traffic generator replays the workload.
"""

import argparse
import time

import ray
from ray import serve
from ray.serve.config import RequestRouterConfig
from ray.cluster_utils import Cluster

from sglang_replica import SGLangReplica
from routers import AffinityLoadAwareRouter

GROUP_CONFIG = {
    "A": {"router": "default", "router_kwargs": {}},
    "B1": {"router": "default", "router_kwargs": {}},
    "B2": {"router": "default", "router_kwargs": {}},
    "C": {
        "router": "ray.serve.experimental.consistent_hash_router.ConsistentHashRouter",
        "router_kwargs": {"num_fallback_replicas": 0},
    },
    "D": {
        "router": AffinityLoadAwareRouter,
        "router_kwargs": {"hot_fraction": 0.5},
    },
}


def parse_list(raw: str) -> list:
    return [item.strip() for item in raw.split(",") if item.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, choices=sorted(GROUP_CONFIG))
    ap.add_argument("--router-name", required=True, help="recorded only; matches run_workload.py --router-name")
    ap.add_argument("--max-ongoing-requests", type=int, required=True)
    ap.add_argument("--backends", default="127.0.0.1:31000,127.0.0.1:31001,127.0.0.1:31002,127.0.0.1:31003",
                    help="comma-separated host:port, one per replica, in order")
    ap.add_argument("--backend-ids", default="SGLang-0,SGLang-1,SGLang-2,SGLang-3",
                    help="comma-separated backend identities reported in X-SGLang-Backend")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--num-cpus-per-worker", type=int, default=8)
    args = ap.parse_args()

    backends = parse_list(args.backends)
    backend_ids = parse_list(args.backend_ids)
    if len(backends) != len(backend_ids):
        raise SystemExit("--backends and --backend-ids must have the same length")

    # Always build a fresh logical cluster for this round, so no stale
    # deployment or worker can leak in from a previous group.
    cluster = Cluster()
    cluster.add_node(num_cpus=4, resources={"replica_slot": 0})
    for _ in range(len(backends)):
        cluster.add_node(num_cpus=args.num_cpus_per_worker, resources={"replica_slot": 1})
    ray.init(address=cluster.address, ignore_reinit_error=True)
    print(f"created logical cluster with 1 head + {len(backends)} workers")

    cfg = GROUP_CONFIG[args.group]
    router_config = None
    if cfg["router"] != "default":
        router_config = RequestRouterConfig(
            request_router_class=cfg["router"],
            request_router_kwargs=cfg["router_kwargs"],
        )

    # serve.deployment(...) is a decorator factory in Ray 2.56: apply it to
    # the replica class to get a Deployment.
    deployment_kwargs = dict(
        name="SGLangReplica",
        num_replicas=len(backends),
        max_ongoing_requests=args.max_ongoing_requests,
        ray_actor_options={"num_cpus": 1, "resources": {"replica_slot": 1}},
    )
    if router_config is not None:
        deployment_kwargs["request_router_config"] = router_config
    deployment = serve.deployment(**deployment_kwargs)(SGLangReplica)

    # Each replica lands on its own worker node and picks its backend by
    # node index (see sglang_replica.py), so both lists are passed to all.
    app = deployment.bind(
        [f"http://{url}" for url in backends], backend_ids
    )
    # Ray 2.56's serve.run() no longer takes host/port; the proxy listens on
    # the default 127.0.0.1:8000, which is the BASE_URL run_group.sh probes.
    serve.run(app, name="hw3", route_prefix="/")
    print(f"Serve app deployed: name=hw3 route_prefix=/ proxy=http://127.0.0.1:{args.port}/")

    print(f"READY group={args.group} router_name={args.router_name} "
          f"max_ongoing_requests={args.max_ongoing_requests} port={args.port}")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
