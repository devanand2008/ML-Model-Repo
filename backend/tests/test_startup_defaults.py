"""Fresh deployment model configuration and safe public-file serving regressions."""
import asyncio
import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import database
from config import settings, BASE_DIR
from models import registry


def test_fresh_model_seed_matches_config_and_official_resolution(tmp_path,monkeypatch):
    configured={kind:getattr(settings,f"{kind}_model") for kind in ("general","human","ship","container")}
    # Known defaults must resolve safely even before any weight exists, without a network test.
    for kind in configured:
        monkeypatch.setattr(settings,f"{kind}_model","yolo26n.pt")
    empty_weights=tmp_path/"empty-weights";empty_weights.mkdir()
    monkeypatch.setattr(settings,"weights_dir",empty_weights)
    loaded=[]
    sentinel=object()
    def load_checkpoint(path):
        loaded.append(path)
        return sentinel
    monkeypatch.setattr(registry,"_load_yolo",load_checkpoint)
    engine=create_async_engine("sqlite+aiosqlite:///"+(tmp_path/"fresh.db").as_posix())
    factory=async_sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(database,"AsyncSessionLocal",factory)
    async def check():
        async with engine.begin() as conn:
            await conn.run_sync(database.Base.metadata.create_all)
        await database.seed_default_models()
        async with factory() as db:
            records=list((await db.execute(select(database.AIModel))).scalars())
            assert len(records)==4
            assert all(r.filename==getattr(settings,f"{r.model_type}_model") for r in records)
            assert all(r.version=="26" and "YOLO26" in r.name for r in records)
            general=next(r for r in records if r.model_type=="general")
            assert len(general.class_names_list)==80
            assert registry.get_model(general.filename) is sentinel
            assert Path(loaded[0])==empty_weights/"yolo26n.pt"
        await engine.dispose()
    asyncio.run(check())


def test_custom_model_seed_does_not_invent_classes_or_overwrite_records(tmp_path,monkeypatch):
    files={"general":"authorized_custom.pt","human":"authorized_person.pt",
           "ship":"yolov8n.pt","container":"authorized_container.pt"}
    for kind,filename in files.items():
        monkeypatch.setattr(settings,f"{kind}_model",filename)
    engine=create_async_engine("sqlite+aiosqlite:///"+(tmp_path/"custom.db").as_posix())
    factory=async_sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(database,"AsyncSessionLocal",factory)
    async def check():
        async with engine.begin() as conn:
            await conn.run_sync(database.Base.metadata.create_all)
        await database.seed_default_models()
        async with factory() as db:
            records=list((await db.execute(select(database.AIModel))).scalars())
            for model in records:
                assert model.filename==files[model.model_type]
                assert model.metrics_dict=={}
                if model.model_type=="ship":
                    assert model.class_names_list==["boat"] and model.version=="8"
                else:
                    assert model.class_names_list==[] and model.version=="configured"
        monkeypatch.setattr(settings,"general_model","yolo26n.pt")
        await database.seed_default_models()
        async with factory() as db:
            records=list((await db.execute(select(database.AIModel))).scalars())
            assert len(records)==4
            assert next(r for r in records if r.model_type=="general").filename==files["general"]
        await engine.dispose()
    asyncio.run(check())


def test_public_svg_and_spa_reject_directory_traversal():
    if not (BASE_DIR/"frontend"/"dist"/"transitopt-icon.svg").exists():
        pytest.skip("Build the frontend before checking public artifacts")
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as client:
        icon=client.get("/transitopt-icon.svg")
        assert icon.status_code==200 and icon.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in icon.text
        assert client.get("/visionx-icon.svg").headers["content-type"].startswith("image/svg+xml")
        assert client.get("/%2e%2e/.env").status_code==404
        assert client.get("/%2e%2e/%2e%2e/visionx.db").status_code==404
        assert client.get("/api/does-not-exist").status_code==404
        assert client.get("/unknown-spa-route").headers["content-type"].startswith("text/html")
