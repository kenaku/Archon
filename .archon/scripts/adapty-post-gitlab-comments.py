#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote


def parse_env(path):
    data = {}
    for raw in Path(path).read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        data[key] = value
    return data


class CommandError(Exception):
    def __init__(self, args, returncode, stdout, stderr):
        self.args_list = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(self.format())

    def format(self):
        return f"Command failed ({self.returncode}): {' '.join(self.args_list)}\n{self.stderr.strip()}\n{self.stdout.strip()}"


def run_json(args):
    proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise CommandError(args, proc.returncode, proc.stdout, proc.stderr)
    try:
        return json.loads(proc.stdout or '{}')
    except Exception as exc:
        raise SystemExit(f"Command did not return JSON: {' '.join(args)}\n{exc}\n{proc.stdout[:1000]}")



def existing_review_notes(host, project_id, iid):
    discussions = run_json(['glab', 'api', '--hostname', host, f'/projects/{project_id}/merge_requests/{iid}/discussions'])
    existing_inline = set()
    if not isinstance(discussions, list):
        return existing_inline
    for discussion in discussions:
        for note_obj in discussion.get('notes') or []:
            if not isinstance(note_obj, dict):
                continue
            body = note_obj.get('body') or ''
            position = note_obj.get('position') or {}
            existing_inline.add((position.get('new_path'), position.get('new_line'), body))
    return existing_inline


def existing_plain_notes(host, project_id, iid):
    notes = run_json(['glab', 'api', '--hostname', host, f'/projects/{project_id}/merge_requests/{iid}/notes'])
    existing = set()
    if not isinstance(notes, list):
        return existing
    for note_obj in notes:
        if isinstance(note_obj, dict):
            existing.add(note_obj.get('body') or '')
    return existing


def fallback_body(file_path, line, note):
    return f"**File:** `{file_path}:{line}`\n\n{note}"


def is_unmappable_line_error(exc):
    text = f"{exc.stderr}\n{exc.stdout}"
    return exc.returncode == 1 and '400 Bad request' in text and 'line_code' in text

def load_comments(path):
    comments = []
    if not path.exists():
        return comments
    for lineno, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except Exception as exc:
            raise SystemExit(f"Invalid JSONL at {path}:{lineno}: {exc}")
        comments.append(item)
    return comments


def main():
    artifacts = Path(os.environ['ARTIFACTS_DIR'])
    review = artifacts / 'review'
    env = parse_env(review / 'target.env')
    comments_path = review / 'gitlab-comments.jsonl'
    comments = load_comments(comments_path)
    post_enabled = env.get('POST_GITLAB_COMMENTS') == 'yes'
    if not post_enabled:
        print(f"GitLab inline comments: {len(comments)} drafted, 0 posted.")
        return 0
    if env.get('TARGET_KIND') != 'mr':
        raise SystemExit('GitLab inline comments require TARGET_KIND=mr')
    if not comments:
        print('GitLab inline comments: 0 drafted, 0 posted.')
        return 0

    project = env.get('PROJECT_FULL_PATH')
    iid = env.get('MR_IID')
    if not project or not iid:
        raise SystemExit('target.env missing PROJECT_FULL_PATH or MR_IID')
    project_id = quote(project, safe='')
    host = env.get('GITLAB_HOST') or 'gitlab.adapty.io'
    versions = run_json(['glab', 'api', '--hostname', host, f'/projects/{project_id}/merge_requests/{iid}/versions'])
    if not isinstance(versions, list) or not versions:
        raise SystemExit('GitLab MR versions response is empty')
    version = versions[0]
    base_sha = version.get('base_commit_sha')
    start_sha = version.get('start_commit_sha')
    head_sha = version.get('head_commit_sha')
    if not (base_sha and start_sha and head_sha):
        raise SystemExit('GitLab MR version is missing position SHAs')

    existing_inline = existing_review_notes(host, project_id, iid)
    existing_plain = existing_plain_notes(host, project_id, iid)
    posted_inline = 0
    posted_fallback = 0
    skipped = 0
    for index, item in enumerate(comments, start=1):
        file_path = item.get('file') or item.get('file_path')
        line = item.get('line') or item.get('new_line')
        note = item.get('note')
        if not (file_path and line and note):
            raise SystemExit(f'Comment #{index} must contain file, line, and note')
        inline_key = (file_path, int(line), note)
        plain_body = fallback_body(file_path, int(line), note)
        if inline_key in existing_inline or plain_body in existing_plain:
            skipped += 1
            continue
        payload = {
            'body': note,
            'position': {
                'position_type': 'text',
                'base_sha': base_sha,
                'start_sha': start_sha,
                'head_sha': head_sha,
                'new_path': file_path,
                'new_line': int(line),
            },
        }
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.json', delete=False) as fh:
            json.dump(payload, fh, ensure_ascii=False)
            payload_path = fh.name
        try:
            try:
                response = run_json(['glab', 'api', '--hostname', host, '-X', 'POST', '-H', 'Content-Type: application/json', f'/projects/{project_id}/merge_requests/{iid}/discussions', '--input', payload_path])
            except CommandError as exc:
                if not is_unmappable_line_error(exc):
                    raise SystemExit(exc.format())
                fallback_payload = {'body': plain_body}
                with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.json', delete=False) as fallback_fh:
                    json.dump(fallback_payload, fallback_fh, ensure_ascii=False)
                    fallback_path = fallback_fh.name
                try:
                    run_json(['glab', 'api', '--hostname', host, '-X', 'POST', '-H', 'Content-Type: application/json', f'/projects/{project_id}/merge_requests/{iid}/notes', '--input', fallback_path])
                finally:
                    try:
                        os.unlink(fallback_path)
                    except OSError:
                        pass
                existing_plain.add(plain_body)
                posted_fallback += 1
                continue
        finally:
            try:
                os.unlink(payload_path)
            except OSError:
                pass
        notes = response.get('notes') if isinstance(response, dict) else None
        if not notes or not any(note.get('type') == 'DiffNote' and note.get('position') for note in notes if isinstance(note, dict)):
            raise SystemExit(f'GitLab did not create a valid DiffNote for comment #{index}')
        existing_inline.add(inline_key)
        posted_inline += 1
    print(f"GitLab comments: {len(comments)} drafted, {posted_inline} inline posted, {posted_fallback} fallback posted, {skipped} already present.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
