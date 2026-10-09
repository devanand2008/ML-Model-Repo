"""Cloud storage preserves data and production startup cannot use demo credentials."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from start_cloud import configure_storage, copy_missing, validate_credentials


def test_seed_preserves_operator_data_and_skips_download_cache(tmp_path):
    source=tmp_path/'seed';source.mkdir()
    (source/'yolo26n.pt').write_bytes(b'stock seed')
    (source/'new.json').write_bytes(b'new seed')
    (source/'.cache').mkdir()
    (source/'.cache'/'private-download').write_bytes(b'cache')
    destination=tmp_path/'disk';destination.mkdir()
    (destination/'yolo26n.pt').write_bytes(b'operator model')
    copy_missing(source,destination)
    assert (destination/'yolo26n.pt').read_bytes()==b'operator model'
    assert (destination/'new.json').read_bytes()==b'new seed'
    assert not (destination/'.cache').exists()
    assert sorted(p.name for p in destination.iterdir())==['new.json','yolo26n.pt']


def test_storage_routes_runtime_files_to_disk_and_uses_https_origin(tmp_path,monkeypatch):
    seed=tmp_path/'seed'
    for name in ('weights','forecasting','synthetic'):
        (seed/name).mkdir(parents=True)
    (seed/'forecasting'/'demand_30.json').write_text('seed',encoding='utf-8')
    keys=['DATABASE_URL','WEIGHTS_DIR','UPLOAD_DIR','OUTPUT_DIR','REPORT_DIR',
          'TRANSIT_FORECAST_DIR','TRANSIT_DEMAND_DATASET','CORS_ORIGINS']
    for key in keys:
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv('RENDER_EXTERNAL_HOSTNAME','example.onrender.com')
    # Record all later setdefault writes for restoration by monkeypatch.
    import os
    snapshot=dict(os.environ)
    try:
        disk=tmp_path/'storage'
        configure_storage(disk,seed)
        assert os.environ['DATABASE_URL']=='sqlite+aiosqlite:///'+(disk/'visionx.db').as_posix()
        assert os.environ['CORS_ORIGINS']=='https://example.onrender.com'
        for key in keys[1:-1]:
            assert Path(os.environ[key]).is_relative_to(disk)
        assert (disk/'forecasting'/'demand_30.json').read_text()=='seed'
        monkeypatch.setenv('DATABASE_URL','postgresql+asyncpg://configured-example')
        configure_storage(disk,seed)
        assert os.environ['DATABASE_URL']=='postgresql+asyncpg://configured-example'
    finally:
        os.environ.clear();os.environ.update(snapshot)


@pytest.mark.parametrize('auth,password,secret',[
    ('false','long-enough-password','x'*32),
    ('true','changeme','x'*32),
    ('true','long-enough-password','change-me'),
])
def test_cloud_rejects_unsafe_credentials(auth,password,secret,monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED',auth)
    monkeypatch.setenv('ADMIN_PASSWORD',password)
    monkeypatch.setenv('SECRET_KEY',secret)
    with pytest.raises(RuntimeError):validate_credentials()


def test_cloud_accepts_configured_credentials(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED','true')
    monkeypatch.setenv('ADMIN_PASSWORD','deployment-test-password')
    monkeypatch.setenv('SECRET_KEY','s'*32)
    validate_credentials()
