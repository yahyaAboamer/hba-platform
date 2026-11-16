"""Production orders, as platform screens (ADR 0084, batch 1).

The old framed Production (its API, services, screens and tables) is gone
(ADR 0085); only its suppliers remain (``app.modules.production.models``).
Tables are prefixed ``prod_``; the API is under ``/api/prod``.
"""
