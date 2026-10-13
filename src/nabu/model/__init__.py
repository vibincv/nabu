"""Model layer (FR-10). Pluggable on two axes:

- runtime: how Nabu talks to the local model server (`runtime.py`: Ollama, OpenAI-compatible)
- profile: what differs between model families, kept as data (`profiles.py`)

The pipeline uses only `client.ModelClient`. Everything here talks to loopback only (AR-3).
"""
