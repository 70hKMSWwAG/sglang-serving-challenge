"""Ray Serve replica: a thin streaming forwarder to one SGLang backend.

Each replica lands on its own logical Ray worker node (via the
"replica_slot" custom resource) and forwards POST /generate verbatim to
exactly one SGLang server, streaming the SSE response back untouched and
stamping the three routing headers the workload generator requires.

The replica-to-backend mapping is derived from the replica's Ray node id:
worker nodes are sorted by node id and replica on worker i forwards to
backend i. The mapping is stable for the life of the cluster.
"""

import ray
from ray import serve
import httpx
from starlette.requests import Request
from starlette.responses import StreamingResponse

FORWARD_HEADERS = ("X-Session-Id", "X-Workload-Request-ID", "X-Prefix-Family")


def _backend_for_my_node(backend_urls, backend_ids) -> tuple:
    my_node = ray.get_runtime_context().get_node_id()
    worker_nodes = sorted(
        n["NodeID"]
        for n in ray.nodes()
        if n.get("Resources", {}).get("replica_slot", 0) >= 1
    )
    if my_node not in worker_nodes:
        raise RuntimeError(
            f"replica is on node {my_node} which is not a worker node; "
            "check the cluster setup"
        )
    idx = worker_nodes.index(my_node)
    if idx >= len(backend_urls):
        raise RuntimeError(
            f"node index {idx} out of range for {len(backend_urls)} backends"
        )
    return backend_urls[idx], backend_ids[idx]


class SGLangReplica:
    def __init__(self, backend_urls: list, backend_ids: list):
        self.backend_url, self.backend_id = _backend_for_my_node(backend_urls, backend_ids)
        self.backend_url = self.backend_url.rstrip("/")
        self.node_id = ray.get_runtime_context().get_node_id()
        self.replica_label = self.backend_id
        try:
            ctx = serve.get_replica_context()
            self.replica_label = f"{self.backend_id}@{ctx.replica_id}"
        except Exception:
            pass
        self._in_flight = 0
        # No client-side timeout: a streaming generation can be slow.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(None))

    async def __call__(self, request: Request) -> StreamingResponse:
        body = await request.body()
        headers = {"content-type": request.headers.get("content-type", "application/json")}
        for name in FORWARD_HEADERS:
            value = request.headers.get(name)
            if value:
                headers[name] = value

        upstream_request = self._client.build_request(
            "POST", f"{self.backend_url}/generate", content=body, headers=headers
        )
        try:
            upstream = await self._client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            return StreamingResponse(
                iter([f"replica cannot reach SGLang backend {self.backend_id}: {exc!r}\n"]),
                status_code=502,
                media_type="text/plain",
                headers=self._routing_headers(),
            )

        async def relay():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                self._in_flight -= 1

        self._in_flight += 1
        return StreamingResponse(
            relay(),
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "text/event-stream"),
            headers=self._routing_headers(),
        )

    def _routing_headers(self) -> dict:
        return {
            "X-Ray-Replica-ID": self.replica_label,
            "X-Ray-Node-ID": self.node_id,
            "X-SGLang-Backend": self.backend_id,
        }

    async def record_routing_stats(self) -> dict:
        """Polled by the controller; read by request routers as load signal.

        Must be async: Ray Serve calls this on the replica's asyncio loop, and
        a sync version blocks the loop while streaming traffic is in flight,
        which makes the proxy time out waiting for queue lengths.
        """
        return {"in_flight": self._in_flight}
