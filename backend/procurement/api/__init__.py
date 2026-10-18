"""M3 HTTP API package.

A thin DRF adapter over :mod:`procurement.services`. Views resolve request
references, call exactly one service function and render the result; they never
re-implement business calculations, open their own transactions or reorder the
service layer's row locks.
"""
