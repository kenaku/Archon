#!/usr/bin/env python3
import os
import re
import shlex
import json
import subprocess
from pathlib import Path

PROJECT_FULL_PATH = "adapty/adapty-dashboard-interface"
PROJECT_NAME = "adapty-dashboard-interface"
DEFAULT_TARGET_BRANCH = "master"


def run(args, check=True):
    p = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{p.stderr.strip()}")
    return p.stdout.strip()


def shell_value(value):
    return shlex.quote(str(value))


def write_block(review, message):
    review.mkdir(parents=True, exist_ok=True)
    (review / "target.json").write_text(json.dumps({"schema_version": 1, "status": "blocked", "message": message.rstrip()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(message.splitlines()[0] if message else "Target resolution blocked.")


def parse_target(arguments):
    match = re.search(r"https?://([^/]+)/(.+?)/-/merge_requests/(\d+)(?:\b|[/#?])", arguments)
    if not match:
        return None
    host, project, iid = match.groups()
    return {"host": host, "project": project, "iid": iid, "url": match.group(0).rstrip("/)}]>,.")}


def origin_matches_project(origin_url, host, project):
    compact = origin_url.removesuffix(".git")
    return host in compact and compact.endswith(project)


def main():
    artifacts = Path(os.environ.get("ARTIFACTS_DIR", ".artifacts"))
    review = artifacts / "review"
    review.mkdir(parents=True, exist_ok=True)
    arguments = os.environ.get("ARGUMENTS", "")
    parsed = parse_target(arguments)
    if not parsed:
        write_block(review, "Target resolution blocked. Provide a full GitLab MR URL like https://gitlab.adapty.io/adapty/adapty-dashboard-interface/-/merge_requests/<iid>.")
        return 2
    if parsed["project"] != PROJECT_FULL_PATH:
        write_block(review, f"Target resolution blocked. Unsupported project {parsed['project']}; expected {PROJECT_FULL_PATH}.")
        return 2

    origin = run(["git", "remote", "get-url", "origin"])
    if not origin_matches_project(origin, parsed["host"], parsed["project"]):
        write_block(review, f"Target resolution blocked. origin remote does not match {parsed['project']}: {origin}")
        return 2

    iid = parsed["iid"]
    head_ref = f"mr/{iid}"
    post_comments = "no" if re.search(r"\b(no-gitlab-comments|dry-run|draft-only)\b", arguments, re.I) else "yes"

    run(["git", "fetch", "origin", f"{DEFAULT_TARGET_BRANCH}:refs/remotes/origin/{DEFAULT_TARGET_BRANCH}"])
    run(["git", "fetch", "origin", f"+merge-requests/{iid}/head:refs/heads/{head_ref}"])
    base_ref = f"origin/{DEFAULT_TARGET_BRANCH}"
    base_sha = run(["git", "merge-base", base_ref, head_ref])
    head_sha = run(["git", "rev-parse", head_ref])
    run(["git", "switch", "--detach", head_ref])

    values = {
        "TARGET_KIND": "mr",
        "TARGET_URL": parsed["url"],
        "GITLAB_HOST": parsed["host"],
        "PROJECT_FULL_PATH": parsed["project"],
        "TARGET_LABEL": f"MR !{iid} in {PROJECT_NAME}",
        "BASE_REF": base_sha,
        "HEAD_REF": head_ref,
        "MR_IID": iid,
        "MR_TARGET_BRANCH": DEFAULT_TARGET_BRANCH,
        "POST_GITLAB_COMMENTS": post_comments,
    }
    env_lines = [f"{key}={shell_value(value)}" for key, value in values.items()]
    (review / "target.env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    (review / "target.json").write_text(json.dumps({
        "schema_version": 1,
        "status": "ready",
        "target": values["TARGET_LABEL"],
        "url": parsed["url"],
        "base_ref": base_sha,
        "head_ref": head_ref,
        "head_sha": head_sha,
        "gitlab_comments": post_comments,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Target: MR !{iid}; base {base_sha[:12]}; head {head_sha[:12]}; comments {post_comments}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        artifacts = Path(os.environ.get("ARTIFACTS_DIR", ".artifacts"))
        write_block(artifacts / "review", f"Target resolution blocked. {exc}")
        raise SystemExit(2)
