import httpx


class ChromaAdapter:
    def __init__(self, host: str, port: int) -> None:
        self._url = f"http://{host}:{port}/api/v2/heartbeat"

    def heartbeat(self) -> None:
        with httpx.Client(timeout=2.0, trust_env=False) as client:
            response = client.get(self._url)
            response.raise_for_status()
