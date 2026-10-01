"""Durable activity report history and authenticated text downloads."""
import json
import re
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from config import settings
from security import require_user

router = APIRouter(dependencies=[Depends(require_user)])
ID_PATTERN = re.compile(r'activity_[0-9a-f]{32}_\d{4,}')

@router.get('/reports')
async def list_reports(limit: int = Query(50, ge=1, le=100)):
    reports = []
    for path in settings.report_dir.glob('activity_*.json'):
        if not ID_PATTERN.fullmatch(path.stem):
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data['id'] == path.stem and path.with_suffix('.txt').is_file():
                reports.append(data)
        except (OSError, ValueError, KeyError):
            continue
    reports.sort(key=lambda item: item['ended_at'], reverse=True)
    return {'reports': reports[:limit]}

@router.get('/reports/{report_id}/download')
async def download_report(report_id: str):
    if not ID_PATTERN.fullmatch(report_id):
        raise HTTPException(400, 'Invalid report ID')
    path = settings.report_dir / f'{report_id}.txt'
    if not path.is_file():
        raise HTTPException(404, 'Report not found')
    return FileResponse(path, media_type='text/plain; charset=utf-8', filename=path.name)
