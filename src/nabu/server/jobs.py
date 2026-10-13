"""Background reading jobs with progress events (AD-13). M2.

Model calls block (nabu.model.client is synchronous, up to model_timeout_s per call). Jobs must
run them in a worker thread, never on the server's event loop, or one page would freeze the
review window.
"""
