#!/usr/bin/env python3
"""
HW3 target3: Ray Serve front-end for the 4-replica SGLang routing comparison.

Topology (everything on one machine)::

    Client --POST /generate--> Ray Serve HTTP proxy (port 8000)
        --RequestRouter--> SGLangRouter replica (4 replicas, one per worker node)
        --HTTP POST /generate--> fixed SGLang backend http://127.0.0.1:3000<i>

The 4 replicas form ONE Serve deployment ("sglang-router", route_prefix="/"),
so Ray Serve's request router -- configured per ROUTER_MODE through
``RequestRouterConfig`` -- is what chooses the replica:

    A_default   default PowerOfTwoChoices router, max_ongoing_requests=5
    B_cand1     default router, max_ongoing_requests=16
    B_cand2     default router, max_ongoing_requests=64
    C_affinity  ConsistentHashRouter(num_virtual_nodes=100,
                num_fallback_replicas=0); the routing key is the X-Session-Id
                header, which the course traffic generator sets to the
                prefix-family id.
    D_improved  custom AffinityLoadAwareRouter (see routers.py): consistent-hash
                prefix affinity first, fall back to the least-loaded replica
                when the affinity replica's in-flight queue >= threshold.

Replica placement: 4 logical worker nodes are created with
``ray.cluster_utils.Cluster`` (no containers / sudo needed), each advertising
a custom resource ``hw3_worker``. The deployment requests one placement-group
bundle ``{"CPU": 1, "hw3_worker": 1}`` per replica; because every worker owns
exactly 1.0 unit of ``hw3_worker``, the 4 replicas are forced onto 4 distinct
worker nodes. Each replica resolves its own node id at startup and binds
itself to exactly one SGLang backend for its whole lifetime.

Response headers (required by the course traffic generator
``run_workload.py``)::

    X-Ray-Replica-ID   stable id of the Serve replica handling the request
    X-Ray-Node-ID      Ray node id of that replica
    X-SGLang-Backend   index (0-3) of the SGLang backend used

The /generate SSE byte stream -- including ``meta_info.cached_tokens``, which
the traffic generator uses for the cache-hit-rate metric -- is proxied
verbatim from SGLang.

Run (via run_round.sh, or manually)::

    python serve_app.py --router-mode A_default
    python serve_app.py --router-mode C_affinity --max-ongoing-requests 32
    python serve_app.py --router-mode D_improved --max-ongoing-requests 32 \\
        --fallback-threshold 24
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402
import ray  # noqa: E402
from ray import serve  # noqa: E402
from ray.cluster_utils import Cluster  # noqa: E402
from ray.serve.config import RequestRouterConfig  # noqa: E402
from ray.serve.context import _get_internal_replica_context  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse, Response, StreamingResponse  # noqa: E402

# ----------------------------------------------------------------------------
# Router-mode table. --max-ongoing-requests overrides the default below.
# ----------------------------------------------------------------------------
ROUTER_MODES = {
    "A_default": {"router": "p2c", "default_max_ongoing": 5},
    "B_cand1": {"router": "p2c", "default_max_ongoing": 16},
    "B_cand2": {"router": "p2c", "default_max_ongoing": 64},
    "C_affinity": {"router": "consistent_hash", "default_max_ongoing": 32},
    "D_improved": {"router": "custom", "default_max_ongoing": 32},
}

# Request headers the course traffic generator sends; forwarded to SGLang.
FWD_HEADERS = ("x-session-id", "x-workload-request-id", "x-prefix-family")

WORKER_RESOURCE = "hw3_worker"
N_BACKENDS = 4


def build_router_config(router_mode: str, fallback_threshold=None) -> RequestRouterConfig:
    """RequestRouterConfig for the chosen experimental group."""
    kind = ROUTER_MODES[router_mode]["router"]
    if kind == "p2c":
        # Ray Serve's default router (PowerOfTwoChoicesRequestRouter).
        return RequestRouterConfig()
    if kind == "consistent_hash":
        # Group C: strict prefix affinity, no fallback.
        return RequestRouterConfig(
            request_router_class=(
                "ray.serve.experimental.consistent_hash_router:ConsistentHashRouter"
            ),
            request_router_kwargs={
                "num_virtual_nodes": 100,
                "num_fallback_replicas": 0,
            },
        )
    if kind == "custom":
        # Group D: our AffinityLoadAwareRouter (routers.py).
        from routers import AffinityLoadAwareRouter

        kwargs = {
            "num_virtual_nodes": 100,
            "num_fallback_replicas": 0,
        }
        if fallback_threshold is not None:
            kwargs["fallback_inflight_threshold"] = int(fallback_threshold)
        return RequestRouterConfig(
            request_router_class=AffinityLoadAwareRouter,
            request_router_kwargs=kwargs,
        )
    raise ValueError(f"unknown router kind: {kind}")


class SGLangRouter:
    """One Serve replica = one fixed SGLang backend + HTTP/SSE proxying.

    ``__call__`` receives the raw Starlette request (Ray Serve >= 2.x routes
    HTTP to ``__call__(request: Request)``); we dispatch on the path.
    """

    def __init__(self, node_to_backend: dict):
        ctx = _get_internal_replica_context()
        self.replica_id = ctx.replica_id.unique_id
        self.node_id = ray.get_runtime_context().get_node_id()
        try:
            info = node_to_backend[self.node_id]
        except KeyError:
            raise RuntimeError(
                f"replica {self.replica_id}: node {self.node_id} has no "
                f"SGLang backend assigned (known nodes: {sorted(node_to_backend)})"
            )
        self.backend_index = int(info["index"])
        self.sglang_url = info["url"].rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=30.0, read=300.0, write=60.0),
            limits=httpx.Limits(max_connections=1000, max_keepalive_connections=200),
        )
        print(
            f"[SGLangRouter] replica={self.replica_id} node={self.node_id} "
            f"-> backend {self.backend_index} ({self.sglang_url})",
            flush=True,
        )

    # -- helpers ------------------------------------------------------
    def _routing_headers(self) -> dict:
        return {
            "X-Ray-Replica-ID": self.replica_id,
            "X-Ray-Node-ID": self.node_id,
            "X-SGLang-Backend": str(self.backend_index),
        }

    async def _handle_generate(self, request: Request):
        body = await request.body()
        fwd = {"content-type": "application/json"}
        for name in FWD_HEADERS:
            if name in request.headers:
                fwd[name] = request.headers[name]
        url = self.sglang_url + "/generate"
        try:
            sglang_req = self._client.build_request("POST", url, content=body, headers=fwd)
            sglang_resp = await self._client.send(sglang_req, stream=True)
        except httpx.HTTPError as exc:
            return JSONResponse(
                {"error": f"SGLang backend {self.backend_index} unreachable: {exc}"},
                status_code=502,
                headers=self._routing_headers(),
            )
        if sglang_resp.status_code != 200:
            content = await sglang_resp.aread()
            await sglang_resp.aclose()
            return Response(
                content=content,
                status_code=sglang_resp.status_code,
                media_type="application/json",
                headers=self._routing_headers(),
            )

        async def sse_bytes():
            try:
                async for chunk in sglang_resp.aiter_bytes():
                    yield chunk
            finally:
                await sglang_resp.aclose()

        return StreamingResponse(
            sse_bytes(),
            media_type="text/event-stream",
            headers=self._routing_headers(),
        )

    async def _handle_healthz(self):
        return JSONResponse(
            {
                "ok": True,
                "replica_id": self.replica_id,
                "node_id": self.node_id,
                "sglang_backend": self.backend_index,
                "sglang_url": self.sglang_url,
            },
            headers=self._routing_headers(),
        )

    # -- HTTP entrypoint ----------------------------------------------
    async def __call__(self, request: Request):
        path = request.url.path
        if path == "/healthz" and request.method == "GET":
            return await self._handle_healthz()
        if path == "/generate" and request.method == "POST":
            return await self._handle_generate(request)
        return JSONResponse({"error": f"not found: {request.method} {path}"}, status_code=404)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="HW3 target3 Ray Serve application")
    parser.add_argument(
        "--router-mode",
        choices=sorted(ROUTER_MODES),
        required=True,
        help="experimental group: A_default / B_cand1 / B_cand2 / C_affinity / D_improved",
    )
    parser.add_argument(
        "--max-ongoing-requests",
        type=int,
        default=None,
        help="override for the deployment's max_ongoing_requests "
        "(default per router mode; B's chosen value must be passed for C/D)",
    )
    parser.add_argument(
        "--fallback-threshold",
        type=int,
        default=None,
        help="group D only: in-flight threshold above which the affinity "
        "replica is bypassed (default: 75%% of max_ongoing_requests)",
    )
    parser.add_argument("--serve-port", type=int, default=8000)
    parser.add_argument("--sglang-base-port", type=int, default=30000,
                        help="SGLang backends listen on base_port + [0..3]")
    parser.add_argument("--sglang-host", default="127.0.0.1")
    parser.add_argument("--head-cpus", type=int, default=4)
    parser.add_argument("--worker-cpus", type=int, default=4)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    mode_info = ROUTER_MODES[args.router_mode]
    max_ongoing = args.max_ongoing_requests or mode_info["default_max_ongoing"]

    # -- 1. Ray cluster: 1 head + 4 logical workers --------------------
    print("[serve_app] starting Ray cluster: 1 head + 4 workers", flush=True)
    cluster = Cluster(
        initialize_head=True,
        head_node_args={"num_cpus": args.head_cpus},
        connect=True,
    )
    for _ in range(N_BACKENDS):
        cluster.add_node(
            num_cpus=args.worker_cpus,
            resources={WORKER_RESOURCE: 1},
        )
    cluster.wait_for_nodes()

    worker_nodes = sorted(
        (
            node
            for node in ray.nodes()
            if node["Alive"] and WORKER_RESOURCE in node["Resources"]
        ),
        key=lambda node: node["NodeID"],
    )
    if len(worker_nodes) != N_BACKENDS:
        print(
            f"[serve_app] ERROR: expected {N_BACKENDS} alive worker nodes with "
            f"resource {WORKER_RESOURCE!r}, found {len(worker_nodes)}",
            flush=True,
        )
        return 1

    node_to_backend = {
        node["NodeID"]: {
            "index": i,
            "url": f"http://{args.sglang_host}:{args.sglang_base_port + i}",
        }
        for i, node in enumerate(worker_nodes)
    }
    print("[serve_app] node -> backend mapping:", flush=True)
    print(json.dumps(node_to_backend, indent=2), flush=True)

    # -- 2. Serve -------------------------------------------------------
    router_config = build_router_config(args.router_mode, args.fallback_threshold)
    print(
        f"[serve_app] router_mode={args.router_mode} "
        f"router_class={router_config.request_router_class} "
        f"router_kwargs={router_config.request_router_kwargs} "
        f"max_ongoing_requests={max_ongoing}",
        flush=True,
    )
    serve.start(
        detached=True,
        http_options={"host": "0.0.0.0", "port": args.serve_port},
    )
    deployment = serve.deployment(
        SGLangRouter,
        name="sglang-router",
        num_replicas=N_BACKENDS,
        max_ongoing_requests=max_ongoing,
        ray_actor_options={"num_cpus": 1},
        # One placement-group bundle per replica; each worker owns exactly
        # 1.0 unit of WORKER_RESOURCE, so replicas land on distinct workers.
        placement_group_bundles=[{"CPU": 1, WORKER_RESOURCE: 1}],
        request_router_config=router_config,
    )
    handle = serve.run(
        deployment.bind(node_to_backend),
        name="hw3-target3",
        route_prefix="/",
    )
    print(f"[serve_app] serving at http://127.0.0.1:{args.serve_port} "
          f"(handle={handle}); blocking until killed", flush=True)

    # -- 3. Block until killed (run_round.sh / stop_all.sh tear us down) --
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        print("[serve_app] shutting down", flush=True)
        try:
            cluster.shutdown()
        except Exception as exc:  # noqa: BLE001 - best effort teardown
            print(f"[serve_app] cluster shutdown raised: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
