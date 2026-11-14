"""Offline secret guard. Diagnostics contain paths, categories and hashes only."""
from pathlib import Path, PurePosixPath
from datetime import date
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

ALLOWLIST = '.secrets-allowlist'
PATTERNS = {
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----'),
    'github-token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'aws-access-key': re.compile(rb'(?:AKIA|ASIA)[A-Z0-9]{16}'),
    'telegram-token': re.compile(rb'\b\d{6,12}:[A-Za-z0-9_-]{30,}\b'),
    'provider-key': re.compile(rb'\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}'),
}
ASSIGNMENT = re.compile(rb'''(?im)(?:^|[{,])[ \t]*(?:(?:export|const|let|var)[ \t]+)*["']?([a-z_][a-z0-9_.-]*)["']?[ \t]*[:=][ \t]*(?:"([^"\r\n]*)"|'([^'\r\n]*)'|([^\r\n#,}]+))''')
NAME = re.compile(rb'(?:^|[_ .-])(?:password|passwd|token|secret|api[_-]?key)$', re.I)
PLACEHOLDERS = {b'placeholder', b'changeme', b'your_api_key', b'example', b'redacted', b'none', b'null', b'true', b'false'}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def literal_like(value: bytes) -> bool:
    """Heuristic, not a parser: skip expressions, prose, URLs and obvious examples."""
    if len(value) < 12 or value.lower() in PLACEHOLDERS:
        return False
    if value.startswith((b'$' + b'{', b'<')) or value.lower().startswith((b'http://', b'https://')):
        return False
    if re.search(rb'[\s()\[\]{}"\'\\]', value):
        return False
    if value.lower().startswith((b'os.', b'process.', b'settings.', b'config.', b'self.')):
        return False
    if value.lower().startswith((b'your_', b'example_', b'placeholder_', b'replace_', b'insert_')):
        return False
    if re.fullmatch(rb'[a-z]+(?:[A-Z][a-z0-9]+)+', value):
        return False
    if re.fullmatch(rb'[a-z_][a-z_0-9]*(?:\.[a-z_][a-z_0-9]*)*', value):
        return b'_' not in value and b'.' not in value and (len(value) >= 20 or bool(re.search(rb'\d', value)))
    if re.fullmatch(rb'[A-Z_][A-Z_0-9]*(?:\.[A-Z_][A-Z_0-9]*)*', value):
        return b'_' not in value and b'.' not in value and (len(value) >= 20 or bool(re.search(rb'\d', value)))
    return True


def findings(path: str, data: bytes) -> list[tuple[str, str]]:
    p = PurePosixPath(path.lower())
    name = p.name
    blocked = (
        (name == '.env' or name.startswith('.env.')) and name not in {'.env.example', '.env.template'}
        or name in {'rclone.conf', 'credentials.json', 'token.json', 'tokens.json', '.npmrc', '.pypirc', 'settings.local.json'}
        or name.startswith(('id_rsa', 'id_ed25519'))
        or p.suffix in {'.pem', '.key', '.p12', '.pfx'}
        or bool(set(p.parts) & {'secrets', 'credentials', 'private', 'transcripts'})
    )
    result = [('sensitive-path', digest(data))] if blocked else []
    if b'\0' in data:
        return result
    for label, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            result.append((label, digest(data if label == 'private-key' else match.group())))
    for match in ASSIGNMENT.finditer(data):
        if not NAME.search(match.group(1)):
            continue
        value = next(x for x in match.groups()[1:] if x is not None).strip()
        if match.group(4) is not None:
            value = value.removesuffix(b';').rstrip()
        if literal_like(value):
            result.append(('credential-literal', digest(value)))
    return list(dict.fromkeys(result))


def inspect(path: str, data: bytes) -> list[str]:
    return sorted({label for label, _ in findings(path, data)})


def git(root: Path, *args: str, input: bytes | None = None) -> bytes:
    return subprocess.check_output(['git', *args], cwd=root, input=input, stderr=subprocess.DEVNULL)


def parse_allowlist(data: bytes) -> set[tuple[str, str, str]]:
    if not data:
        return set()
    value = json.loads(data)
    if not isinstance(value, dict) or set(value) != {'version', 'entries'} or type(value['version']) is not int or value['version'] != 1 or not isinstance(value['entries'], list):
        raise ValueError('Invalid allowlist structure.')
    result = set()
    for entry in value['entries']:
        if not isinstance(entry, dict) or set(entry) != {'path', 'type', 'sha256', 'reason', 'date'}:
            raise ValueError('Invalid allowlist entry.')
        path, label, fingerprint, reason, when = (entry[x] for x in ('path', 'type', 'sha256', 'reason', 'date'))
        if not all(isinstance(x, str) for x in (path, label, fingerprint, reason, when)):
            raise ValueError('Invalid allowlist fields.')
        p = PurePosixPath(path)
        if not path or p.is_absolute() or '..' in p.parts or p.as_posix() != path or any(c in path for c in '*?\\:'):
            raise ValueError('Allowlist paths must be exact relative POSIX paths.')
        if label not in {*PATTERNS, 'sensitive-path', 'credential-literal'} or not re.fullmatch('[a-f0-9]{64}', fingerprint) or not reason.strip():
            raise ValueError('Invalid allowlist type, fingerprint or reason.')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', when):
            raise ValueError('Invalid allowlist date.')
        date.fromisoformat(when)
        key = (path, label, fingerprint)
        if key in result:
            raise ValueError('Duplicate allowlist entry.')
        result.add(key)
    return result


def allowlist_at(root: Path, mode: str, ref: str = 'HEAD') -> set[tuple[str, str, str]]:
    if mode == 'working':
        p = root / ALLOWLIST
        if p.is_symlink():
            raise ValueError('Allowlist must be a regular file.')
        return parse_allowlist(p.read_bytes() if p.exists() else b'')
    if mode == 'staged':
        entries = [x for x in git(root, 'ls-files', '--stage', '-z', '--', ALLOWLIST).split(b'\0') if x]
        if not entries:
            return set()
        meta = entries[0].split(b'\t', 1)[0].split()
        if len(entries) != 1 or meta[0] != b'100644' or meta[2] != b'0':
            raise ValueError('Allowlist must be a regular resolved file.')
        return parse_allowlist(git(root, 'cat-file', 'blob', meta[1].decode()))
    entries = git(root, 'ls-tree', '-z', ref, '--', ALLOWLIST).split(b'\0')
    if not entries[0]:
        return set()
    meta = entries[0].split(b'\t', 1)[0].split()
    if meta[0] != b'100644':
        raise ValueError('Allowlist must be a regular file.')
    return parse_allowlist(git(root, 'cat-file', 'blob', meta[2].decode()))


def history_entries(root: Path, commits: list[str] | None) -> set[tuple[str, str]]:
    if commits == []:
        return set()
    selection = ['--all'] if commits is None else ['--no-walk=unsorted', '--stdin']
    input_data = None if commits is None else ('\n'.join(commits) + '\n').encode()
    records = git(root, 'log', '--format=', '--raw', '-z', '--no-abbrev', '--no-renames', '--root', '-m', *selection, '--', input=input_data).split(b'\0')
    entries = set()
    i = 0
    while i < len(records):
        record = records[i].strip(b'\n')
        i += 1
        if not record:
            continue
        if not record.startswith(b':') or i == len(records):
            raise ValueError('Unexpected Git diff record.')
        fields = record[1:].split()
        path = records[i].decode('utf-8', 'strict')
        i += 1
        if len(fields) != 5:
            raise ValueError('Unexpected Git diff metadata.')
        if fields[4] == b'D':
            continue
        if fields[1] == b'160000':
            raise ValueError('Submodules need their own guard.')
        entries.add((path, fields[3].decode()))
    return entries


def read_blobs(root: Path, oids: set[str]) -> dict[str, bytes]:
    if not oids:
        return {}
    ordered = sorted(oids)
    output = git(root, 'cat-file', '--batch', input=('\n'.join(ordered) + '\n').encode())
    result = {}
    offset = 0
    for oid in ordered:
        end = output.index(b'\n', offset)
        header = output[offset:end].split()
        if len(header) != 3 or header[0].decode() != oid or header[1] != b'blob':
            raise ValueError('Missing or invalid Git blob.')
        size = int(header[2])
        offset = end + 1
        result[oid] = output[offset:offset + size]
        offset += size
        if output[offset:offset + 1] != b'\n':
            raise ValueError('Truncated Git blob.')
        offset += 1
    return result


def check_files(files, allowed) -> list[tuple[str, list[str]]]:
    result = []
    used = set()
    for path, data in files:
        labels = []
        for label, fp in findings(path, data):
            key = (path, label, fp)
            if key in allowed:
                used.add(key)
            else:
                labels.append(f'{label} [sha256:{fp}]')
        if labels:
            result.append((path, labels))
    for path, label, fp in sorted(allowed - used):
        print(f'Warning: unused exception in this scan scope: {path!r}: {label} [sha256:{fp}]', file=sys.stderr)
    return result


def scan(root: Path, mode: str, commits: list[str] | None = None, ref: str = 'HEAD') -> list[tuple[str, list[str]]]:
    allowed = allowlist_at(root, mode, ref)
    if mode == 'working':
        files = []
        for path in git(root, 'ls-files', '-z').split(b'\0'):
            if path:
                name = path.decode('utf-8', 'strict')
                p = root / name
                if p.is_symlink():
                    files.append((name, os.readlink(p).encode()))
                elif p.is_file():
                    files.append((name, p.read_bytes()))
        return check_files(files, allowed)
    if mode == 'staged':
        entries = set()
        for entry in git(root, 'ls-files', '--stage', '-z').split(b'\0'):
            if not entry:
                continue
            meta, path = entry.split(b'\t', 1)
            perm, oid, stage = meta.split()
            if stage != b'0' or perm == b'160000':
                raise ValueError('Resolve conflicts; submodules are not supported.')
            entries.add((path.decode('utf-8', 'strict'), oid.decode()))
    else:
        entries = history_entries(root, commits)
    blobs = read_blobs(root, {oid for _, oid in entries})
    return check_files(((path, blobs[oid]) for path, oid in sorted(entries)), allowed)


def scan_push(root: Path, stdin: str, remote_name: str) -> list[tuple[str, list[str]]]:
    results = []
    remotes = git(root, 'remote').decode().splitlines()
    for line in stdin.splitlines():
        parts = line.split()
        if len(parts) != 4:
            raise ValueError('Malformed pre-push input.')
        _, local, _, remote = parts
        if not all(re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', oid) for oid in (local, remote)):
            raise ValueError('Invalid object ID.')
        if set(local) == {'0'}:
            continue
        local_commit = git(root, 'rev-parse', '--verify', local + '^{commit}').decode().strip()
        revisions = [local_commit, '--not']
        if remote_name in remotes:
            revisions.append('--remotes=' + remote_name)
        if set(remote) != {'0'}:
            remote_commit = git(root, 'rev-parse', '--verify', remote + '^{commit}').decode().strip()
            revisions.append(remote_commit)
        commits = git(root, 'rev-list', *revisions, '--').decode().splitlines()
        results.extend(scan(root, 'history', commits, ref=local_commit))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--staged', action='store_true')
    group.add_argument('--history', action='store_true')
    group.add_argument('--pre-push', metavar='REMOTE')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        found = scan_push(root, sys.stdin.read(), args.pre_push) if args.pre_push is not None else scan(root, 'history' if args.history else 'staged' if args.staged else 'working')
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError):
        print('Security scan failed; blocked. Check Git objects, conflicts and allowlist; fetch remote refs before retrying push.')
        return 2
    for path, labels in found:
        print(f'{path!r}: {", ".join(labels)}')
    print('Potential secrets found; blocked.' if found else 'Secrets check passed.')
    return int(bool(found))


if __name__ == '__main__':
    raise SystemExit(main())
