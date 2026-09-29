from __future__ import annotations

import json


def parse_json(body: bytes):
    return json.loads(body.decode("utf-8"))
