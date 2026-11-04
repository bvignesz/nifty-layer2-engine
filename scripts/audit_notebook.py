"""Audit all reachable Git blobs and notebook cells without printing secret values."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SENSITIVE = re.compile(r'(?:secret|token|password|client_id|chat_id|api_key)', re.I)
TOKEN = re.compile(r'\b\d{7,12}:[A-Za-z0-9_-]{25,}\b|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')


def scan_source(source, location):
    findings = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = ast.parse('\n'.join('' if line.lstrip().startswith(('!', '%')) else line for line in source.splitlines()))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name)]
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                value = node.value.value
            elif (isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == 'os.environ.get'
                  and len(node.value.args) > 1 and isinstance(node.value.args[1], ast.Constant)
                  and isinstance(node.value.args[1].value, str)):
                value = node.value.args[1].value
            else:
                continue
            if value and any(SENSITIVE.search(n) for n in names) and not any(x in value.upper() for x in ('YOUR_', 'PLACEHOLDER', 'REDACTED', 'PASTE', 'REPLACE_')):
                findings.append({'location': location, 'line': node.lineno, 'names': names,
                                 'fingerprint': hashlib.sha256(value.encode()).hexdigest()[:12], 'type': 'literal credential or identifier'})
    for match in TOKEN.finditer(source):
        findings.append({'location': location, 'type': 'token pattern', 'fingerprint': hashlib.sha256(match[0].encode()).hexdigest()[:12]})
    return findings


def main():
    findings = []
    commits = subprocess.check_output(['git', 'rev-list', '--all'], cwd=ROOT, text=True).splitlines()
    for commit in commits:
        paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', commit], cwd=ROOT, text=True).splitlines()
        for path in paths:
            data = subprocess.check_output(['git', 'show', f'{commit}:{path}'], cwd=ROOT).decode('utf-8', errors='replace')
            if path.endswith('.ipynb'):
                nb = json.loads(data)
                for i, cell in enumerate(nb['cells']):
                    source = ''.join(cell.get('source', []))
                    if cell['cell_type'] == 'code':
                        findings.extend(scan_source(source, f'{commit}:{path}:cell{i}'))
                    for match in TOKEN.finditer(json.dumps(cell.get('outputs', []))):
                        findings.append({'location': f'{commit}:{path}:cell{i}:output', 'type': 'token in output', 'fingerprint': hashlib.sha256(match[0].encode()).hexdigest()[:12]})
            elif path.endswith('.py') or path == 'layer2':
                findings.extend(scan_source(data, f'{commit}:{path}'))
    nb = json.loads(subprocess.check_output(['git', 'show', 'HEAD:final.ipynb'], cwd=ROOT))
    cells = []
    for i, cell in enumerate(nb['cells']):
        source = ''.join(cell.get('source', []))
        operations = [{'line': j, 'operation': line.strip()} for j, line in enumerate(source.splitlines(), 1)
                      if any(x in line for x in ('drive.mount', '/content/drive', 'to_csv(', 'csv.writer', 'json.dump', 'sqlite3.connect', 'open(', 'os.fsync', 'os.sync', 'os.makedirs', 'urlretrieve', 'os.chmod'))]
        cells.append({'cell': i, 'type': cell['cell_type'], 'line_count': len(source.splitlines()), 'output_count': len(cell.get('outputs', [])), 'storage_operations': operations})
    report = {'reachable_commits_scanned': commits, 'credential_findings': findings, 'cells': cells,
              'scope': 'All files in all refs reachable from this local clone; no inaccessible server refs or deleted remote objects.'}
    target = ROOT / 'docs/audit-inventory.json'
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'commits': len(commits), 'cells': len(cells), 'findings': len(findings), 'credential_names': sorted({n for f in findings for n in f.get('names', [])})}))


if __name__ == '__main__':
    main()
