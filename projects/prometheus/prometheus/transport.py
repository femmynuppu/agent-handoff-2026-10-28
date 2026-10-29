"""Bounded, same-origin loopback A2A JSON-RPC transport; never generates locally."""
from __future__ import annotations
import hashlib
import http.client
import threading
import math
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

class BridgeError(Exception):
    def __init__(self, code, message, *, ambiguous=False):
        super().__init__(message)
        self.code, self.ambiguous = code, ambiguous

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BridgeError("REDIRECT_REFUSED", "Redirect refused; credentials were not forwarded")

def origin(url):
    if not isinstance(url, str):
        raise BridgeError("UNSAFE_ENDPOINT", "Endpoint must be a string")
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        raise BridgeError("UNSAFE_ENDPOINT", "Malformed endpoint") from None
    if p.scheme != "http" or p.username or p.password or p.fragment or p.query:
        raise BridgeError("UNSAFE_ENDPOINT", "Only credential-free loopback HTTP URLs are accepted")
    try:
        address = ipaddress.ip_address(p.hostname or "")
    except ValueError:
        raise BridgeError("UNSAFE_ENDPOINT", "Use a literal loopback IP, not DNS") from None
    if not address.is_loopback:
        raise BridgeError("UNSAFE_ENDPOINT", "Endpoint is not loopback")
    try:
        port = p.port or 80
    except ValueError:
        raise BridgeError("UNSAFE_ENDPOINT", "Invalid endpoint port") from None
    return p.scheme, str(address), port

class A2AClient:
    """Read operations retry; mutating/ambiguous operations NEVER replay automatically."""
    def __init__(self, endpoint, token, *, timeout=30, response_cap=2_000_000,
                 payload_cap=500_000, retries=2, audit=None, fixture=False):
        self.origin = origin(endpoint)
        self.endpoint = endpoint.rstrip("/") + "/"
        if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
            raise BridgeError("AUTH_REQUIRED", "Nonempty bearer token required")
        if isinstance(timeout, bool) or not isinstance(timeout, (int,float)) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ValueError("Invalid deadline")
        for value, minimum, maximum in ((response_cap,1,16_000_000),(payload_cap,1,4_000_000),(retries,0,5)):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError("Invalid cap/retry bound")
        self.token, self.timeout, self.response_cap = token, timeout, response_cap
        self.payload_cap, self.retries = payload_cap, retries
        self.audit, self.fixture = audit, fixture
        self.tenant = None
        self.contexts = {}
        self.card = None
        self.methods = {}

    def _event(self, event, **data):
        if self.audit:
            self.audit(event, fixture=self.fixture, **data)

    def _request(self, url, body=None, *, safe=False, deadline=None):
        if origin(url) != self.origin:
            raise BridgeError("FOREIGN_ORIGIN", "Foreign endpoint refused")
        deadline = deadline if deadline is not None else time.monotonic() + self.timeout
        encoded = None if body is None else json.dumps(body, separators=(",", ":"), allow_nan=False).encode()
        if encoded is not None and len(encoded) > self.payload_cap:
            raise BridgeError("PAYLOAD_LIMIT", "Request exceeds payload cap")
        for attempt in range(self.retries + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeError("DEADLINE", "Operation deadline exhausted")
            p = urllib.parse.urlsplit(url)
            connection = http.client.HTTPConnection(p.hostname, p.port or 80, timeout=remaining)
            expired = threading.Event()
            active_socket = [None]
            def interrupt():
                expired.set()
                sock = active_socket[0] or connection.sock
                if sock is not None:
                    try: sock.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                connection.close()
            timer = threading.Timer(remaining, interrupt)
            timer.daemon = True
            started = time.monotonic()
            timer.start()
            try:
                connection.request("GET" if body is None else "POST", p.path or "/", body=encoded, headers={
                    "Authorization":"Bearer "+self.token,"Content-Type":"application/json","Accept":"application/json"})
                active_socket[0] = connection.sock
                response = connection.getresponse()
                if 300 <= response.status < 400:
                    raise BridgeError("REDIRECT_REFUSED", "Redirect refused")
                if response.status >= 400:
                    raise urllib.error.HTTPError(url,response.status,"HTTP request failed",{},None)
                raw = response.read(self.response_cap + 1)
                if expired.is_set() or time.monotonic() > deadline:
                    raise BridgeError("DEADLINE", "Response exceeded deadline", ambiguous=not safe)
                if len(raw) > self.response_cap:
                    raise BridgeError("RESPONSE_LIMIT", "Response exceeds cap", ambiguous=not safe)
                def invalid_constant(value):
                    raise ValueError("Nonfinite JSON constant")
                result = json.loads(raw, parse_constant=invalid_constant)
                if not isinstance(result, dict):
                    raise BridgeError("INVALID_RESPONSE", "Expected JSON object", ambiguous=not safe)
                self._event("http_result", method="GET" if body is None else body.get("method"),
                            response_sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                            elapsed=time.monotonic()-started)
                return result
            except urllib.error.HTTPError as exc:
                error = BridgeError("HTTP_"+str(exc.code), "HTTP request failed", ambiguous=not safe)
                retry = safe and exc.code in (429, 502, 503, 504)
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError, http.client.HTTPException):
                error = BridgeError("DEADLINE" if expired.is_set() else "TRANSPORT", "Connection failed or timed out", ambiguous=not safe)
                retry = safe and not expired.is_set()
            except (ValueError, UnicodeDecodeError):
                raise BridgeError("INVALID_RESPONSE", "Invalid JSON response", ambiguous=not safe) from None
            finally:
                timer.cancel()
                connection.close()
            if not retry or attempt >= self.retries:
                self._event("http_failure", code=error.code, ambiguous=error.ambiguous)
                raise error
            pause = min(0.25 * 2**attempt, max(0, deadline-time.monotonic()))
            time.sleep(pause)
        raise AssertionError("unreachable retry state")

    def discover(self):
        deadline = time.monotonic() + self.timeout
        url = urllib.parse.urljoin(self.endpoint, "/.well-known/agent-card.json")
        try:
            card = self._request(url, safe=True, deadline=deadline)
        except BridgeError as exc:
            if exc.code != "HTTP_404":
                raise
            card = self._request(urllib.parse.urljoin(self.endpoint, "/.well-known/agent.json"),
                                 safe=True, deadline=deadline)
        target = card.get("url")
        interfaces = card.get("supportedInterfaces", [])
        if not isinstance(interfaces,list) or any(not isinstance(i,dict) for i in interfaces):
            raise BridgeError("CARD_INCOMPATIBLE", "Malformed supportedInterfaces")
        chosen = None
        for interface in interfaces:
            binding = interface.get("protocolBinding", "")
            if not isinstance(binding,str):
                raise BridgeError("CARD_INCOMPATIBLE", "Malformed protocol binding")
            if binding.upper() in ("JSONRPC", "JSON-RPC"):
                chosen = interface; target = interface.get("url") or target; break
        if interfaces and chosen is None:
            raise BridgeError("CARD_INCOMPATIBLE", "No JSON-RPC interface")
        if not target:
            raise BridgeError("CARD_INCOMPATIBLE", "Agent Card has no JSON-RPC URL")
        if origin(target) != self.origin:
            raise BridgeError("FOREIGN_ORIGIN", "Agent Card advertises foreign endpoint")
        version = (chosen or card).get("protocolVersion", "")
        if not isinstance(version,str) or version not in ("1.0","1.0.0","0.3.0","0.2.0"):
            raise BridgeError("CARD_INCOMPATIBLE", "Unsupported or missing A2A protocol version")
        self.tenant = chosen.get("tenant") if chosen else None
        if self.tenant is not None and not isinstance(self.tenant,str):
            raise BridgeError("CARD_INCOMPATIBLE", "Malformed tenant")
        schemes, requirements = card.get("securitySchemes",{}), card.get("security",[])
        if not isinstance(schemes,dict) or not isinstance(requirements,list) or any(not isinstance(r,dict) for r in requirements):
            raise BridgeError("CARD_AUTH_INCOMPATIBLE", "Malformed security requirements")
        if requirements and not any(not r or all(isinstance(schemes.get(k),dict) and schemes[k].get("type")=="http" and str(schemes[k].get("scheme","")).lower()=="bearer" and scopes==[] for k,scopes in r.items()) for r in requirements):
            raise BridgeError("CARD_AUTH_INCOMPATIBLE", "No supported bearer authentication alternative")
        modern = version.startswith("1.")
        self.methods = {"send": "SendMessage" if modern else "message/send",
                        "get": "GetTask" if modern else "tasks/get",
                        "cancel": "CancelTask" if modern else "tasks/cancel"}
        self.endpoint, self.card = target, card
        self._event("agent_card", protocol=version, card_sha256=hashlib.sha256(json.dumps(card,sort_keys=True).encode()).hexdigest())
        return card

    def rpc(self, method, params, *, safe=False, deadline=None):
        request_id = uuid.uuid4().hex
        params = dict(params)
        if self.tenant is not None:
            params["tenant"] = self.tenant
        reply = self._request(self.endpoint, {"jsonrpc":"2.0", "id":request_id,
                              "method":method,"params":params}, safe=safe, deadline=deadline)
        if reply.get("jsonrpc") != "2.0" or reply.get("id") != request_id:
            raise BridgeError("INVALID_RESPONSE", "JSON-RPC envelope mismatch", ambiguous=not safe)
        if "error" in reply:
            code = reply["error"].get("code") if isinstance(reply["error"],dict) else None
            raise BridgeError("METHOD_UNSUPPORTED" if code == -32601 else "RPC_ERROR", "A2A RPC error: "+str(code))
        if "result" not in reply or not isinstance(reply["result"],dict):
            raise BridgeError("INVALID_RESPONSE", "Missing object result", ambiguous=not safe)
        return reply["result"]

    def _ready(self):
        if self.card is None:
            self.discover()

    def submit(self, text, *, context_id=None):
        self._ready()
        modern = self.methods["send"] == "SendMessage"
        message = {"messageId":uuid.uuid4().hex, "role":"ROLE_USER" if modern else "user",
                   "parts":[{"text":text} if modern else {"kind":"text","text":text}]}
        if context_id:
            message["contextId"] = context_id
        result = self.rpc(self.methods["send"], {"message":message})
        task = result.get("task", result)
        if not isinstance(task,dict):raise BridgeError('INVALID_RESPONSE','Malformed task',ambiguous=True)
        returned = task.get("contextId")
        if not isinstance(returned,str) or not returned or (context_id and returned != context_id):
            raise BridgeError("CONTEXT_MISMATCH", "Missing or changed context ID", ambiguous=True)
        task_id = task.get("id")
        if task_id:
            self.contexts[task_id] = returned
        return result

    def get(self, task_id, *, deadline=None):
        self._ready()
        result = self.rpc(self.methods["get"], {"id":task_id,"historyLength":100}, safe=True, deadline=deadline)
        task = result.get("task",result)
        if not isinstance(task,dict):raise BridgeError('INVALID_RESPONSE','Malformed task')
        if task.get("id") != task_id or (task_id in self.contexts and task.get("contextId") != self.contexts[task_id]):
            raise BridgeError("CONTEXT_MISMATCH", "Task/context ID mismatch")
        return result

    def cancel(self, task_id):
        self._ready()
        return self.rpc(self.methods["cancel"], {"id":task_id})

    def poll(self, task_id, *, interval=0.5):
        deadline = time.monotonic() + self.timeout
        terminal = {"completed","failed","canceled","cancelled","rejected","input-required","auth-required"}
        while True:
            result = self.get(task_id, deadline=deadline)
            task = result.get("task", result)
            status=task.get('status')
            if not isinstance(status,dict):raise BridgeError('INVALID_RESPONSE','Malformed task status')
            state = str(status.get("state", "")).lower().removeprefix("task_state_").replace("_","-")
            if state in terminal:
                return result
            if state not in {"submitted","working"}:
                raise BridgeError("TASK_STATE_INCOMPATIBLE", "Unknown task state")
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise BridgeError("DEADLINE", "Polling deadline exhausted")
            time.sleep(min(interval,remaining))

    @staticmethod
    def extract(result):
        task = result.get("task",result)
        if not isinstance(task,dict):raise BridgeError('INVALID_RESPONSE','Malformed task')
        status = task.get("status",{})
        if not isinstance(status,dict):raise BridgeError('INVALID_RESPONSE','Malformed task status')
        state = str(status.get("state","")).lower().removeprefix("task_state_").replace("_","-")
        parts = []
        artifacts=task.get('artifacts',[])
        if not isinstance(artifacts,list):raise BridgeError('INVALID_RESPONSE','Malformed artifacts')
        for artifact in artifacts:
            if not isinstance(artifact,dict) or not isinstance(artifact.get('parts',[]),list):raise BridgeError('INVALID_RESPONSE','Malformed artifact')
            parts.extend(artifact.get("parts",[]))
        if not parts and isinstance(status.get("message"),dict):
            parts = status["message"].get("parts",[])
        text = "\n".join(p["text"] for p in parts if isinstance(p,dict) and isinstance(p.get("text"),str))
        return {"task_id":task.get("id"),"context_id":task.get("contextId"),"state":state,
                "success":state=="completed","text":text,"raw":result}

    def wait_or_cancel(self, task_id):
        try:
            return self.extract(self.poll(task_id))
        except BridgeError as exc:
            if exc.code != "DEADLINE": raise
            try:
                cancelled = self.cancel(task_id)
                self._event("deadline_cancel", task_id=task_id, result=cancelled)
            except BridgeError as cancel_error:
                self._event("deadline_cancel_failed", task_id=task_id, code=cancel_error.code)
            raise
