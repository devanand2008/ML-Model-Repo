"""Create an honest captioned evidence video from actual API/model results.

This is a rendered demonstration, not an application screen capture. A user can
record the actual browser app via Record-Full-Demo.bat and its screen chooser.
"""
import base64
import io
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

import cv2
import httpx
import imageio_ffmpeg
import numpy as np
from dotenv import dotenv_values
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'deliverables'/'TransitOpt-Demo'
WIDTH,HEIGHT,FPS=1280,720,24
NAVY='#071827';PANEL='#102b41';CYAN='#49dfd1';WHITE='#edf7ff';MUTED='#a6c1d6'
FONT=Path('C:/Windows/Fonts/segoeui.ttf')
BOLD=Path('C:/Windows/Fonts/segoeuib.ttf')


def font(size,bold=False):return ImageFont.truetype(str(BOLD if bold else FONT),size)
def wrap(draw,text,width,face):
    lines=[];line=''
    for word in str(text).split():
        candidate=(line+' '+word).strip()
        if draw.textlength(candidate,font=face)>width and line:lines.append(line);line=word
        else:line=candidate
    return lines+[line]


def text(draw,value,x,y,size=23,color=WHITE,width=1100,bold=False):
    face=font(size,bold)
    for line in wrap(draw,value,width,face):draw.text((x,y),line,font=face,fill=color);y+=int(size*1.4)
    return y


def get_results():
    config=dotenv_values(ROOT/'.env')
    result={}
    with httpx.Client(base_url='http://127.0.0.1:8000',auth=(config['ADMIN_USERNAME'],config['ADMIN_PASSWORD']),timeout=150) as client:
        def call(method,path,**kwargs):
            response=client.request(method,path,**kwargs);response.raise_for_status();return response.json()
        result['health']=call('GET','/api/health')
        result['models']=call('GET','/api/models/status')
        result['ml']=call('GET','/api/ml/overview')
        for role,camera in [('road','CAM02'),('people','BUS_CAM_001')]:
            print('Running actual '+role+' inference...',flush=True)
            data=call('POST',f'/api/vision/samples/bus-image/analyze?camera_id={camera}')
            encoded=data.get('annotated_image') or data.get('processed_image')
            image=Image.open(io.BytesIO(base64.b64decode(encoded.split(',')[-1]))).convert('RGB')
            image.save(OUT/f'{role}-actual-inference.jpg')
            result[role]={k:data.get(k) for k in ['analysis_id','counts','model_info','processing_time','source','observation']}
        print('Running recorded video inference...',flush=True)
        job=call('POST','/api/vision/samples/bus-video/analyze?camera_id=CAM02')
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            state=call('GET',f"/api/vision/jobs/{job['job_id']}")
            if state['status'] in {'complete','completed'}:break
            if state['status'] in {'failed','cancelled'}:raise RuntimeError(state.get('error',state['status']))
            time.sleep(.5)
        else:raise RuntimeError('Video inference timed out')
        data=state.get('result',state)
        response=client.get(data['download_url']);response.raise_for_status();(OUT/'actual-annotated-sample.mp4').write_bytes(response.content)
        result['video']={k:data.get(k) for k in ['analysis_id','processed_frames','counts','video_encoding','source']}
        result['forecast']=call('POST','/api/demand/forecast',json={'route_id':'R02','horizon_minutes':60})
        settings=call('GET','/api/settings')['settings']
        body={k:settings[k] for k in ['fleet_size','reserve_fleet','horizon_minutes','max_headway_minutes','solver_time_limit_seconds']}
        body.update(name='Captioned ML demonstration',demand_multiplier=1.,traffic_level='current',event_intensity='none')
        result['optimization']=call('POST','/api/optimization/run',json=body)
        result['scenario']=call('POST','/api/simulator/run',json={**body,'name':'Video demonstration: demand plus 20 percent','demand_multiplier':1.2})
        try:
            result['navigation']=call('POST','/api/public/navigation/routes',json={
                'origin':{'latitude':11.6649,'longitude':78.146},'destination':{'latitude':11.6757,'longitude':78.1402},'goal':'lowest_observed_traffic'})
        except httpx.HTTPError as exc:result['navigation']={'routes':[],'provider_unavailable':str(exc).split('\n')[0]}
        result['buses']=call('GET','/api/public/buses')
        result['traffic']=call('GET','/api/public/traffic/feed')
        result['alerts']=call('GET','/api/alerts')
    (OUT/'actual-results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def timestamp(seconds):
    ms=round(seconds*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def make_video(data):
    road=data['road']['counts'];people=data['people']['counts'];plan=data['optimization'];forecast=data['forecast']
    cases=[
        ('TransitOpt AI: two camera ML uses','EVIDENCE WALKTHROUGH',
         ['One app: passenger, administrator and driver','Road cameras: vehicle detection and traffic scene pressure','Bus cameras: person detection and visible crowd estimates'],
         'This captioned evidence walkthrough uses actual API and model outputs. It is not a screen recording of the web app.',10,'intro'),
        ('Existing YOLO models','MODEL IDENTITY',
         [f"{m['type']}: {m['filename']} | weights available: {m['weights_available']}" for m in data['models']['detection_models'] if m['is_default'] and m['type'] in {'general','human'}]+['Camera inference runs on the laptop; phone frames use encrypted HTTPS / WSS.'],
         'The project uses its installed YOLO weights for both vehicle and person detection. Inference happens on the shared laptop server.',10,'models'),
        ('Road vehicle detection','ACTUAL YOLO OUTPUT',
         [f'{name}: {count}' for name,count in road.items()]+[f"Analysis #{data['road']['analysis_id']}",'Source: bundled recorded street image'],
         'YOLO detects visible objects in the bundled street image. Vehicle counts form a camera-local scene-pressure estimate.',12,'road'),
        ('Person detector / bus crowd pipeline','ACTUAL PERSON-ONLY OUTPUT',
         [f'{name}: {count}' for name,count in people.items()]+['Same street sample tests the person-only pipeline.','Actual bus interior footage is required for a real bus demonstration.'],
         'Person-only inference counts visible people. This sample is outdoors; it demonstrates the pipeline, not real bus occupancy.',12,'people'),
        ('Recorded video processing','ACTUAL ANNOTATED VIDEO',
         [f"Frames processed: {data['video']['processed_frames']}",'Bounding boxes and class counts come from real model inference.','The bundled clip repeats a still image. It is not live traffic.'],
         'The backend processes the sample video and creates a browser-playable annotated result. Repeated still frames are explicitly recorded demo footage.',12,'video'),
        ('Laptop + phone live camera','LIVE CAPTURE SETUP',
         ['Open /ml, select a registered camera, then Start Camera and Start Detection.','Fast mode uses 320 px inference and one frame in flight.','Preview FPS and model FPS are separate; hardware capture was not measured.'],
         'Laptop and phone camera controls are implemented. A real live demonstration requires device permission and a trusted phone HTTPS connection.',12,'camera'),
        ('One-minute traffic forecasting','LIVE DATA QUALITY GATE',
         ['Learner: Ridge autoregression over ten-second scene-pressure bins','Minimum: ten continuous minutes from one live road camera session','Forecast must beat persistence on a purged chronological holdout.','Current recorded samples do not train this live forecaster.'],
         'The live traffic learner predicts scene pressure only after enough continuous camera history and a successful validation check.',12,'forecast'),
        ('Passenger road routing','ACTUAL ROUTING RESPONSE',
         [f"Road routes returned: {len(data['navigation'].get('routes',[]))}",'Source: OSRM road graph, using illustrative Salem endpoints','Selected paths are monitored every five seconds for camera evidence.','No alternative is invented when the provider returns one path.'],
         'OSRM provides drivable road geometry. New camera pressure can recommend another available route, while the passenger chooses whether to switch.',12,'route'),
        ('Demand prediction','XGBOOST · SYNTHETIC TRANSIT HISTORY',
         [f"Route: {forecast.get('route_id','R02')} | Horizon: {forecast.get('horizon_minutes',60)} minutes",f"Predicted demand: {forecast.get('predicted_demand',forecast.get('predicted_passengers','See exported result'))}",'90-day reproducible dataset; temporal train / validation / test split','Synthetic boardings are separate from visible people counts.'],
         'XGBoost forecasts passenger demand from the labeled synthetic transit history. This planning forecast is separate from bus camera crowd counts.',12,'demand'),
        ('Fleet optimization + what-if','ACTUAL SOLVER RESULTS · SIMULATION',
         [f"Solver: {plan.get('solver_status')} | Feasible: {plan.get('feasible')}",f"Forecast demand: {plan.get('totals',{}).get('forecast_demand','Unavailable')}",f"Plus-20% scenario demand: {data['scenario'].get('totals',{}).get('forecast_demand','Unavailable')}",'Constraints include fleet, reserve, service headway and essential stops.'],
         'OR-Tools computes a constrained fleet plan and a demand-plus-20-percent scenario. These remain reviewable simulation outputs.',12,'solver'),
        ('Fleet, GPS and safety','PUBLIC AGGREGATES · PRIVATE REVIEW',
         [f"Public bus records: {len(data['buses']['buses'])}",f"Current shared traffic alerts: {len(data['traffic']['alerts'])}",f"Private safety records: {len(data['alerts'].get('alerts',data['alerts'].get('events',[])))}",'GPS freshness, camera coverage and incident context are shown explicitly.','No simulated GPS was published for this video.'],
         'Passengers receive aggregate bus and traffic information. Safety evidence stays with authorized operators, and stale GPS is labeled.',12,'fleet'),
        ('Start and record the actual app','DELIVERED LAUNCHERS',
         ['Start-TransitOpt-All.bat: run the complete web application','Run-On-Web.bat: open the same complete web app','Record-Full-Demo.bat: capture the actual app with on-screen captions','Run-TransitOpt-Phone.bat start: optional encrypted phone access'],
         'Use the full-app BAT file to run every module. To create the actual screen recording, open the guided recorder and select the TransitOpt browser tab.',12,'end'),
    ]
    output=OUT/'TransitOpt-ML-Working-Demo-Captioned.mp4'
    writer=imageio_ffmpeg.write_frames(str(output),(WIDTH,HEIGHT),fps=FPS,codec='libx264',
        pix_fmt_in='rgb24',pix_fmt_out='yuv420p',quality=8,macro_block_size=16,
        output_params=['-preset','fast','-movflags','+faststart'])
    writer.send(None)
    captions=[];chapters=[];elapsed=0
    frames=[];capture=cv2.VideoCapture(str(OUT/'actual-annotated-sample.mp4'))
    while True:
        ok,frame=capture.read()
        if not ok:break
        frames.append(Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)))
    capture.release()
    for index,(title,eyebrow,bullets,caption,duration,kind) in enumerate(cases):
        print(f'Rendering chapter {index+1}/{len(cases)}: {title}',flush=True)
        canvas=Image.new('RGB',(WIDTH,HEIGHT),NAVY);draw=ImageDraw.Draw(canvas)
        draw.rectangle((0,0,WIDTH,64),fill='#0b263b');text(draw,'TRANSITOPT AI',42,17,22,CYAN,bold=True)
        text(draw,'ACTUAL ML RESULTS  /  NOT A SCREEN RECORDING',590,23,14,MUTED)
        text(draw,eyebrow,46,92,14,CYAN,bold=True);text(draw,title,46,122,37,bold=True)
        draw.rounded_rectangle((38,190,1242,578),radius=16,fill=PANEL)
        visual=kind in {'road','people','video','route'}
        bx,by,bw=(700,220,500) if visual else (73,224,1120)
        for bullet in bullets:
            draw.ellipse((bx,by+9,bx+7,by+16),fill=CYAN)
            by=text(draw,bullet,bx+23,by,23,MUTED,bw-26)+15
        if kind in {'road','people'}:
            picture=Image.open(OUT/f'{kind}-actual-inference.jpg');picture.thumbnail((600,356));canvas.paste(picture,(62+(600-picture.width)//2,207+(356-picture.height)//2))
        if kind=='route' and data['navigation'].get('routes'):
            geometry=data['navigation']['routes'][0]['geometry'];xs=[p[0] for p in geometry];ys=[p[1] for p in geometry]
            points=[(85+(x-min(xs))/max(max(xs)-min(xs),.00001)*510,528-(y-min(ys))/max(max(ys)-min(ys),.00001)*285) for x,y in geometry]
            draw.line(points,fill=CYAN,width=6)
            for label,p in [('A',points[0]),('B',points[-1])]:draw.ellipse((p[0]-16,p[1]-16,p[0]+16,p[1]+16),fill='#1c7894');draw.text((p[0]-7,p[1]-13),label,font=font(20,True),fill=WHITE)
            text(draw,'OSRM geometry · no map tile basemap',84,550,13,MUTED)
        draw.rectangle((0,601,WIDTH,697),fill='#020d17')
        for line_no,line in enumerate(wrap(draw,caption,1170,font(22))):
            draw.text(((WIDTH-draw.textlength(line,font=font(22)))/2,612+line_no*30),line,font=font(22),fill=WHITE)
        text(draw,f'{index+1:02} / {len(cases):02}     Recorded sample evidence | Synthetic planning labeled',45,698,11,MUTED)
        preview=canvas.copy();preview.save(OUT/f'chapter-{index+1:02}.jpg')
        for n in range(duration*FPS):
            image=canvas.copy()
            if kind=='video' and frames:
                picture=frames[(n//2)%len(frames)].copy();picture.thumbnail((600,356));image.paste(picture,(62+(600-picture.width)//2,207+(356-picture.height)//2))
            d=ImageDraw.Draw(image);d.rectangle((0,HEIGHT-4,int(WIDTH*(elapsed+n/FPS)/sum(c[4] for c in cases)),HEIGHT),fill=CYAN)
            writer.send(np.asarray(image))
        captions.append(f'{index+1}\n{timestamp(elapsed)} --> {timestamp(elapsed+duration)}\n{caption}\n')
        chapters.append({'start_seconds':elapsed,'duration_seconds':duration,'title':title})
        elapsed+=duration
    writer.close()
    (OUT/'TransitOpt-ML-Demo-Captions.srt').write_text('\n'.join(captions),encoding='utf-8')
    (OUT/'chapters.json').write_text(json.dumps({'duration_seconds':elapsed,'fps':FPS,'resolution':[WIDTH,HEIGHT],'chapters':chapters},indent=2),encoding='utf-8')
    # A selectable caption track is included in addition to burned-in captions.
    muxed=OUT/'TransitOpt-ML-Working-Demo-With-Subtitles.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y','-i',str(output),'-i',str(OUT/'TransitOpt-ML-Demo-Captions.srt'),'-map','0:v','-map','1:0','-c:v','copy','-c:s','mov_text','-metadata:s:s:0','language=eng','-movflags','+faststart',str(muxed)],check=True)
    print(json.dumps({'video':str(muxed),'duration_seconds':elapsed,'bytes':muxed.stat().st_size}),flush=True)


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    make_video(get_results())
