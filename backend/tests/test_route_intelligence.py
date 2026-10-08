"""Meaningful ML holdout, missing-data and newly congested route checks."""
from datetime import datetime, timedelta
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from transit.traffic_forecasting import forecast_samples
from transit.route_intelligence import annotate_routes, route_id


def samples(values):
    now=datetime(2026,10,8,12,0,0)
    return [(now-timedelta(seconds=(len(values)-i)*10-1),score) for i,score in enumerate(values)],now


def test_forecast_requires_continuous_history_and_wins_a_purged_holdout():
    history,now=samples(np.linspace(10,80,90))
    output=forecast_samples(history,now)
    assert output['available'] is True
    assert output['validation_mae'] < output['persistence_mae']*.95
    assert output['predicted_score'] > output['current_score']
    assert output['horizon_seconds']==60
    assert output['training_samples']+6+output['validation_samples']==79
    history.pop(-20)
    broken=forecast_samples(history,now)
    assert broken['available'] is False
    assert broken['history_bins']==19


def test_stable_history_does_not_claim_a_better_ml_forecast():
    history,now=samples([30]*90)
    output=forecast_samples(history,now)
    assert output['status']=='baseline_preferred'
    assert output['available'] is False
    assert output['persistence_mae']==0
    history,now=samples([20]*20)
    assert forecast_samples(history,now)['status']=='collecting'

def test_median_bins_resist_single_frame_spikes_and_tuning_leaves_outer_holdout_untouched():
    now=datetime(2026,10,8,12,0,0)
    rows=[]
    for i in range(90):
        start=now-timedelta(seconds=(90-i)*10)
        value=10+i*.7
        rows.extend([(start+timedelta(seconds=second),score) for second,score in [(1,value),(3,value),(5,100)]])
    result=forecast_samples(rows,now)
    assert result['available']
    assert result['current_score']==round(10+89*.7,1)
    assert result['selected_alpha'] in [1,10,100]
    assert result['training_samples']+6+result['validation_samples']==79
    assert result['validation_mae']<result['persistence_mae']*.95
    assert 'inner chronological' in result['tuning']

def test_small_ranking_changes_do_not_switch_the_selected_path():
    paths=[{'id':'selected','geometry':[[78,11],[78.1,11.1]],'distance_km':4,'base_duration_minutes':10},
           {'id':'slightly-faster','geometry':[[78,11],[78.2,11.1]],'distance_km':3.95,'base_duration_minutes':9.8}]
    for goal in ['fastest','lowest_observed_traffic','shortest']:
        result=annotate_routes(paths,[],'selected',goal)
        assert result['recommended_route_id']=='selected'
        assert result['ranked_first_route_id']=='slightly-faster'
        assert not result['alternative_available']
        assert 'too small' in result['recommendation_reason']


def test_new_camera_traffic_reranks_real_paths_without_changing_the_selection():
    paths=[{'id':'chosen','geometry':[[78.10,11.67],[78.20,11.67]],'distance_km':10,'base_duration_minutes':10},
           {'id':'alternative','geometry':[[78.10,11.69],[78.20,11.69]],'distance_km':11,'base_duration_minutes':11}]
    camera={'id':'SIGNAL','name':'Signal camera','latitude':11.67,'longitude':78.15,
        'coordinate_source':'operator_configured','prediction':{'available':False},
        'observation':{'fresh':True,'live':True,'source':'REAL_MODEL_DETECTION','score':90,
                       'category':'SEVERE','timestamp':'2026-10-08T12:00:00Z'}}
    result=annotate_routes(paths,[camera],'chosen')
    assert result['selected_route_id']=='chosen'
    assert result['recommended_route_id']=='alternative'
    assert result['route_alerts'][0]['camera_id']=='SIGNAL'
    assert result['routes'][0]['geometry']==paths[0]['geometry']
    assert result['routes'][0]['observed_camera_count']==1
    assert result['alternative_available'] is True
    camera['observation']['live']=False
    camera['observation']['observation_type']='recorded_detection'
    recorded=annotate_routes(paths,[camera],'chosen')
    assert recorded['recommended_route_id']=='chosen'
    assert recorded['route_alerts']==[]
    assert recorded['routes'][0]['comparison_minutes']==10
    assert annotate_routes(paths,[camera],'chosen',recorded_demo=True)['recommended_route_id']=='alternative'
    # A provider ordering change retains the identity of a fixed path.
    assert route_id(paths[0]['geometry']) != route_id(paths[1]['geometry'])


def test_validated_forecast_can_raise_route_pressure_before_current_high_counts():
    path={'id':'route','geometry':[[78.14,11.67],[78.15,11.67]],'distance_km':1,'base_duration_minutes':4}
    camera={'id':'CAM','latitude':11.67,'longitude':78.145,'coordinate_source':'operator_configured',
        'prediction':{'available':True,'predicted_score':80},
        'observation':{'fresh':True,'live':True,'source':'REAL_MODEL_DETECTION','score':20,
                       'category':'LOW','timestamp':'2026-10-08T12:00:00Z'}}
    output=annotate_routes([path],[camera])
    assert output['route_alerts']
    assert output['routes'][0]['camera_comparison_penalty_minutes']==1.6


def test_avoid_traffic_prioritizes_observed_pressure_and_keeps_unknown_coverage_explicit():
    paths = [dict(id='busy', geometry=[[78.1, 11.67], [78.2, 11.67]], distance_km=2, base_duration_minutes=4),
             dict(id='uncovered', geometry=[[78.1, 11.69], [78.2, 11.69]], distance_km=8, base_duration_minutes=12)]
    camera = dict(id='signal', latitude=11.67, longitude=78.15, coordinate_source='operator_configured',
                  observation=dict(fresh=True, live=True, source='REAL_MODEL_DETECTION', score=90,
                                   category='SEVERE', timestamp='2026-10-09T00:00:00Z'))
    avoiding = annotate_routes(paths, [camera], goal='lowest_observed_traffic')
    assert avoiding['selected_route_id'] == 'uncovered'
    assert avoiding['routes'][0]['high_pressure_camera_count'] == 1
    assert avoiding['routes'][1]['traffic_coverage'] == 'unknown'
    assert avoiding['routes'][1]['observed_camera_count'] == 0
    assert annotate_routes(paths, [camera], goal='fastest')['selected_route_id'] == 'busy'
    camera['observation']['fresh'] = False
    stale = annotate_routes(paths, [camera], goal='lowest_observed_traffic')
    assert stale['selected_route_id'] == 'busy'
    assert stale['route_alerts'] == []
    assert stale['routes'][0]['high_pressure_camera_count'] == 0
