"""Serving fixture pages, and recording what is done on them.

A task that drives a web page is given one served over a local HTTP origin,
from a copy outside the checkout. Not ``file://``: the address bar is part of
the screen, and a path under the repository tells the room where the source it
may not read is. Safari also refuses a ``file://`` page under the temp
directory outright. An HTTP origin says nothing but a port number, which is
what the applications these tasks really drive look like.

A page reports what was done on it - an approval, a submission - by POSTing a
JSON object to ``event``. That list is the screen's own record of the run, and
it is what a report cites, rather than the room's account.
"""

from __future__ import annotations

import functools
import json
import pathlib
import shutil
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class Pages:
    """Fixture pages served for the length of a ``with`` block.

    Attributes:
        origin: ``http://127.0.0.1:<port>``.
        events: What the pages reported, in order.
    """

    def __init__(self, fixtures: pathlib.Path):
        self.fixtures = pathlib.Path(fixtures)
        self.events: list[dict] = []
        self.origin = ""
        self._lock = threading.Lock()
        self._server = None
        self._served = None

    def url(self, page: str) -> str:
        return f"{self.origin}/{page}"

    def __enter__(self) -> "Pages":
        self._served = pathlib.Path(tempfile.mkdtemp(prefix="quality-loop-pages-"))
        shutil.copytree(self.fixtures, self._served, dirs_exist_ok=True)
        pages = self

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args, **kwargs):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    event = json.loads(self.rfile.read(length).decode("utf-8"))
                except ValueError:
                    event = None
                if isinstance(event, dict):
                    with pages._lock:
                        pages.events.append(event)
                self.send_response(204)
                self.end_headers()

        self._server = ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Handler, directory=str(self._served)))
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.origin = f"http://127.0.0.1:{self._server.server_port}"
        return self

    def __exit__(self, *exc) -> bool:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._served is not None:
            shutil.rmtree(self._served, ignore_errors=True)
        return False

    def write(self, path: pathlib.Path) -> None:
        """The events as JSON lines - the screen's record, for the evidence."""
        with self._lock:
            path.write_text("".join(json.dumps(e) + "\n" for e in self.events),
                            encoding="utf-8")
