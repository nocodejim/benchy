## Incident INC-2041: revoked API tokens keep working

Support escalated two reports about the REST API (`/api/tokens`):

1. After a user revokes their token with `DELETE /api/tokens`, requests using that token still succeed.
2. `POST /api/tokens` sometimes returns a token that has already expired, while a user with a
   perfectly valid token gets a brand-new one on every call.

Find and fix the root cause(s). Expected behaviour:
- A valid token with more than 60 seconds left is reused by `POST /api/tokens`.
- A token that is expired, about to expire, or revoked is never accepted and never handed out again.

Add a regression test for this to `tests.py` and make sure the whole test suite passes
(`.venv/bin/python -m unittest tests`).
