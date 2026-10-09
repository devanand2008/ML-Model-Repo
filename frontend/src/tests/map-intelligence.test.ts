import { describe, expect, it } from 'vitest';
import { distanceMeters, distanceToPath, rankTrafficPlaces, trafficEvidence } from '../services/mapIntelligence';

const now=Date.parse('2026-10-09T05:00:00Z');
const camera=(id:string,score:number,extra:Record<string,unknown>={})=>({id,name:id,latitude:11.67,longitude:78.14,
  coordinate_source:'operator_configured',camera_role:'road_traffic',observation:{live:true,fresh:true,source:'REAL_MODEL_DETECTION',
    timestamp:new Date(now-10000).toISOString(),score,category:score>=75?'SEVERE':score>=50?'HIGH':score>=25?'MODERATE':'LOW'},...extra});

describe('Traffic map evidence',()=>{
  it('ranks located live cameras and uses pressure colors instead of one online color',()=>{
    const places=rankTrafficPlaces([camera('busy',85),camera('quiet',10),camera('medium',40)],now);
    expect(places.map(place=>place.id)).toEqual(['quiet','medium','busy']);
    expect(trafficEvidence(places[0],now).color).toBe('#16a34a');
    expect(trafficEvidence(places[2],now).color).toBe('#dc2626');
  });
  it('does not label stale, recorded, invalid or approximately located evidence as minimum traffic',()=>{
    const valid=camera('valid',30);
    const base=camera('old',1);
    const unknown=[camera('approximate',0,{coordinate_source:'illustrative_demo_coordinate'}),
      {...base,observation:{...base.observation,timestamp:new Date(now-301000).toISOString()}},
      {...base,id:'recorded',observation:{...base.observation,live:false}},
      camera('invalid',5,{latitude:100}), {...base,id:'score',observation:{...base.observation,score:-1}}];
    expect(rankTrafficPlaces([...unknown,valid],now).map(item=>item.id)).toEqual(['valid']);
    for(const item of unknown)expect(trafficEvidence(item,now).category).toBe('UNKNOWN');
  });
  it('expires moving-bus captures after twenty seconds',()=>{
    const moving=camera('bus',10,{coordinate_source:'bus_gps_at_capture',camera_role:'bus_road'});
    expect(trafficEvidence(moving,now).available).toBe(true);
    expect(trafficEvidence(moving,now+11000).available).toBe(false);
  });
  it('measures movement and off-route distance without inventing a travel time',()=>{
    expect(distanceMeters({latitude:11.67,longitude:78.14},{latitude:11.67,longitude:78.14})).toBe(0);
    expect(distanceMeters({latitude:11.67,longitude:78.14},{latitude:11.671,longitude:78.14})).toBeCloseTo(111.2,0);
    expect(distanceToPath({latitude:11.67,longitude:78.145},[[78.14,11.67],[78.15,11.67]])).toBeCloseTo(0);
    expect(distanceToPath({latitude:11.671,longitude:78.145},[[78.14,11.67],[78.15,11.67]])).toBeCloseTo(111.32);
  });
});
