"""Compare old/new scene learners on labeled synthetic robustness fixtures."""
import json,sys
from pathlib import Path
from datetime import datetime,timedelta
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from transit.traffic_forecasting import forecast_samples

def previous_forecast(values):
    def feature(window):return [window[-1],window[-2],window[-3],np.mean(window),window[-1]-window[-3],np.std(window)]
    x=np.array([feature(values[i-5:i+1]) for i in range(5,len(values)-6)]);y=values[11:]
    split=int(len(x)*.8);model=make_pipeline(StandardScaler(),Ridge(alpha=10))
    model.fit(x[:split-6],y[:split-6]);error=np.mean(np.abs(np.clip(model.predict(x[split:]),0,100)-y[split:]))
    baseline=np.mean(np.abs(x[split:,0]-y[split:]))
    if baseline<1 or error>=baseline*.95:return float(values[-1])
    model.fit(x,y);return float(np.clip(model.predict([feature(values[-6:])])[0],0,100))

def main():
    now=datetime(2026,10,9,12);cases=[]
    for name,trend,spike in [('clean_rising',True,False),('rising_with_spikes',True,True),('steady_with_spikes',False,True)]:
        state=10+np.arange(96)*.55 if trend else np.full(96,30.)
        rows=[];old_values=[]
        for i in range(90):
            observations=[float(state[i]),float(state[i]),100. if spike else float(state[i])]
            old_values.append(np.mean(observations))
            start=now-timedelta(seconds=(90-i)*10)
            rows.extend((start+timedelta(seconds=second),score) for second,score in zip([1,3,5],observations))
        new=forecast_samples(rows,now)
        estimate=new.get('predicted_score',float(np.median([rows[-j][1] for j in (1,2,3)])))
        old=previous_forecast(np.array(old_values));target=float(state[95])
        cases.append({'fixture':name,'target_score':round(target,3),'previous_prediction':round(old,3),
            'updated_prediction':estimate,'previous_absolute_error':round(abs(old-target),3),
            'updated_absolute_error':round(abs(estimate-target),3),'updated_status':new['status'],
            'selected_alpha':new.get('selected_alpha'),'validation_mae':new.get('validation_mae')})
    report={'source':'LABELED_SYNTHETIC_ROBUSTNESS_FIXTURES','field_accuracy_claim':False,
        'comparison':'Previous mean bins / Ridge alpha 10 versus median bins / inner chronological alpha tuning',
        'note':'Three controlled cases illustrate spike robustness; they do not establish field accuracy or general superiority.',
        'cases':cases}
    path=ROOT/'data'/'demo_exports'/'scene-forecast-robustness.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
