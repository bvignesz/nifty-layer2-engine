"""Install the local web service. Public HTTPS routing is configured separately."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.parse import urlparse


def prepare(origin, root, config):
    parsed = urlparse(origin)
    if (parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment or parsed.username
            or any(c in origin for c in '\r\n\x00')
            or (parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost'))):
        raise ValueError('Use an HTTPS public origin or http://127.0.0.1:8080 for local access')
    config.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config, 0o700)
    env = config / 'web.env'
    if env.exists():
        raise ValueError('web.env already exists; update its origin locally and restart nifty-web')
    password = secrets.token_urlsafe(32)
    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(f'NIFTY_WEB_ORIGIN={origin.rstrip("/")}\nNIFTY_WEB_PASSWORD={password}\n')
    service = (root / 'deploy/nifty-web.service').read_text()
    return service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', default='http://127.0.0.1:8080')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if root != Path('/home/ubuntu/nifty-layer2-engine') or Path.home() != Path('/home/ubuntu'):
        parser.error('This service template is for ubuntu in /home/ubuntu/nifty-layer2-engine')
    config = Path.home() / '.config/nifty-layer2'
    try:
        service = prepare(args.origin, root, config)
        subprocess.run(['sudo', '-n', 'tee', '/etc/systemd/system/nifty-web.service'],
                       input=service, text=True, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['sudo', '-n', 'systemctl', 'daemon-reload'], check=True)
        subprocess.run(['sudo', '-n', 'systemctl', 'enable', '--now', 'nifty-web'], check=True)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print('Web service installed. Username: owner')
    print(f'Your generated dashboard password is stored privately in {config / "web.env"}.')
    print('Listen address: http://127.0.0.1:8080 (public HTTPS proxy still required).')


if __name__ == '__main__':
    main()
