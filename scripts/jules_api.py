"""Minimal client for the Jules REST API (v1alpha).

Docs: https://jules.google/docs/api/  |  auth header: x-goog-api-key
Only the endpoints this pipeline needs, with retry/backoff on 429 and 5xx.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("JULES_API_BASE", "https://jules.googleapis.com/v1alpha")

TERMINAL_STATES = {"COMPLETED", "FAILED"}
STUCK_STATES = {"AWAITING_PLAN_APPROVAL", "AWAITING_USER_FEEDBACK", "PAUSED"}


class JulesError(RuntimeError):
    pass


class JulesClient:
    def __init__(self, api_key: str | None = None, timeout: int = 60):
        self.api_key = api_key or os.environ.get("JULES_API_KEY", "")
        if not self.api_key:
            raise JulesError("JULES_API_KEY is not set")
        self.timeout = timeout

    # ---------------------------------------------------------------- transport
    def _request(self, method: str, path: str, body: dict | None = None,
                 params: dict | None = None, retries: int = 5):
        url = f"{BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "x-goog-api-key": self.api_key,
            "Accept": "application/json",
            "User-Agent": "mormot2-monitor",
        }
        if data:
            headers["Content-Type"] = "application/json"

        for attempt in range(retries):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw.strip() else {}
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    wait = min(90, 5 * 2 ** attempt)
                    print(f"  jules {exc.code}, retry in {wait}s", flush=True)
                    time.sleep(wait)
                    continue
                raise JulesError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                if attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise JulesError(f"{method} {path} -> {exc}") from exc
        raise JulesError(f"{method} {path} -> exhausted retries")

    # ------------------------------------------------------------------ sources
    def list_sources(self) -> list[dict]:
        sources, token = [], None
        while True:
            params = {"pageSize": 100}
            if token:
                params["pageToken"] = token
            page = self._request("GET", "/sources", params=params)
            sources.extend(page.get("sources", []))
            token = page.get("nextPageToken")
            if not token:
                return sources

    def find_source(self, owner: str, repo: str) -> str:
        wanted = f"{owner}/{repo}".lower()
        for source in self.list_sources():
            gh = source.get("githubRepo") or {}
            name = f"{gh.get('owner', '')}/{gh.get('repo', '')}".lower()
            if name == wanted:
                return source["name"]
        raise JulesError(
            f"No Jules source for {owner}/{repo}. Install the Jules GitHub app on "
            f"that repository first (https://jules.google.com)."
        )

    # ----------------------------------------------------------------- sessions
    def create_session(self, prompt: str, source: str, branch: str = "main",
                       title: str | None = None, automation_mode: str = "AUTO_CREATE_PR",
                       require_plan_approval: bool = False) -> dict:
        body = {
            "prompt": prompt,
            "sourceContext": {
                "source": source,
                "githubRepoContext": {"startingBranch": branch},
            },
            "requirePlanApproval": require_plan_approval,
        }
        if title:
            body["title"] = title[:120]
        if automation_mode:
            body["automationMode"] = automation_mode
        return self._request("POST", "/sessions", body=body)

    def get_session(self, session_id: str) -> dict:
        return self._request("GET", f"/sessions/{session_id}")

    def approve_plan(self, session_id: str) -> dict:
        return self._request("POST", f"/sessions/{session_id}:approvePlan", body={})

    def send_message(self, session_id: str, prompt: str) -> dict:
        return self._request("POST", f"/sessions/{session_id}:sendMessage",
                             body={"prompt": prompt})

    def list_activities(self, session_id: str, page_size: int = 30) -> list[dict]:
        page = self._request("GET", f"/sessions/{session_id}/activities",
                             params={"pageSize": page_size})
        return page.get("activities", [])

    # ------------------------------------------------------------------ waiting
    def wait(self, session_id: str, timeout_s: int = 3600, poll_s: int = 20,
             auto_approve: bool = True, log=print) -> dict:
        """Poll until the session reaches a terminal state.

        Approves plans automatically (sessions created via the API normally
        auto-approve, this covers the case where they do not) and raises when
        Jules stalls waiting for human input.
        """
        deadline = time.time() + timeout_s
        last_state = None
        while time.time() < deadline:
            session = self.get_session(session_id)
            state = session.get("state", "STATE_UNSPECIFIED")
            if state != last_state:
                log(f"  session {session_id}: {state}")
                last_state = state
            if state in TERMINAL_STATES:
                return session
            if state == "AWAITING_PLAN_APPROVAL" and auto_approve:
                log("  approving plan")
                self.approve_plan(session_id)
            elif state in STUCK_STATES:
                for activity in self.list_activities(session_id, 5):
                    log(f"  last activity: {json.dumps(activity)[:400]}")
                raise JulesError(f"session stalled in {state}")
            time.sleep(poll_s)
        raise JulesError(f"session {session_id} timed out after {timeout_s}s "
                         f"(last state: {last_state})")


def pull_request_output(session: dict) -> dict | None:
    for output in session.get("outputs", []) or []:
        pr = output.get("pullRequest")
        if pr and pr.get("url"):
            return pr
    return None


if __name__ == "__main__":  # tiny CLI: python scripts/jules_api.py sources
    client = JulesClient()
    if len(sys.argv) > 1 and sys.argv[1] == "sources":
        for src in client.list_sources():
            print(src.get("name"))
    elif len(sys.argv) > 2 and sys.argv[1] == "session":
        print(json.dumps(client.get_session(sys.argv[2]), indent=2))
    else:
        print(__doc__)
