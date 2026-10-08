"""
VisionX AI Analyzer — Database Models & Setup
SQLAlchemy async with SQLite
"""
from datetime import datetime
from typing import Optional, Any
import json

from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, Enum
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship

from config import settings

engine = create_async_engine(str(settings.database_url), echo=settings.debug)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ───────────────────────────── Models ────────────────────────────────

class AIModel(Base):
    __tablename__ = "ai_models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    model_type = Column(String(60), nullable=False)   # general|human|ship|container|condition
    filename = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    version = Column(String(40), default="1.0.0")
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    confidence_threshold = Column(Float, default=0.50)
    class_names = Column(Text, default="[]")           # JSON array
    dataset_info = Column(Text, default="{}")          # JSON object
    metrics = Column(Text, default="{}")               # JSON object
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    analyses = relationship("Analysis", back_populates="model")

    @property
    def class_names_list(self):
        return json.loads(self.class_names or "[]")

    @property
    def metrics_dict(self):
        return json.loads(self.metrics or "{}")


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    analyzer_type = Column(String(60), nullable=False)   # image|human|ship|container|combined
    input_filename = Column(String(255), nullable=True)
    input_type = Column(String(20), default="image")     # image|video|webcam
    output_filename = Column(String(255), nullable=True)
    model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=True)
    confidence_threshold = Column(Float, default=0.50)
    total_objects = Column(Integer, default=0)
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)
    processing_time = Column(Float, nullable=True)
    results = Column(Text, default="{}")                 # Full JSON payload
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    model = relationship("AIModel", back_populates="analyses")
    detections = relationship("Detection", back_populates="analysis", cascade="all, delete-orphan")


class Detection(Base):
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False)
    class_name = Column(String(120), nullable=False)
    confidence = Column(Float, nullable=False)
    bbox_x = Column(Float, nullable=True)
    bbox_y = Column(Float, nullable=True)
    bbox_w = Column(Float, nullable=True)
    bbox_h = Column(Float, nullable=True)
    track_id = Column(Integer, nullable=True)
    frame_number = Column(Integer, nullable=True)

    analysis = relationship("Analysis", back_populates="detections")


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    dataset_type = Column(String(60), nullable=False)
    description = Column(Text, nullable=True)
    num_images = Column(Integer, default=0)
    num_labels = Column(Integer, default=0)
    class_names = Column(Text, default="[]")
    split_info = Column(Text, default="{}")
    yaml_path = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ───────────────────────────── Helpers ───────────────────────────────

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(120), unique=True, nullable=False)
    role = Column(String(30), default="admin")
    # Passwords are configured in environment; never stored as plaintext in this table.
    created_at = Column(DateTime, default=datetime.utcnow)

class ModelVersion(Base):
    __tablename__ = "model_versions"
    id = Column(Integer, primary_key=True)
    model_id = Column(Integer, ForeignKey("ai_models.id"), nullable=False)
    version = Column(String(40), nullable=False)
    sha256 = Column(String(64), nullable=False)
    filename = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Additive compatibility migration for the initial scaffold database.
        from sqlalchemy import inspect, text
        columns = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("analyses")})
        if "user_id" not in columns:
            await conn.execute(text("ALTER TABLE analyses ADD COLUMN user_id INTEGER REFERENCES users(id)"))


async def seed_default_models():
    """Insert default pretrained model records if not already present."""
    from sqlalchemy import select
    async with AsyncSessionLocal() as session:
        operator = await session.execute(select(User).where(User.username == settings.admin_username))
        if not operator.scalars().first():
            session.add(User(username=settings.admin_username,role="admin"))
            await session.commit()
        result = await session.execute(select(AIModel))
        if result.scalars().first():
            return  # already seeded

        # COCO class names (80 classes)
        coco_classes = [
            "person","bicycle","car","motorcycle","airplane","bus","train","truck","boat",
            "traffic light","fire hydrant","stop sign","parking meter","bench","bird","cat",
            "dog","horse","sheep","cow","elephant","bear","zebra","giraffe","backpack",
            "umbrella","handbag","tie","suitcase","frisbee","skis","snowboard","sports ball",
            "kite","baseball bat","baseball glove","skateboard","surfboard","tennis racket",
            "bottle","wine glass","cup","fork","knife","spoon","bowl","banana","apple",
            "sandwich","orange","broccoli","carrot","hot dog","pizza","donut","cake","chair",
            "couch","potted plant","bed","dining table","toilet","tv","laptop","mouse","remote",
            "keyboard","cell phone","microwave","oven","toaster","sink","refrigerator","book",
            "clock","vase","scissors","teddy bear","hair drier","toothbrush"
        ]

        known_assets = {"yolo26n.pt": ("YOLO26 nano", "26"),
                        "yolov8n.pt": ("YOLOv8 nano", "8")}
        labels = {"general":"General Object Detector", "human":"Human Detector",
                  "ship":"Ship Detector", "container":"Container Detector"}
        defaults = []
        for kind in ("general", "human", "ship", "container"):
            filename = getattr(settings, f"{kind}_model")
            known = known_assets.get(filename)
            classes = (["person"] if kind == "human" else ["boat"] if kind == "ship" else coco_classes) if known else []
            if known:
                architecture, version = known
                description = f"Configured {architecture} COCO checkpoint. "
                description += {"general":"Uses its supported 80 object classes.",
                                "human":"Person detection filters the supported person class.",
                                "ship":"COCO boat detections are a ship fallback; ship subtypes are unavailable.",
                                "container":"COCO has no shipping-container class; container/condition results remain unavailable."}[kind]
                name = f"{labels[kind]} ({architecture} COCO)"
            else:
                version = "configured"
                name = f"{labels[kind]} (Configured weights)"
                description = "Uses the existing checkpoint selected in configuration. Class names are discovered from the installed model; no classes or accuracy are assumed."
            defaults.append(AIModel(name=name, model_type=kind, filename=filename,
                description=description, version=version, is_active=True, is_default=True,
                confidence_threshold=.50 if kind == "general" else .45,
                class_names=json.dumps(classes), metrics=json.dumps({}),
                dataset_info=json.dumps({"source":"configured_checkpoint","class_metadata":"known_asset" if known else "not_inspected"})))

        session.add_all(defaults)
        await session.commit()
