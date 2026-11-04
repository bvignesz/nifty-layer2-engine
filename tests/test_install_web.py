import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('install_web', Path(__file__).resolve().parents[1] / 'scripts/install_web.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_private_install_config_and_overwrite_refusal(tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = tmp_path / 'config'
    service = installer.prepare('https://research.example.com', root, config)
    assert 'nifty_l2.web' in service
    assert config.stat().st_mode & 0o777 == 0o700
    env = config / 'web.env'
    assert env.stat().st_mode & 0o777 == 0o600
    contents = env.read_text()
    assert 'NIFTY_WEB_ORIGIN=https://research.example.com' in contents
    assert len(contents.split('NIFTY_WEB_PASSWORD=')[1].strip()) >= 32
    with pytest.raises(ValueError, match='already exists'):
        installer.prepare('https://research.example.com', root, config)
    assert env.read_text() == contents


@pytest.mark.parametrize('origin', ['http://public.example.com', 'https://example.com/path', 'https://user@example.com', 'https://example.com\nBAD=1'])
def test_install_rejects_invalid_origins(tmp_path, origin):
    with pytest.raises(ValueError):
        installer.prepare(origin, Path(__file__).resolve().parents[1], tmp_path / 'config')
