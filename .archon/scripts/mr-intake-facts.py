#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


MR_URL_RE = re.compile(r"(https?://[^/]+)/(.+?)/-/merge_requests/(\d+)(?:[/?#][^\s]*)?")
HUNK_RE = re.compile(r"^@@ ", re.MULTILINE)


def fail(message: str) -> int:
    print(f"mr-intake-facts: ERROR: {message}", file=sys.stderr)
    return 1


def parse_mr_url(raw: str) -> dict:
    match = MR_URL_RE.search(raw.strip())
    if not match:
        raise ValueError("expected GitLab MR URL like https://gitlab.example.com/group/project/-/merge_requests/123")
    base_url, project_path, iid = match.groups()
    return {
        "base_url": base_url.rstrip("/"),
        "project_path": urllib.parse.unquote(project_path),
        "project_id": urllib.parse.quote(urllib.parse.unquote(project_path), safe=""),
        "iid": int(iid),
        "web_url": f"{base_url.rstrip('/')}/{project_path}/-/merge_requests/{iid}",
    }


def first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def auth_token(base_url: str) -> str:
    return first_env("GITLAB_TOKEN", "GITLAB_PRIVATE_TOKEN", "GL_TOKEN", "PRIVATE_TOKEN")


def glab_json(base_url: str, path: str, query: dict | None = None, paginate: bool = False):
    host = urllib.parse.urlparse(base_url).hostname or ""
    endpoint = path.lstrip("/")
    if query:
        endpoint += "?" + urllib.parse.urlencode(query)
    args = ["glab", "api", "--hostname", host, endpoint]
    if paginate:
        args.extend(["--paginate", "--output", "json"])
    try:
        proc = subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("no GitLab token env vars set and glab is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"glab api timed out for {endpoint}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"glab api {endpoint} failed: {proc.stderr.strip()[:500]}")
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


def request_json(base_url: str, path: str, token: str, query: dict | None = None):
    url = f"{base_url}/api/v4{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"Accept": "application/json"}
    if token:
        headers["PRIVATE-TOKEN"] = token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body), resp.headers
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GET {url} failed: HTTP {exc.code}: {detail}") from exc


def request_pages(base_url: str, path: str, token: str, query: dict | None = None) -> list:
    query = dict(query or {})
    query.setdefault("per_page", 100)
    page = 1
    items = []
    while True:
        query["page"] = page
        data, headers = request_json(base_url, path, token, query)
        if not isinstance(data, list):
            raise RuntimeError(f"GET {path} returned non-list response")
        items.extend(data)
        next_page = headers.get("X-Next-Page", "").strip()
        if not next_page:
            break
        page = int(next_page)
    return items


def api_json(base_url: str, path: str, token: str, query: dict | None = None):
    if token:
        data, _ = request_json(base_url, path, token, query)
        return data
    return glab_json(base_url, path, query, paginate=False)


def api_pages(base_url: str, path: str, token: str, query: dict | None = None) -> list:
    if token:
        return request_pages(base_url, path, token, query)
    data = glab_json(base_url, path, query, paginate=True)
    if not isinstance(data, list):
        raise RuntimeError(f"glab api {path} returned non-list response")
    return data


def trim(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def count_diff(diff: str) -> tuple[int, int, int]:
    additions = deletions = 0
    for line in (diff or "").splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions, len(HUNK_RE.findall(diff or ""))


def path_parts(paths: list[str]) -> dict:
    top = {}
    extensions = {}
    for path in paths:
        parts = Path(path).parts
        root = parts[0] if parts else "."
        top[root] = top.get(root, 0) + 1
        suffix = Path(path).suffix.lower() or "[none]"
        extensions[suffix] = extensions.get(suffix, 0) + 1
    return {
        "top_level_dirs": dict(sorted(top.items(), key=lambda item: (-item[1], item[0]))),
        "extensions": dict(sorted(extensions.items(), key=lambda item: (-item[1], item[0]))),
    }


def status_for(diff: dict) -> str:
    if diff.get("new_file"):
        return "added"
    if diff.get("deleted_file"):
        return "deleted"
    if diff.get("renamed_file"):
        return "renamed"
    return "modified"


def compact_diff_item(item: dict) -> dict:
    old_path = item.get("old_path") or ""
    new_path = item.get("new_path") or old_path
    additions, deletions, hunks = count_diff(item.get("diff") or "")
    out = {
        "path": new_path,
        "old_path": old_path if old_path != new_path else None,
        "status": status_for(item),
        "additions": additions,
        "deletions": deletions,
        "hunks": hunks,
        "extension": Path(new_path).suffix.lower() or "[none]",
        "collapsed": bool(item.get("collapsed")),
        "too_large": bool(item.get("too_large")),
        "generated_file": bool(item.get("generated_file")),
    }
    return {key: value for key, value in out.items() if value is not None}


def build_facts(target: dict, mr: dict, diffs: list[dict], commits: list[dict]) -> dict:
    files = [compact_diff_item(item) for item in diffs]
    paths = [item["path"] for item in files]
    additions = sum(item["additions"] for item in files)
    deletions = sum(item["deletions"] for item in files)
    hunks = sum(item["hunks"] for item in files)
    status_counts = {}
    for item in files:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    path_summary = path_parts(paths)

    description = mr.get("description") or ""
    include_description = os.environ.get("MR_INTAKE_INCLUDE_DESCRIPTION", "").lower() in {"1", "true", "yes", "on"}
    return {
        "schema_version": 1,
        "target": {
            "url": target["web_url"],
            "host": target["base_url"],
            "project_path": target["project_path"],
            "project_id": mr.get("project_id"),
            "iid": mr.get("iid"),
        },
        "mr": {
            "title": mr.get("title") or "",
            "description_excerpt": trim(description, 300) if include_description else "",
            "description_chars": len(description),
            "state": mr.get("state"),
            "draft": bool(mr.get("draft") or mr.get("work_in_progress")),
            "labels": mr.get("labels") or [],
            "source_branch": mr.get("source_branch"),
            "target_branch": mr.get("target_branch"),
            "author_username": (mr.get("author") or {}).get("username"),
            "created_at": mr.get("created_at"),
            "updated_at": mr.get("updated_at"),
            "web_url": mr.get("web_url") or target["web_url"],
        },
        "diff_refs": mr.get("diff_refs") or {},
        "stats": {
            "files": len(files),
            "additions": additions,
            "deletions": deletions,
            "changed_lines": additions + deletions,
            "hunks": hunks,
            "commits": len(commits),
            "status_counts": dict(sorted(status_counts.items())),
            **path_summary,
        },
        "files": sorted(files, key=lambda item: item["path"]),
        "limits": {
            "diff_files_returned": len(diffs),
            "has_collapsed_files": any(item.get("collapsed") for item in files),
            "has_too_large_files": any(item.get("too_large") for item in files),
            "has_generated_files": any(item.get("generated_file") for item in files),
        },
        "collection": {
            "source": "gitlab_api",
            "api_calls": [
                "GET /projects/:id/merge_requests/:merge_request_iid",
                "GET /projects/:id/merge_requests/:merge_request_iid/diffs",
                "GET /projects/:id/merge_requests/:merge_request_iid/commits",
            ],
            "notes": [
                "Facts are mechanical only. Semantic classification belongs to the LLM node.",
                "Diff text is parsed for counts only and is not copied into this artifact.",
            ],
        },
    }


def main() -> int:
    raw_target = " ".join(sys.argv[1:]).strip() or os.environ.get("ARGUMENTS", "").strip()
    if not raw_target:
        return fail("missing MR URL argument")
    try:
        target = parse_mr_url(raw_target)
    except ValueError as exc:
        return fail(str(exc))

    artifacts = Path(os.environ.get("ARTIFACTS_DIR", ".archon/artifacts"))
    out_dir = artifacts / "mr-intake"
    out_dir.mkdir(parents=True, exist_ok=True)

    token = auth_token(target["base_url"])
    try:
        mr = api_json(
            target["base_url"],
            f"/projects/{target['project_id']}/merge_requests/{target['iid']}",
            token,
            {"with_labels_details": "false"},
        )
        diffs = api_pages(
            target["base_url"],
            f"/projects/{target['project_id']}/merge_requests/{target['iid']}/diffs",
            token,
            {"unidiff": "true"},
        )
        commits = api_pages(
            target["base_url"],
            f"/projects/{target['project_id']}/merge_requests/{target['iid']}/commits",
            token,
            {},
        )
    except Exception as exc:
        return fail(str(exc))

    facts = build_facts(target, mr, diffs, commits)
    out_path = out_dir / "facts.json"
    out_path.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "MR facts: "
        f"{facts['stats']['files']} files, "
        f"+{facts['stats']['additions']}/-{facts['stats']['deletions']}, "
        f"{facts['stats']['hunks']} hunks, "
        f"{facts['stats']['commits']} commits"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
