"""Orchestrator: the only place the flow lives (AR-1, FRD Section 7). M1.

The model is reached only through nabu.model.client.ModelClient (build_client returns None in
no-model mode, FR-3.4). The egress guard is installed by every network entry point (the model
HTTP layer and the review server), so library callers are covered too.
"""
