"""Additive transit schema; existing VisionX tables are preserved."""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, ForeignKey, Index
from database import Base


class TransitRoute(Base):
    __tablename__ = "transit_routes"
    id = Column(String(16), primary_key=True)
    name = Column(String(160), nullable=False)
    spec = Column(JSON, nullable=False)
    current_buses = Column(Integer, nullable=False)
    current_variant_id = Column(String(40), nullable=False, default="existing")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TransitStop(Base):
    __tablename__ = "transit_stops"
    id = Column(String(16), primary_key=True)
    name = Column(String(120), nullable=False)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    essential = Column(Boolean, default=True)
    accessible = Column(Boolean, default=True)


class TransitVehicle(Base):
    __tablename__ = "transit_vehicles"
    id = Column(String(16), primary_key=True)
    capacity = Column(Integer, nullable=False, default=50)
    available = Column(Boolean, default=True)
    route_id = Column(String(16), ForeignKey("transit_routes.id"), nullable=True, index=True)
    reserved = Column(Boolean, default=False)


class TransitCamera(Base):
    __tablename__ = "transit_cameras"
    id = Column(String(16), primary_key=True)
    name = Column(String(120), nullable=False)
    stop_id = Column(String(16), ForeignKey("transit_stops.id"), nullable=False)
    corridor_id = Column(String(16), nullable=False)
    roi = Column(JSON, nullable=True)
    status = Column(String(32), default="awaiting_authorized_input")
    source_type = Column(String(32), default="upload_or_browser_camera")


class TransitDetectionEvent(Base):
    __tablename__ = "transit_detection_events"
    id = Column(String(40), primary_key=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=True)
    camera_id = Column(String(16), ForeignKey("transit_cameras.id"), nullable=True)
    source_id = Column(String(80), nullable=False)
    source_type = Column(String(32), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    frame_timestamp_seconds = Column(Float, nullable=True)
    counts = Column(JSON, nullable=False)
    confidence_mean = Column(Float, nullable=True)
    payload = Column(JSON, nullable=False)


class TransitTrafficObservation(Base):
    __tablename__ = "transit_traffic_observations"
    id = Column(String(40), primary_key=True)
    camera_id = Column(String(16), ForeignKey("transit_cameras.id"), nullable=True)
    detection_event_id = Column(String(40), ForeignKey("transit_detection_events.id"), nullable=True)
    corridor_id = Column(String(16), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    score = Column(Float, nullable=False)
    category = Column(String(16), nullable=False)
    source = Column(String(40), nullable=False)
    payload = Column(JSON, nullable=False)


class TransitDemandObservation(Base):
    __tablename__ = "transit_demand_history"
    id = Column(Integer, primary_key=True)
    route_id = Column(String(16), ForeignKey("transit_routes.id"), nullable=False)
    stop_id = Column(String(16), ForeignKey("transit_stops.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    boardings = Column(Float, nullable=False)
    source = Column(String(40), nullable=False)
    features = Column(JSON, nullable=False)
    __table_args__ = (Index("ix_transit_demand_route_time", "route_id", "timestamp"),)


class TransitForecast(Base):
    __tablename__ = "transit_demand_forecasts"
    id = Column(String(40), primary_key=True)
    route_id = Column(String(16), ForeignKey("transit_routes.id"), nullable=False, index=True)
    stop_id = Column(String(16), ForeignKey("transit_stops.id"), nullable=True)
    horizon_minutes = Column(Integer, nullable=False)
    predicted_demand = Column(Float, nullable=False)
    model_version = Column(String(80), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    payload = Column(JSON, nullable=False)


class TransitOptimizationRun(Base):
    __tablename__ = "transit_optimization_runs"
    id = Column(String(40), primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    config = Column(JSON, nullable=False)
    solver_status = Column(String(40), nullable=False)
    feasible = Column(Boolean, nullable=False)
    results = Column(JSON, nullable=False)


class TransitRecommendation(Base):
    __tablename__ = "transit_recommendations"
    id = Column(String(40), primary_key=True)
    run_id = Column(String(40), ForeignKey("transit_optimization_runs.id"), nullable=False, index=True)
    route_id = Column(String(16), ForeignKey("transit_routes.id"), nullable=False)
    status = Column(String(32), nullable=False, default="pending_review")
    proposed_buses = Column(Integer, nullable=False)
    proposed_variant_id = Column(String(40), nullable=False)
    payload = Column(JSON, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)


class TransitScenario(Base):
    __tablename__ = "transit_simulation_scenarios"
    id = Column(String(40), primary_key=True)
    name = Column(String(160), nullable=False)
    run_id = Column(String(40), ForeignKey("transit_optimization_runs.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    inputs = Column(JSON, nullable=False)
    baseline = Column(JSON, nullable=False)
    optimized = Column(JSON, nullable=False)
    payload = Column(JSON, nullable=False)
    activated = Column(Boolean, default=False)


class TransitOperatorAction(Base):
    __tablename__ = "transit_operator_actions"
    id = Column(String(40), primary_key=True)
    recommendation_id = Column(String(40), ForeignKey("transit_recommendations.id"), nullable=True)
    action = Column(String(32), nullable=False)
    operator = Column(String(120), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    payload = Column(JSON, nullable=False)


class TransitVisionJob(Base):
    __tablename__ = "transit_vision_jobs"
    id = Column(String(40), primary_key=True)
    status = Column(String(32), nullable=False)
    progress = Column(Float, default=0)
    timestamp = Column(DateTime, default=datetime.utcnow)
    payload = Column(JSON, nullable=False)


class TransitSetting(Base):
    __tablename__ = "transit_settings"
    key = Column(String(80), primary_key=True)
    value = Column(JSON, nullable=False)


class TransitBusProfile(Base):
    __tablename__ = "transit_bus_profiles"
    bus_id = Column(String(16), ForeignKey("transit_vehicles.id"), primary_key=True)
    registration_number = Column(String(32), unique=True, nullable=False)
    source_city = Column(String(100), nullable=False, default="Salem")
    operator_name = Column(String(120), nullable=True)
    gps_device_id = Column(String(100), nullable=True)
    coverage = Column(String(32), nullable=False, default="partial")
    demo = Column(Boolean, nullable=False, default=False)


class TransitCameraSetup(Base):
    __tablename__ = "transit_camera_setups"
    camera_id = Column(String(16), ForeignKey("transit_cameras.id"), primary_key=True)
    role = Column(String(24), nullable=False, index=True)
    bus_id = Column(String(16), ForeignKey("transit_vehicles.id"), nullable=True, index=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    coordinate_source = Column(String(40), nullable=False, default="unconfigured")
    safety_zone = Column(JSON, nullable=True)
    door_open = Column(Boolean, nullable=True)
    source_label = Column(String(120), nullable=True)


class TransitBusLocation(Base):
    __tablename__ = "transit_bus_locations"
    id = Column(String(40), primary_key=True)
    bus_id = Column(String(16), ForeignKey("transit_vehicles.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy_m = Column(Float, nullable=True)
    heading_deg = Column(Float, nullable=True)
    speed_kmh = Column(Float, nullable=True)
    source = Column(String(40), nullable=False)


class TransitBusOccupancy(Base):
    __tablename__ = "transit_bus_occupancy"
    id = Column(String(40), primary_key=True)
    bus_id = Column(String(16), ForeignKey("transit_vehicles.id"), nullable=False, index=True)
    camera_id = Column(String(16), ForeignKey("transit_cameras.id"), nullable=False, index=True)
    detection_event_id = Column(String(40), ForeignKey("transit_detection_events.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    visible_people = Column(Integer, nullable=False)
    crowd_level = Column(String(16), nullable=False)
    coverage = Column(String(32), nullable=False)
    data_quality = Column(String(40), nullable=False)


class TransitSafetyEvent(Base):
    __tablename__ = "transit_safety_events"
    id = Column(String(40), primary_key=True)
    bus_id = Column(String(16), ForeignKey("transit_vehicles.id"), nullable=False, index=True)
    camera_id = Column(String(16), ForeignKey("transit_cameras.id"), nullable=False, index=True)
    detection_event_id = Column(String(40), ForeignKey("transit_detection_events.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    category = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=False)
    status = Column(String(24), nullable=False, default="awaiting_review")
    note = Column(String(1000), nullable=False, default="")
    evidence = Column(JSON, nullable=False)


class TransitSafetyAction(Base):
    __tablename__ = "transit_safety_actions"
    id = Column(String(40), primary_key=True)
    event_id = Column(String(40), ForeignKey("transit_safety_events.id"), nullable=False, index=True)
    operator = Column(String(120), nullable=False)
    action = Column(String(24), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    note = Column(String(1000), nullable=False, default="")


class TransitNavigationRequest(Base):
    __tablename__ = "transit_navigation_requests"
    id = Column(String(40), primary_key=True)
    timestamp = Column(DateTime, nullable=False)
    route_provider = Column(String(40), nullable=False)
    origin = Column(JSON, nullable=False)
    destination = Column(JSON, nullable=False)
    selected_route_id = Column(String(40), nullable=True)
    options = Column(JSON, nullable=False)


class TransitGeoStop(Base):
    __tablename__ = "transit_geo_stops"
    stop_id = Column(String(16), ForeignKey("transit_stops.id"), primary_key=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    coordinate_source = Column(String(40), nullable=False)


class TransitAccount(Base):
    __tablename__ = "transit_accounts"
    username = Column(String(120), primary_key=True)
    password_hash = Column(String(240), nullable=False)
    role = Column(String(24), nullable=False)
    bus_id = Column(String(16), ForeignKey("transit_vehicles.id"), nullable=True)
    active = Column(Boolean, nullable=False, default=True)


class TransitBusSession(Base):
    __tablename__ = "transit_bus_sessions"
    bus_id = Column(String(16), ForeignKey("transit_vehicles.id"), primary_key=True)
    direction = Column(String(16), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    source = Column(String(40), nullable=False)
    operator = Column(String(120), nullable=False)
    updated_at = Column(DateTime, nullable=False)
