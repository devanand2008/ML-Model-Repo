// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DemoRecorderProvider, cuesToSrt, useDemoRecorder } from '../components/DemoRecorder';

afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});
function Controls(){const r=useDemoRecorder();const location=useLocation();return <><button onClick={()=>r.start(true)}>Capture</button><button onClick={r.stop}>Finish</button><output data-testid="location">{location.pathname}</output><output data-testid="recorded">{r.videoUrl}</output><output data-testid="captions">{r.srt}</output><p role="alert">{r.error}</p></>;}
function mount(){render(<MemoryRouter initialEntries={['/record-demo']}><DemoRecorderProvider><Controls/></DemoRecorderProvider></MemoryRouter>);}

describe('Full application recording',()=>{
  it('formats caption timings and excludes empty cues',()=>{
    expect(cuesToSrt([{start:1234,end:65234,text:'Actual recorded source.'},{start:80,end:80,text:'Skip'}])).toBe('1\n00:00:01,234 --> 00:01:05,234\nActual recorded source.\n');
  });
  it('requests screen capture only on click and reports denied permission',async()=>{
    const capture=vi.fn().mockRejectedValue(new Error('Screen sharing was cancelled.'));
    Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getDisplayMedia:capture}});
    vi.stubGlobal('MediaRecorder',class {});mount();expect(capture).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Capture'));await screen.findByText('Screen sharing was cancelled.');
    expect(capture).toHaveBeenCalledTimes(1);expect(screen.getByTestId('location').textContent).toBe('/record-demo');
  });
  it('records across app navigation and releases capture while retaining downloads',async()=>{
    const track={stop:vi.fn(),onended:null};
    Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getDisplayMedia:vi.fn().mockResolvedValue({getTracks:()=>[track],getVideoTracks:()=>[track]})}});
    class Recorder {
      static isTypeSupported(){return true;}state='inactive';ondataavailable:any;onstop:any;onerror:any;
      start(){this.state='recording';}stop(){this.state='inactive';this.ondataavailable?.({data:new Blob(['video'])});this.onstop?.();}
    }
    vi.stubGlobal('MediaRecorder',Recorder);
    Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn().mockReturnValue('blob:recording')});
    Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()});
    mount();fireEvent.click(screen.getByText('Capture'));
    await waitFor(()=>expect(screen.getByTestId('location').textContent).toBe('/'));
    fireEvent.click(screen.getByText('Next'));expect(screen.getByTestId('location').textContent).toBe('/ml');
    fireEvent.click(screen.getByText('Pause tour'));expect(screen.getByText(/Recording continues/)).toBeTruthy();
    await act(async()=>{fireEvent.click(screen.getByText('Finish'));});
    expect(track.stop).toHaveBeenCalled();expect(screen.getByTestId('recorded').textContent).toBe('blob:recording');
    expect(screen.getByTestId('location').textContent).toBe('/record-demo');
    expect(screen.getByTestId('captions').textContent).toContain('00:00:00,');
  });
});
