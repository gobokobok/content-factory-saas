"""The shape of a run id in a request body (F9).

A run id reaches R2 keys and a local ``/tmp/{run_id}`` working path in the render, so a
body value is limited to what real ids use: a uuid, or the legacy ``{date}_{slug}`` form
(letters, digits, ``-`` and ``_``). Anything with a slash or dots is rejected with a 422.
"""

RUN_ID_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"
