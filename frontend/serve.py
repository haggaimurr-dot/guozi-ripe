import http.server, urllib.request, urllib.error

BACKEND = "http://127.0.0.1:8100"

class H(http.server.SimpleHTTPRequestHandler):
    def px(self):
        path = self.path
        if not (path.startswith("/api/") or path.startswith("/uploads/")):
            return False
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        ct = self.headers.get("Content-Type")
        hdrs = {}
        if self.headers.get("Authorization"):
            hdrs["Authorization"] = self.headers["Authorization"]
        if ct:
            hdrs["Content-Type"] = ct
        elif body is not None and self.command in ("POST", "PATCH", "PUT"):
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(BACKEND + path, data=body, method=self.command, headers=hdrs)
        try:
            r = urllib.request.urlopen(req)
            code, d, rct = r.status, r.read(), r.headers.get("Content-Type", "application/octet-stream")
        except urllib.error.HTTPError as e:
            code, d = e.code, e.read()
            rct = e.headers.get("Content-Type", "application/json") if e.headers else "application/json"
        self.send_response(code)
        self.send_header("Content-Type", rct)
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)
        return True

    def do_GET(self):
        if not self.px():
            super().do_GET()

    def do_POST(self):
        self.px()

    def do_PATCH(self):
        self.px()

    def do_DELETE(self):
        self.px()

http.server.ThreadingHTTPServer(("127.0.0.1", 8771), H).serve_forever()
