"""Initialize cloud storage and start the unified app on Render's assigned port."""
import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def validate_credentials() -> None:
    if os.getenv('AUTH_ENABLED','true').lower() not in {'true','1'}:
        raise RuntimeError('Cloud deployment requires AUTH_ENABLED=true')
    password=os.getenv('ADMIN_PASSWORD','')
    if len(password)<12 or password.lower() in {'changeme','change-me'}:
        raise RuntimeError('Set ADMIN_PASSWORD to a strong value of at least 12 characters in Render')
    if len(os.getenv('SECRET_KEY',''))<32:
        raise RuntimeError('Set SECRET_KEY to a random value of at least 32 characters in Render')


def copy_missing(source: Path, destination: Path) -> None:
    """Seed new disks without replacing uploaded weights, trained models or data."""
    if not source.is_dir():
        raise RuntimeError(f'Cloud model seed directory is missing: {source}')
    for original in source.rglob('*'):
        if not original.is_file() or '.cache' in original.parts:
            continue
        target=destination/original.relative_to(source)
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            continue
        with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as temporary:
            pending=Path(temporary.name)
        try:
            shutil.copyfile(original,pending)
            os.replace(pending,target)
        finally:
            pending.unlink(missing_ok=True)


def configure_storage(storage: Path, seed: Path) -> None:
    storage=storage.resolve()
    storage.mkdir(parents=True,exist_ok=True)
    for name in ('weights','forecasting','synthetic','uploads','outputs','reports'):
        (storage/name).mkdir(exist_ok=True)
    for name in ('weights','forecasting','synthetic'):
        copy_missing(seed/name,storage/name)
    paths={
        'DATABASE_URL':'sqlite+aiosqlite:///'+(storage/'visionx.db').as_posix(),
        'WEIGHTS_DIR':str(storage/'weights'),'UPLOAD_DIR':str(storage/'uploads'),
        'OUTPUT_DIR':str(storage/'outputs'),'REPORT_DIR':str(storage/'reports'),
        'TRANSIT_FORECAST_DIR':str(storage/'forecasting'),
        'TRANSIT_DEMAND_DATASET':str(storage/'synthetic'/'transit_demand.csv.gz'),
    }
    for name,value in paths.items():
        os.environ.setdefault(name,value)
    # Tell Uvicorn the public origin is HTTPS behind Render's trusted proxy.
    # The single service serves both frontend and API on this same origin.
    os.environ.setdefault('CORS_ORIGINS','')
    hostname=os.getenv('RENDER_EXTERNAL_HOSTNAME')
    if hostname and not os.environ['CORS_ORIGINS']:
        os.environ['CORS_ORIGINS']='https://'+hostname


def drop_privileges(storage: Path) -> None:
    if os.name!='posix' or os.geteuid()!=0:
        return
    import pwd
    account=pwd.getpwnam('visionx')
    # Disk mounts replace Docker's pre-created directory and can be root-owned.
    for directory,subdirectories,files in os.walk(storage):
        for path in [Path(directory),*(Path(directory)/name for name in subdirectories+files)]:
            if not path.is_symlink():
                os.chown(path,account.pw_uid,account.pw_gid)
    os.initgroups(account.pw_name,account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.environ['HOME']=account.pw_dir


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage-dir',type=Path,default=Path(os.getenv('PERSISTENT_STORAGE','/app/storage')))
    parser.add_argument('--seed-dir',type=Path,default=Path(os.getenv('CLOUD_SEED_DIR','/app/cloud-seed')))
    args=parser.parse_args()
    port=int(os.getenv('PORT','10000'))
    if not 1<=port<=65535:
        raise ValueError('PORT must be between 1 and 65535')
    validate_credentials()
    configure_storage(args.storage_dir,args.seed_dir)
    drop_privileges(args.storage_dir.resolve())
    os.execv(sys.executable,[sys.executable,'-m','uvicorn','main:app','--app-dir',str(ROOT/'backend'),
        '--host','0.0.0.0','--port',str(port),'--workers','1',
        '--proxy-headers','--forwarded-allow-ips','*'])


if __name__=='__main__':
    main()
