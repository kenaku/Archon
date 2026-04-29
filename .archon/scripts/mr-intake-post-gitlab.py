#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


MARKER = "<!-- archon-mr-intake-classifier -->"


def fail(message: str) -> int:
    print(f"mr-intake-post: ERROR: {message}", file=sys.stderr)
    return 1


def should_post(raw_args: str) -> bool:
    lowered = raw_args.lower()
    if any(flag in lowered for flag in ["no-gitlab-comments", "no-gitlab-comment", "no-post", "--dry-run"]):
        return False
    env = os.environ.get("POST_GITLAB_COMMENT", "").strip().lower()
    if env in {"0", "false", "no", "off"}:
        return False
    return True


def first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def auth_token() -> str:
    return first_env("GITLAB_TOKEN", "GITLAB_PRIVATE_TOKEN", "GL_TOKEN", "PRIVATE_TOKEN")


def run_glab(base_url: str, endpoint: str, method: str = "GET", fields: dict | None = None, paginate: bool = False):
    host = urllib.parse.urlparse(base_url).hostname or ""
    args = ["glab", "api", "--hostname", host, endpoint]
    if method != "GET":
        args.extend(["--method", method])
    if paginate:
        args.extend(["--paginate", "--output", "json"])
    for key, value in (fields or {}).items():
        args.extend(["--raw-field", f"{key}={value}"])
    proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"glab api {method} {endpoint} failed: {proc.stderr.strip()[:500]}")
    text = proc.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if not paginate:
            raise
        decoder = json.JSONDecoder()
        pos = 0
        merged = []
        while pos < len(text):
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if pos >= len(text):
                break
            value, pos = decoder.raw_decode(text, pos)
            if isinstance(value, list):
                merged.extend(value)
            else:
                merged.append(value)
        return merged


def request_json(
    base_url: str,
    endpoint: str,
    token: str,
    method: str = "GET",
    fields: dict | None = None,
):
    url = f"{base_url.rstrip('/')}/api/v4/{endpoint.lstrip('/')}"
    headers = {
        "Accept": "application/json",
        "PRIVATE-TOKEN": token,
    }
    data = None
    if fields is not None:
        data = urllib.parse.urlencode(fields).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            if not body:
                return None, resp.headers
            return json.loads(body), resp.headers
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GitLab API {method} {url} failed: HTTP {exc.code}: {detail}") from exc


def request_pages(base_url: str, endpoint: str, token: str) -> list:
    sep = "&" if "?" in endpoint else "?"
    page_endpoint = f"{endpoint}{sep}per_page=100"
    page = 1
    items = []
    while True:
        current = f"{page_endpoint}&page={page}"
        data, headers = request_json(base_url, current, token)
        if not isinstance(data, list):
            raise RuntimeError(f"GitLab API {current} returned non-list response")
        items.extend(data)
        next_page = headers.get("X-Next-Page", "").strip()
        if not next_page:
            break
        page = int(next_page)
    return items


def api_json(
    base_url: str,
    endpoint: str,
    token: str,
    method: str = "GET",
    fields: dict | None = None,
    paginate: bool = False,
):
    if token:
        if paginate:
            return request_pages(base_url, endpoint, token)
        data, _ = request_json(base_url, endpoint, token, method, fields)
        return data
    return run_glab(base_url, endpoint, method=method, fields=fields, paginate=paginate)


def intake_labels(classification: dict) -> list[str]:
    size = classification.get("size_class")
    risk = classification.get("risk")
    complexity = classification.get("complexity")
    if not complexity:
        size_class = classification.get("size_class")
        if size_class in {"empty", "trivial", "small"}:
            complexity = "simple"
        elif size_class in {"large", "huge"}:
            complexity = "broad"
        else:
            complexity = "standard"
    labels = []
    if size:
        labels.append(f"size::{size}")
    if complexity:
        labels.append(f"complexity::{complexity}")
    if risk:
        labels.append(f"risk::{risk}")
    return labels


def scoped_labels(existing_labels: list, scopes: set[str]) -> list[str]:
    result = []
    for label in existing_labels or []:
        name = label.get("name") if isinstance(label, dict) else str(label)
        if "::" not in name:
            continue
        scope = name.split("::", 1)[0]
        if scope in scopes:
            result.append(name)
    return result


def main() -> int:
    raw_args = " ".join(sys.argv[1:]) or os.environ.get("ARGUMENTS", "")
    artifacts = Path(os.environ.get("ARTIFACTS_DIR", ".archon/artifacts"))
    review = artifacts / "mr-intake"
    facts_path = review / "facts.json"
    summary_path = review / "summary.md"
    classification_path = review / "classification.json"
    if not facts_path.exists():
        return fail(f"missing {facts_path}")
    if not summary_path.exists():
        return fail(f"missing {summary_path}")
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    classification = json.loads(classification_path.read_text(encoding="utf-8")) if classification_path.exists() else {}
    target = facts.get("target") or {}
    base_url = target.get("host")
    project = target.get("project_path")
    iid = target.get("iid")
    if not base_url or not project or not iid:
        return fail("facts.json target must include host, project_path, and iid")
    project_id = urllib.parse.quote(project, safe="")

    body = summary_path.read_text(encoding="utf-8").strip()
    body = f"{MARKER}\n{body}\n"

    if not should_post(raw_args):
        print("GitLab comment: skipped")
        return 0

    token = auth_token()
    notes_endpoint = f"projects/{project_id}/merge_requests/{iid}/notes"
    notes = api_json(base_url, notes_endpoint, token, paginate=True) or []
    existing = next((note for note in notes if MARKER in str(note.get("body", ""))), None)
    if existing:
        note_id = existing.get("id")
        api_json(base_url, f"{notes_endpoint}/{note_id}", token, method="PUT", fields={"body": body})
        action = "updated"
    else:
        api_json(base_url, notes_endpoint, token, method="POST", fields={"body": body})
        action = "created"

    labels = intake_labels(classification)
    label_fields = {}
    if labels:
        mr = api_json(
            base_url,
            f"projects/{project_id}/merge_requests/{iid}?with_labels_details=false",
            token,
        ) or {}
        remove_labels = [label for label in scoped_labels(mr.get("labels") or [], {"size", "complexity", "risk"}) if label not in labels]
        label_fields["add_labels"] = ",".join(labels)
        if remove_labels:
            label_fields["remove_labels"] = ",".join(remove_labels)
        api_json(
            base_url,
            f"projects/{project_id}/merge_requests/{iid}",
            token,
            method="PUT",
            fields=label_fields,
        )
    label_text = ",".join(labels) if labels else "none"
    print(f"GitLab comment: {action}; labels set: {label_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
