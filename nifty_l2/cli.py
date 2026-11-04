import argparse
import json
from .storage import Store, DEFAULT_DB
from .migration import import_file, verify_import


def main():
    parser = argparse.ArgumentParser(description='NIFTY research storage; no trading or network access')
    parser.add_argument('--db', default=str(DEFAULT_DB))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    commands.add_parser('integrity')
    commands.add_parser('verify-imports')
    imp = commands.add_parser('import')
    imp.add_argument('files', nargs='+')
    imp.add_argument('--observed-at', help='Known capture time with timezone, for legacy files without timestamps')
    backup = commands.add_parser('backup')
    backup.add_argument('destination')
    args = parser.parse_args()
    store = Store(args.db)
    if args.command in ('init', 'integrity'):
        result = store.integrity()
    elif args.command == 'import':
        result = [import_file(store, file, observed_at=args.observed_at) for file in args.files]
    elif args.command == 'verify-imports':
        with store.connect() as conn:
            result = [verify_import(conn, sha) for sha, in conn.execute('SELECT file_sha256 FROM import_files')]
    else:
        result = store.backup(args.destination)
    print(json.dumps(result, indent=2))
    if isinstance(result, dict) and result.get('ok') is False or isinstance(result, list) and any(r.get('ok') is False for r in result):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
