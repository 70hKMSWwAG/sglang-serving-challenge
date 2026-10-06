#!/usr/bin/env bash
# Kill all sglang.launch_server processes and shut down the logical Ray cluster.
pkill -f "sglang.launch_server" 2>/dev/null && echo "sglang backends stopped" || echo "no sglang backends running"
ray stop --force 2>/dev/null && echo "ray stopped" || true
