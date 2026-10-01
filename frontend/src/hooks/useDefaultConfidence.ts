import {useEffect,useState} from 'react';
import {api} from '../services/api';
export function useDefaultConfidence(type:string) {
 const state=useState(.5);const set=state[1];
 useEffect(()=>{let active=true;api.getModels().then(({models})=>{const m=models.find(m=>m.model_type===type&&m.is_default&&m.is_active);if(active&&m)set(m.confidence_threshold);}).catch(()=>{});return()=>{active=false;};},[type]);
 return state;
}
