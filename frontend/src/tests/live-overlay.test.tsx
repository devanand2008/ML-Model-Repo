// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { drawDetectionOverlay } from '../pages/LiveCameraPage';

function drawingSurface() {
  const context = {
    clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
    strokeRect: vi.fn(), measureText: vi.fn(() => ({ width: 60 })), fillRect: vi.fn(),
    fillText: vi.fn(), arc: vi.fn(), fill: vi.fn(),
  };
  const canvas = { width: 0, height: 0, getContext: () => context };
  return { canvas: canvas as unknown as HTMLCanvasElement, context };
}

const keypoints: [number, number, number][] = Array.from({ length: 17 }, () => [0, 0, 0]);
keypoints[5] = [100, 100, 0.9]; keypoints[7] = [100, 150, 0.9];
const frame = { type: 'detection', frame_width: 640, frame_height: 480, counts: { person: 1 },
  total_objects: 1, inference_time: 30, fps: 30, mode: 'human',
  trajectories: [{ track_id: 1, points: [[80, 80], [100, 100]] as [number, number][] }],
  detections: [{ id: 1, class: 'person', confidence: 0.9, bbox: [50, 50, 100, 200] as [number, number, number, number],
    track_id: 1, keypoints, action_estimates: ['Standing posture (estimate)'] }] };

describe('Live overlay presentation controls', () => {
  it('can hide boxes and class labels while retaining skeleton, trajectories and action estimates', () => {
    const { canvas, context } = drawingSurface();
    drawDetectionOverlay(canvas, frame, { boxes: false, labels: false });
    expect(context.strokeRect).not.toHaveBeenCalled();
    expect(context.fillText.mock.calls.some(([value]) => String(value).includes('person 90%'))).toBe(false);
    expect(context.fillText.mock.calls.some(([value]) => value === 'Standing posture (estimate)')).toBe(true);
    expect(context.lineTo.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(canvas.width).toBe(640);
  });

  it('redraws the same detection frame with boxes and object labels enabled', () => {
    const { canvas, context } = drawingSurface();
    drawDetectionOverlay(canvas, frame, { boxes: true, labels: true });
    expect(context.strokeRect).toHaveBeenCalledWith(50, 50, 100, 200);
    expect(context.fillText.mock.calls.some(([value]) => String(value).includes('#1 person 90%'))).toBe(true);
  });
});
