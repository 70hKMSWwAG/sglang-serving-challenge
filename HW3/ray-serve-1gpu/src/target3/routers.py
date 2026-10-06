"""Custom Ray Serve request router for HW3 target3, group D.

AffinityLoadAwareRouter: prefix-affinity first, load-aware fallback.

It subclasses Ray Serve's experimental ConsistentHashRouter (the same class
used for group C), so the affinity mechanism -- a consistent-hash ring over
the session id -- is inherited unchanged. On top of it we add one rule:

    primary = consistent_hash(session_id)            # prefix affinity
    if queue_len(primary) < fallback_inflight_threshold:
        route to primary                             # keep strict affinity
    else:
        route to the least-loaded candidate replica  # load-aware fallback

Signals used (the assignment requires the router to use only the current
request and the current service state -- never future requests):

  * current request : ``pending_request.metadata.session_id``, populated by the
    Ray Serve HTTP proxy from the ``X-Session-Id`` header. The course traffic
    generator sets ``X-Session-Id`` to the prefix-family id, so requests that
    share an SGLang radix-cache prefix hash to the same replica.
  * current service state : per-replica in-flight queue lengths, read from the
    router's local queue-length cache first and actively probed via
    ``RequestRouter._probe_queue_lens`` on a cache miss -- the same mechanism
    Ray Serve's own PowerOfTwoChoices router uses.

Every fallback decision is appended as one JSON line to the file named by the
``HW3_ROUTER_LOG`` environment variable (default
``/tmp/hw3_router_fallbacks.jsonl``), so ``run_round.sh`` can collect it into
the results directory for the report.

Reference: ray 2.56.0
``python/ray/serve/experimental/consistent_hash_router.py`` and
``python/ray/serve/_private/request_router/request_router.py``.
"""

import json
import logging
import os
import time

from typing import Dict, List, Optional

from ray.serve._private.constants import SERVE_LOGGER_NAME
from ray.serve._private.request_router.common import PendingRequest
from ray.serve._private.request_router.replica_wrapper import RunningReplica
from ray.serve.experimental.consistent_hash_router import ConsistentHashRouter

logger = logging.getLogger(SERVE_LOGGER_NAME)


class AffinityLoadAwareRouter(ConsistentHashRouter):
    """Consistent-hash prefix affinity with a load-aware fallback.

    Configure through ``RequestRouterConfig``::

        RequestRouterConfig(
            request_router_class=AffinityLoadAwareRouter,  # or "routers:AffinityLoadAwareRouter"
            request_router_kwargs={
                "num_virtual_nodes": 100,
                "num_fallback_replicas": 0,   # strict affinity at the ring level
                "fallback_inflight_threshold": 24,  # optional; default = 75% of max_ongoing_requests
            },
        )
    """

    def initialize_state(
        self,
        fallback_inflight_threshold: Optional[int] = None,
        **kwargs,
    ) -> None:
        # num_virtual_nodes / num_fallback_replicas are consumed here.
        super().initialize_state(**kwargs)
        self._fallback_inflight_threshold = fallback_inflight_threshold
        self._fallback_log_path = os.environ.get(
            "HW3_ROUTER_LOG", "/tmp/hw3_router_fallbacks.jsonl"
        )
        self._n_affinity = 0
        self._n_fallback = 0
        self._log_handle = None
        logger.info(
            "AffinityLoadAwareRouter initialized for %s: "
            "fallback_inflight_threshold=%r (None -> 75%% of max_ongoing_requests), "
            "fallback_log=%s",
            self._deployment_id,
            self._fallback_inflight_threshold,
            self._fallback_log_path,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _threshold_for(self, replica: RunningReplica) -> int:
        if self._fallback_inflight_threshold is not None:
            return int(self._fallback_inflight_threshold)
        max_ongoing = getattr(replica, "max_ongoing_requests", None) or 5
        return max(1, int(0.75 * max_ongoing))

    async def _current_queue_lens(
        self, candidates: List[RunningReplica]
    ) -> Dict:
        """Queue length per candidate replica id (current service state)."""
        queue_lens: Dict = {}
        missing: List[RunningReplica] = []
        use_cache = bool(getattr(self, "_use_replica_queue_len_cache", False))
        cache = getattr(self, "_replica_queue_len_cache", None)
        if use_cache and cache is not None:
            for replica in candidates:
                queued = cache.get(replica.replica_id)
                if queued is None:
                    missing.append(replica)
                else:
                    queue_lens[replica.replica_id] = queued
        else:
            missing = list(candidates)
        if missing:
            for replica, queued in await self._probe_queue_lens(missing, 0):
                if queued is not None:
                    queue_lens[replica.replica_id] = queued
        return queue_lens

    def _log_fallback(
        self,
        pending_request: Optional[PendingRequest],
        primary: RunningReplica,
        chosen: RunningReplica,
        primary_queue_len: Optional[int],
        chosen_queue_len: Optional[int],
    ) -> None:
        try:
            if self._log_handle is None:
                self._log_handle = open(self._fallback_log_path, "a", encoding="utf-8")
            session_id = ""
            if pending_request is not None and pending_request.metadata is not None:
                session_id = pending_request.metadata.session_id or ""
            self._log_handle.write(
                json.dumps(
                    {
                        "ts": time.time(),
                        "session_id": session_id,
                        "primary_replica": str(primary.replica_id),
                        "chosen_replica": str(chosen.replica_id),
                        "primary_queue_len": primary_queue_len,
                        "chosen_queue_len": chosen_queue_len,
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )
            self._log_handle.flush()
        except OSError as exc:
            logger.warning("AffinityLoadAwareRouter: cannot write fallback log: %s", exc)

    # ------------------------------------------------------------------
    # routing
    # ------------------------------------------------------------------
    async def choose_replicas(
        self,
        candidate_replicas: List[RunningReplica],
        pending_request: Optional[PendingRequest] = None,
    ) -> List[List[RunningReplica]]:
        # Ranked candidates from the consistent-hash ring: [[primary], ...].
        # With num_fallback_replicas=0 this is just [[primary]].
        ranks = await super().choose_replicas(
            candidate_replicas=candidate_replicas,
            pending_request=pending_request,
        )
        if not ranks or not ranks[0] or pending_request is None:
            return ranks

        primary = ranks[0][0]
        queue_lens = await self._current_queue_lens(candidate_replicas)
        primary_queue_len = queue_lens.get(primary.replica_id)
        threshold = self._threshold_for(primary)

        if primary_queue_len is None or primary_queue_len < threshold:
            # Affinity replica is healthy -> keep strict prefix affinity.
            self._n_affinity += 1
            return ranks

        # Affinity replica is hot -> fall back to the least-loaded replica.
        known = [
            (replica, queue_lens[replica.replica_id])
            for replica in candidate_replicas
            if replica.replica_id in queue_lens
        ]
        if not known:
            return ranks
        least_loaded = min(known, key=lambda item: item[1])[0]
        if least_loaded.replica_id == primary.replica_id:
            return ranks

        self._n_fallback += 1
        if (self._n_affinity + self._n_fallback) % 200 == 0:
            logger.info(
                "AffinityLoadAwareRouter stats for %s: affinity=%d fallback=%d",
                self._deployment_id,
                self._n_affinity,
                self._n_fallback,
            )
        self._log_fallback(
            pending_request,
            primary,
            least_loaded,
            primary_queue_len,
            queue_lens[least_loaded.replica_id],
        )
        # Prepend as rank 0 so the framework tries it before the affinity
        # replica (single-element ranks keep the strict ordering contract).
        return [[least_loaded]] + ranks
