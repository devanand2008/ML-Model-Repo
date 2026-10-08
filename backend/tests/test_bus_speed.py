"""GPS quality, sustained fusion and moving-camera missing-data contracts."""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from transit.bus_speed import speed_from_fixes, fuse_speed
from transit.vision import summarize
from transit.traffic_forecasting import forecast_samples
from transit.traffic_forecasting import local_history

NOW=datetime(2026,10,9,12,0,0)
def fix(**kw):
    return SimpleNamespace(**({'timestamp':NOW,'source':'browser_geolocation','accuracy_m':5,
        'speed_kmh':5,'latitude':11.67,'longitude':78.14}|kw))
def counts(n=3):
    return summarize([{'class':'bus' if i==0 else 'car','confidence':.9,'bbox':[0,0,10,10]} for i in range(n)],320,240)

@pytest.mark.parametrize('change',[{'timestamp':NOW-timedelta(seconds=21)}, {'timestamp':NOW+timedelta(seconds=1)},
    {'source':'demo_simulation'},{'accuracy_m':None},{'accuracy_m':80}])
def test_bad_gps_never_publishes_speed(change):
    assert not speed_from_fixes(fix(**change),None,NOW)['available']

def test_reported_and_displacement_speed_have_explicit_units_and_uncertainty():
    assert speed_from_fixes(fix(speed_kmh=36),None,NOW)['speed_kmh']==36
    previous=fix(timestamp=NOW-timedelta(seconds=10),speed_kmh=None)
    result=speed_from_fixes(fix(speed_kmh=None,latitude=11.6709),previous,NOW)
    assert result['source']=='gps_displacement_estimate'
    assert 35<result['speed_kmh']<37
    assert result['lower_speed_kmh']<result['speed_kmh']<result['upper_speed_kmh']
    jitter=speed_from_fixes(fix(speed_kmh=None),fix(timestamp=NOW-timedelta(seconds=10),accuracy_m=30),NOW)
    assert jitter['speed_kmh']==0 and jitter['upper_speed_kmh']>10

def observe(seconds=10,n=3,source='browser_camera',session='one',same_fix=False):
    previous=None;result=None
    for i in range(seconds+1):
        now=NOW+timedelta(seconds=i)
        gps=fix(timestamp=NOW+timedelta(seconds=0 if same_fix else i//5*5))
        result=fuse_speed(counts(n),speed_from_fixes(gps,None,now),previous,now,session,source)
        previous=result['speed_observation']
    return result

def test_slow_bus_and_density_require_repeated_gps_and_continuous_live_frames():
    result=observe()
    assert result['congestion_score']==70
    assert result['speed_observation']['suspected_queue']
    assert result['average_speed_kmh'] is None  # Never call bus GPS the surrounding traffic speed.
    for invalid in (observe(n=1),observe(source='video'),observe(same_fix=True),observe(seconds=4)):
        assert not invalid['speed_observation']['suspected_queue']
    for at,session in [(20,'one'),(11,'other')]:
        now=NOW+timedelta(seconds=at)
        reset=fuse_speed(counts(),speed_from_fixes(fix(timestamp=now),None,now),result['speed_observation'],now,session,'browser_camera')
        assert not reset['speed_observation']['suspected_queue']
    cleared=fuse_speed(counts(),{'available':False},result['speed_observation'],NOW+timedelta(seconds=11),'one','browser_camera')
    assert cleared['congestion_score']==15 and not cleared['speed_observation']['suspected_queue']

def test_speed_accuracy_range_must_also_be_slow():
    speed={'available':True,'speed_kmh':0,'upper_speed_kmh':15,'timestamp':'fix'}
    assert not fuse_speed(counts(),speed,None,NOW,'one','browser_camera')['speed_observation']['slow_since']

def test_forecast_accepts_count_and_speed_features_without_promising_improvement():
    rows=[(NOW-timedelta(seconds=(90-i)*10-1),30,{'vehicle_count':6,'speed_observation':{'available':True,'speed_kmh':20}}) for i in range(90)]
    result=forecast_samples(rows,NOW)
    assert result['version']=='scene-pressure-speed-v2'
    assert not result['available'] and result['status']=='baseline_preferred'


def test_moving_camera_learning_resets_between_roads_or_missing_gps():
    point={'latitude':11.67,'longitude':78.14}
    close=(NOW,20,{'capture_location':point})
    far=(NOW,80,{'capture_location':{'latitude':11.69,'longitude':78.14}})
    assert local_history([close,far,close,close],point)==[close,close]
    assert local_history([close,(NOW,30,{}),close],point)==[close]
