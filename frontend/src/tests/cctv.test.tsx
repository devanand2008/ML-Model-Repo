// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TransitProvider } from '../components/transit/Shared';
import CCTVPage from '../pages/transit/CCTVPage';
import { patchTransit, postTransit, transitRequest, uploadVision } from '../services/transit';

const state = vi.hoisted(() => ({ job: { job_id: 'recorded-job', status: 'processing', progress: 33, frame: 10, total: 30 }, roi: null as number[] | null }));

vi.mock('../services/api', () => ({ BASE_URL: '', request: vi.fn(async () => ({ ok: true, blob: async () => new Blob(['processed video'], { type: 'video/mp4' }) })) }));
vi.mock('../services/transit', async importOriginal => {
  const actual = await importOriginal<typeof import('../services/transit')>();
  return { ...actual, transitRequest: vi.fn(async (path: string) => {
    if (path === '/api/cameras') return { cameras: [{ id: 'CAM01', name: 'New Bus Stand demo camera', stop_id: 'S01', corridor_id: 'C01', roi: state.roi, status: 'awaiting_authorized_input' }], capabilities: { rtsp: false } };
    if (path === '/api/vision/samples') return { samples: [{ id: 'bus-image', name: 'Bundled bus image', type: 'image', provenance: 'Authorized bundled image' }] };
    if (path === '/api/models/status') return { detection_models: [{ type: 'general', classes: ['person', 'car', 'bus', 'truck', 'motorcycle', 'bicycle'] }] };
    if (path.includes('/api/vision/jobs/')) return { ...state.job };
    return { events: [] };
  }), postTransit: vi.fn(), patchTransit: vi.fn(), uploadVision: vi.fn() };
});

vi.mock('recharts', () => {
  const Container = ({ children }: any) => <div>{children}</div>;
  const Blank = () => null;
  return { ResponsiveContainer: Container, LineChart: Container, Line: Blank, CartesianGrid: Blank,
    Legend: Blank, Tooltip: Blank, XAxis: Blank, YAxis: Blank };
});

beforeEach(() => {
  state.job = { job_id: 'recorded-job', status: 'processing', progress: 33, frame: 10, total: 30 };
  state.roi = null;
  URL.createObjectURL = vi.fn(() => 'blob:authorized-preview');
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => { cleanup(); vi.mocked(postTransit).mockReset(); vi.mocked(patchTransit).mockReset(); vi.mocked(uploadVision).mockReset(); });

function mountPage() {
  return render(<MemoryRouter><TransitProvider><CCTVPage /></TransitProvider></MemoryRouter>);
}

describe('CCTV intelligence page', () => {
  it('uploads a video, polls real job progress, and sends pause/resume/stop controls', async () => {
    vi.mocked(uploadVision).mockResolvedValue({ job_id: 'recorded-job', status: 'queued', progress: 0 });
    vi.mocked(postTransit).mockImplementation(async path => {
      if (path.endsWith('/pause')) state.job.status = 'paused';
      if (path.endsWith('/resume')) state.job.status = 'processing';
      if (path.endsWith('/cancel')) state.job.status = 'cancelled';
      return { ...state.job };
    });
    mountPage();
    await screen.findByRole('option', { name: 'New Bus Stand demo camera' });
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    const recording = new File(['authorized video'], 'traffic.mp4', { type: 'video/mp4' });
    fireEvent.change(screen.getByLabelText('Choose image or recorded video'), { target: { files: [recording] } });
    fireEvent.click(screen.getByRole('button', { name: 'Start detection' }));
    await waitFor(() => expect(uploadVision).toHaveBeenCalledWith(recording, 'CAM01', 0.5));
    expect(await screen.findByText(/10 \/ 30 frames · 33%/, {}, { timeout: 2500 })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    expect(await screen.findByText('PAUSED')).toBeTruthy();
    expect(postTransit).toHaveBeenCalledWith('/api/vision/jobs/recorded-job/pause');
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }));
    expect(await screen.findByText('PROCESSING')).toBeTruthy();
    expect(postTransit).toHaveBeenCalledWith('/api/vision/jobs/recorded-job/resume');
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(await screen.findByText('CANCELLED')).toBeTruthy();
    expect(postTransit).toHaveBeenCalledWith('/api/vision/jobs/recorded-job/cancel');
    const pollsAtStop = vi.mocked(transitRequest).mock.calls.filter(([path]) => path.includes('/vision/jobs/')).length;
    await new Promise(resolve => setTimeout(resolve, 1100));
    expect(vi.mocked(transitRequest).mock.calls.filter(([path]) => path.includes('/vision/jobs/')).length).toBe(pollsAtStop);
  });

  it('persists camera ROI and renders independently switchable actual detection overlays', async () => {
    vi.mocked(patchTransit).mockImplementation(async (_path, data: any) => { state.roi = data.roi; return { id: 'CAM01', roi: data.roi }; });
    vi.mocked(postTransit).mockResolvedValue({
      source: 'REAL_MODEL_DETECTION', image_width: 640, image_height: 480,
      processed_image: 'data:image/jpeg;base64,source', annotated_image: 'data:image/jpeg;base64,annotated',
      supported_classes: ['person', 'car', 'bus', 'truck', 'motorcycle', 'bicycle'],
      detections: [{ class: 'person', confidence: 0.9, bbox: [20, 30, 40, 100] }],
      observation: { class_counts: { person: 1, car: 2 }, people_count: 1, vehicle_count: 2,
        mean_people_per_frame: 1, mean_vehicles_per_frame: 2, congestion_score: 10,
        congestion_category: 'LOW', confidence_mean: 0.9, roi: [0.1, 0.2, 0.4, 0.3] },
    });
    mountPage();
    await screen.findByRole('option', { name: 'New Bus Stand demo camera' });
    fireEvent.click(screen.getByLabelText('Enable crowd ROI'));
    for (const [label, value] of [['X', '0.1'], ['Y', '0.2'], ['Width', '0.4'], ['Height', '0.3']]) fireEvent.change(screen.getByLabelText(`ROI ${label}`), { target: { value } });
    expect((screen.getByRole('button', { name: 'Start detection' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Save camera ROI' }));
    await waitFor(() => expect(patchTransit).toHaveBeenCalledWith('/api/cameras/CAM01', { roi: [0.1, 0.2, 0.4, 0.3] }));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Start detection' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Start detection' }));
    expect(await screen.findByText('person 90%')).toBeTruthy();
    expect(postTransit).toHaveBeenCalledWith('/api/vision/samples/bus-image/analyze?camera_id=CAM01&confidence=0.5');
    expect(screen.getByLabelText('Detection overlays').querySelectorAll('rect').length).toBe(2);
    fireEvent.click(screen.getByLabelText('Show bounding boxes'));
    expect(screen.getByLabelText('Detection overlays').querySelectorAll('rect').length).toBe(1);
    expect(screen.getByText('person 90%')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Show labels'));
    expect(screen.queryByText('person 90%')).toBeNull();
    expect(screen.getByText('Physical vehicle speed')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open browser camera' }).getAttribute('href')).toBe('/webcam?camera_id=CAM01&mode=general');
  });
});
