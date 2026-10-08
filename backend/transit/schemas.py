"""Validated request schemas for the additive REST API."""
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class ForecastRequest(BaseModel):
    route_id: str = Field("R02",pattern=r"^R0[1-8]$")
    stop_id: str | None = None
    horizon_minutes: Literal[30,60,120] = 60
    forecast_at: str | None = None


class OptimizationRequest(BaseModel):
    name: str | None = Field(None,max_length=160)
    fleet_size: int | None = Field(None,ge=1,le=200)
    reserve_fleet: int | None = Field(None,ge=0,le=100)
    bus_capacity: int | None = Field(None,ge=1,le=150)
    horizon_minutes: Literal[30,60,120] = 60
    demand_multiplier: float = Field(1,ge=0.1,le=3)
    traffic_level: Literal["current","low","medium","high"] = "current"
    event_intensity: Literal["none","moderate","high"] = "none"
    solver_time_limit_seconds: float = Field(5,ge=0.1,le=30)
    max_headway_minutes: float | None = Field(None,ge=5,le=120)
    weights: dict[str,float] | None = None


class OperatorRequest(BaseModel):
    note: str = Field("",max_length=1000)


class CameraRequest(BaseModel):
    roi: list[float] | None = None

    @model_validator(mode="after")
    def validate_roi(self):
        if self.roi is not None:
            if len(self.roi)!=4 or any(v<0 or v>1 for v in self.roi) or self.roi[2]<=0 or self.roi[3]<=0 or self.roi[0]+self.roi[2]>1 or self.roi[1]+self.roi[3]>1:
                raise ValueError("ROI must be normalized [x,y,width,height] within the image")
        return self


class SettingsRequest(BaseModel):
    fleet_size: int | None = Field(None,ge=1,le=200)
    reserve_fleet: int | None = Field(None,ge=0,le=100)
    bus_capacity: int | None = Field(None,ge=1,le=150)
    horizon_minutes: Literal[30,60,120] | None = None
    max_headway_minutes: float | None = Field(None,ge=5,le=120)
    solver_time_limit_seconds: float | None = Field(None,ge=.1,le=30)
    vision_density_reference_vehicles: int | None = Field(None,ge=1,le=500)
    default_confidence: float | None = Field(None,ge=.1,le=.95)
    traffic_thresholds: dict[str,float] | None = None
    crowd_visible_thresholds: dict[str,int] | None = None

    @model_validator(mode="after")
    def thresholds(self):
        if self.traffic_thresholds is not None:
            values=self.traffic_thresholds
            if set(values)!={"moderate","high","severe"} or not 0<values["moderate"]<values["high"]<values["severe"]<=100:
                raise ValueError("Traffic thresholds must satisfy 0 < moderate < high < severe <= 100")
        if self.crowd_visible_thresholds is not None:
            values=self.crowd_visible_thresholds
            if set(values)!={"moderate","high","critical"} or not 0<values["moderate"]<values["high"]<values["critical"]<=300:
                raise ValueError("Visible crowd thresholds must satisfy 0 < moderate < high < critical <= 300")
        return self
