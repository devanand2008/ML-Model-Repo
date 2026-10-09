"""Verify installed modules and real ML/API flows without activating service plans."""
import argparse,json,ssl,time
from pathlib import Path
import httpx
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1]

def main(base_url='http://127.0.0.1:8000',public=False):
    config=dotenv_values(ROOT/'.env');report={'checks':{},'plans_activated':False,
        'device_validation':'Physical webcam/GPS permissions require checks on the device.'}
    report['base_url']=base_url;report['public_no_login']=public
    with httpx.Client(base_url=base_url,auth=None if public else (config['ADMIN_USERNAME'],config['ADMIN_PASSWORD']),timeout=180) as client:
        def call(method,path,**kwargs):
            response=client.request(method,path,**kwargs);response.raise_for_status();return response.json()
        for path in ['/api/health','/api/system/status','/api/models/status','/api/network','/api/cameras',
            '/api/public/stops','/api/public/buses','/api/buses','/api/accounts','/api/alerts','/api/recommendations',
            '/api/dashboard/analytics','/api/traffic/summary','/api/traffic/speed','/api/settings',
            '/api/demand/forecasts','/api/simulator/scenarios','/api/public/rag/status','/api/vision/samples']:
            call('GET',path);report['checks'][path]='passed'
        print('Module APIs passed.',flush=True)
        pages=['/','/admin','/ml','/webcam','/passenger','/driver','/fleet','/safety','/speed','/rag','/status',
            '/cctv','/demand','/optimization','/network','/simulator','/recommendations','/analytics','/settings',
            '/accounts','/models','/history','/image','/human','/ship','/container','/combined','/video','/project','/record-demo','/connect']
        for path in pages:
            response=client.get(path);response.raise_for_status();assert '<div id="root">' in response.text
        report['web_page_entry_points']=len(pages)
        for role,camera in [('vehicles','CAM02'),('people','BUS_CAM_001')]:
            result=call('POST','/api/vision/samples/bus-image/analyze',params={'camera_id':camera})
            assert result['source']=='REAL_MODEL_DETECTION'
            report[role]={'counts':result['counts'],'model':result['model_info']}
        job=call('POST','/api/vision/samples/bus-video/analyze',params={'camera_id':'CAM02'})
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            state=call('GET','/api/vision/jobs/'+job['job_id'])
            if state['status'] in {'complete','completed'}:break
            if state['status'] in {'failed','cancelled','canceled'}:raise RuntimeError('Video job failed: '+str(state.get('error')))
            time.sleep(.5)
        else:raise RuntimeError('Video job timed out')
        result=state.get('result',state);report['video']={'status':state['status'],'processed_frames':result.get('processed_frames')}
        print('Image, people and video inference passed.',flush=True)
        for horizon in [30,60,120]:
            forecast=call('POST','/api/demand/forecast',json={'route_id':'R02','horizon_minutes':horizon})
            report['checks']['forecast_'+str(horizon)]='passed'
        config=call('GET','/api/settings')['settings']
        plan=call('POST','/api/optimization/run',json={k:config[k] for k in ['fleet_size','reserve_fleet','bus_capacity','horizon_minutes','max_headway_minutes','solver_time_limit_seconds']})
        assert plan['feasible'];report['optimizer']={'status':plan['solver_status'],'run_id':plan.get('run_id',plan.get('id'))}
        scenario=call('POST','/api/simulator/run',json={'name':'Full-app verification','demand_multiplier':1.2,'horizon_minutes':60})
        scenario_id=scenario.get('scenario_id',scenario.get('id'))
        for kind in ['json','csv']:
            response=client.get(f'/api/exports/scenarios/{scenario_id}',params={'format':kind});response.raise_for_status();assert response.content
        report['scenario_exports']='JSON and CSV passed'
        routes=call('POST','/api/public/navigation/routes',json={'origin':{'latitude':11.6649,'longitude':78.1460},
            'destination':{'latitude':11.6940,'longitude':78.1630},'goal':'lowest_observed_traffic','save':False})
        report['road_options']=len(routes['routes'])
        for endpoint,extra in [('/api/public/rag/ask',{}),('/api/rag/bus-advice',{'bus_id':'BUS005'})]:
            answer=call('POST',endpoint,json={'question':'Which road route is recommended?' if not extra else 'Can BUS005 change its route?',
                'route_context_id':routes['route_context_id'],**extra})
            assert answer['generation_mode']=='local_neural_constrained'
            assert answer['answer']==next(s['text'] for s in answer['sources'] if s['id']==answer['answer_source_id'])
            assert not answer['actions_taken'];report['checks'][endpoint]='actual local neural inference passed'
        report['limitations']=['Road and bus demo geography is illustrative. Demand training data is synthetic.',
            'Specialized container/condition weights and authorized RTSP feeds are not installed.',
            'Physical camera/GPS and field accuracy were not measured by this API check.']
    address_file=ROOT/'data/phone_tls/address.txt'
    if not public and address_file.exists():
        address=address_file.read_text().strip()
        with httpx.Client(verify=ssl.create_default_context(cafile=str(ROOT/'data/phone_tls/transitopt-phone-ca.crt')),timeout=15,trust_env=False) as phone:
            response=phone.get(f'https://{address}:8443/api/health');response.raise_for_status();report['phone_gateway']='trusted HTTPS passed'
    path=ROOT/'data/demo_exports'/('public-app-verification.json' if public else 'full-app-verification.json');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed_api_checks':len(report['checks']),'web_pages':report['web_page_entry_points'],'road_options':report['road_options'],
        'optimizer':report['optimizer']['status'],'report':str(path),'plans_activated':False}),flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    parser.add_argument('--public',action='store_true',help='Test the hosted public-admin gateway without credentials')
    args=parser.parse_args()
    main(args.base_url.rstrip('/'),args.public)
