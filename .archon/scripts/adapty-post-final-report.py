#!/usr/bin/env python3
import json
import os
import subprocess
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


def run_json(args, payload):
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.json', delete=False) as fh:
        json.dump(payload, fh, ensure_ascii=False)
        payload_path = fh.name
    try:
        proc = subprocess.run(args + ['--input', payload_path], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    finally:
        try:
            os.unlink(payload_path)
        except OSError:
            pass
    if proc.returncode != 0:
        raise SystemExit(f"Command failed ({proc.returncode}): {' '.join(args)} --input <payload>\n{proc.stderr.strip()}\n{proc.stdout.strip()}")
    try:
        return json.loads(proc.stdout or '{}')
    except Exception as exc:
        raise SystemExit(f"Command did not return JSON: {' '.join(args)}\n{exc}\n{proc.stdout[:1000]}")



def run_get_json(args):
    proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise SystemExit(f"Command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr.strip()}\n{proc.stdout.strip()}")
    try:
        return json.loads(proc.stdout or '{}')
    except Exception as exc:
        raise SystemExit(f"Command did not return JSON: {' '.join(args)}\n{exc}\n{proc.stdout[:1000]}")

def main():
    artifacts = Path(os.environ['ARTIFACTS_DIR'])
    review = artifacts / 'review'
    env = parse_env(review / 'target.env')
    report_path = review / 'final-report.md'
    if env.get('POST_GITLAB_COMMENTS') != 'yes':
        print('GitLab final report: draft-only.')
        return 0
    if env.get('TARGET_KIND') != 'mr':
        raise SystemExit('GitLab final report requires TARGET_KIND=mr')
    if not report_path.exists():
        raise SystemExit(f'Missing final report: {report_path}')
    body = report_path.read_text(encoding='utf-8')
    if not body.strip():
        raise SystemExit(f'Final report is empty: {report_path}')
    project = env.get('PROJECT_FULL_PATH')
    iid = env.get('MR_IID')
    host = env.get('GITLAB_HOST') or 'gitlab.adapty.io'
    if not project or not iid:
        raise SystemExit('target.env missing PROJECT_FULL_PATH or MR_IID')
    project_id = quote(project, safe='')
    notes = run_get_json(['glab', 'api', '--hostname', host, f'/projects/{project_id}/merge_requests/{iid}/notes'])
    if isinstance(notes, list):
        for note in notes:
            if not isinstance(note, dict):
                continue
            note_body = note.get('body') or ''
            note_id = note.get('id')
            if note_body == body:
                print(f"GitLab final report: already present note {note_id}.")
                return 0
            if note_body.startswith('# Adapty evidence review') and note_id:
                response = run_json(
                    ['glab', 'api', '--hostname', host, '-X', 'PUT', '-H', 'Content-Type: application/json', f'/projects/{project_id}/merge_requests/{iid}/notes/{note_id}'],
                    {'body': body},
                )
                updated_id = response.get('id') if isinstance(response, dict) else note_id
                print(f"GitLab final report: updated note {updated_id}.")
                return 0
    response = run_json(
        ['glab', 'api', '--hostname', host, '-X', 'POST', '-H', 'Content-Type: application/json', f'/projects/{project_id}/merge_requests/{iid}/notes'],
        {'body': body},
    )
    note_id = response.get('id') if isinstance(response, dict) else None
    if not note_id:
        raise SystemExit('GitLab did not return a note id for final report')
    print(f'GitLab final report: posted note {note_id}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
