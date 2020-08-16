import json


class Response:
    """
    {
        "ok": <True if OK, False otherwise>,
        "detail": <source name or error detail>
    }
    """
    def __init__(self, ok, detail=''):
        self.ok: bool = ok
        self.detail: str = detail

    def to_payload(self) -> bytes:
        """Returns bytes for sending over TCP"""
        data = dict(ok=self.ok, detail=self.detail)
        return json.dumps(data).encode('utf-8')
