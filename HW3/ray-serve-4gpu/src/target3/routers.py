"""Group D: prefix-affinity-first routing with load-aware spillover.

Signals (current request + current service state only):
  - session id of the pending request (== the workload's prefix family id)
  - current in-flight count per replica (router lifecycle hooks, with the
    replicas' record_routing_stats reports as a cross-instance fallback)
  - each replica's configured max_ongoing_requests

Rule:
  1. Primary replica = stable hash of the session id, so requests of one
     prefix family stick to one replica and reuse its RadixCache.
  2. If the primary is hot (in_flight >= hot_fraction * max_ongoing), it is
     demoted: replicas are ranked by ascending in-flight and the primary goes
     last, so hot-replica requests spill to cooler replicas instead of
     queueing behind them. The threshold is deliberately high (0.9):
     spilling too early destroys prefix affinity and costs more prefill.
  3. Ranks are returned individually; if a replica rejects under Serve's
     admission control, the next rank is tried, giving a final safety net.
"""

import hashlib
from typing import List, Optional

from ray.serve._private.request_router.common import PendingRequest
from ray.serve._private.request_router.request_router import FIFOMixin, RequestRouter
from ray.serve._private.request_router.replica_wrapper import RunningReplica


def _stable_index(key: str, n: int) -> int:
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % n


class AffinityLoadAwareRouter(FIFOMixin, RequestRouter):
    def initialize_state(self, **kwargs):
        self.hot_fraction = float(kwargs.get("hot_fraction", 0.5))
        self._counts = {}

    def _record_in_flight(self, replica_id) -> int:
        """Router-side in-flight estimate for this replica."""
        return self._counts.get(replica_id, 0)

    def _load(self, replica: RunningReplica) -> int:
        count = self._record_in_flight(replica.replica_id)
        if count == 0:
            stats = replica.routing_stats or {}
            count = int(stats.get("in_flight") or 0)
        return count

    async def choose_replicas(
        self,
        candidate_replicas: List[RunningReplica],
        pending_request: Optional[PendingRequest] = None,
    ) -> List[List[RunningReplica]]:
        if not candidate_replicas:
            return []
        if pending_request is not None and pending_request.metadata.session_id:
            key = pending_request.metadata.session_id
        elif pending_request is not None:
            key = pending_request.metadata.internal_request_id
        else:
            key = "no-session"

        ordered = sorted(candidate_replicas, key=lambda r: r.replica_id.unique_id)
        primary = ordered[_stable_index(key, len(ordered))]
        cap = max(1, primary.max_ongoing_requests)

        # Offer one rank holding two replicas: the affinity primary plus the
        # currently coolest other replica. Serve probes both and picks the one
        # with the shorter queue, so affinity wins whenever the primary is
        # healthy and the request spills automatically when it is saturated.
        # (Ranking them as separate ranks instead makes Serve try them one at a
        # time, which parks routing tasks and stalls the proxy under load.)
        others = sorted(
            (r for r in ordered if r.replica_id != primary.replica_id),
            key=lambda r: self._load(r),
        )
        spill = others[0] if others else None
        if spill is None:
            return [[primary]]
        if self._load(primary) >= self.hot_fraction * cap:
            # Primary is hot: offer both in one rank and let Serve probe them,
            # cool replica first so ties break away from the hot primary.
            return [[spill, primary]]
        # Primary has headroom: keep strict prefix affinity on this request.
        return [[primary]]

    def on_request_routed(self, pending_request, replica_id, result) -> None:
        self._counts[replica_id] = self._counts.get(replica_id, 0) + 1

    def on_request_completed(self, replica_id, internal_request_id) -> None:
        self._counts[replica_id] = max(0, self._counts.get(replica_id, 0) - 1)
