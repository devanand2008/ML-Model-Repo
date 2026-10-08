"""Add chapter-aligned neural narration to the existing captioned demo.

Optional export dependency: pip install edge-tts==7.2.8
Only the public caption text is sent to the online speech service.
"""
import asyncio
import json
import re
import subprocess
import wave
from pathlib import Path

import edge_tts
import imageio_ffmpeg
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'deliverables' / 'TransitOpt-Demo'
VOICE = 'en-IN-NeerjaNeural'
RATE = 24000
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def seconds(value):
    h, m, s, ms = map(int, re.split('[:,]', value))
    return h * 3600 + m * 60 + s + ms / 1000


def decode(path, tempo=1.0):
    command = [FFMPEG, '-hide_banner', '-loglevel', 'error', '-i', str(path)]
    if tempo != 1:
        command += ['-af', f'atempo={tempo:.6f}']
    command += ['-f', 'f32le', '-ac', '1', '-ar', str(RATE), 'pipe:1']
    return np.frombuffer(subprocess.run(command, check=True, capture_output=True).stdout, dtype='<f4')


async def main():
    original = OUT / 'TransitOpt-ML-Working-Demo-With-Subtitles.mp4'
    destination = OUT / 'TransitOpt-ML-Demo-AI-Voice.mp4'
    if destination.exists():
        raise FileExistsError(f'Preserving existing output: {destination}')
    chapters = json.loads((OUT / 'chapters.json').read_text(encoding='utf-8'))
    total = chapters['duration_seconds']
    track = np.zeros(round(total * RATE), dtype=np.float32)
    records = []
    clips = OUT / 'narration'
    clips.mkdir(exist_ok=True)
    captions = (OUT / 'TransitOpt-ML-Demo-Captions.srt').read_text(encoding='utf-8')
    for block in re.split(r'\n\s*\n', captions.strip()):
        lines = block.splitlines()
        number = int(lines[0])
        start, end = map(seconds, lines[1].split(' --> '))
        text = ' '.join(lines[2:])
        audio = clips / f'chapter-{number:02}.mp3'
        if not audio.exists() or not audio.stat().st_size:
            print(f'Generating AI narration {number}/12', flush=True)
            await edge_tts.Communicate(text, VOICE, rate='+0%').save(str(audio))
        samples = decode(audio)
        available = end - start - 0.5
        original_duration = len(samples) / RATE
        tempo = max(1.0, original_duration / available * 1.01)
        if tempo > 1:
            samples = decode(audio, tempo)
        if len(samples) / RATE > available + 0.05:
            raise ValueError(f'Chapter {number}: narration does not fit the caption interval')
        offset = round((start + 0.2) * RATE)
        track[offset:offset + len(samples)] = samples
        records.append({'chapter': number, 'caption_start_seconds': start,
                        'speech_start_seconds': start + 0.2,
                        'speech_duration_seconds': len(samples) / RATE,
                        'tempo': tempo, 'text': text})
        print(f'Chapter {number}: {len(samples) / RATE:.2f}s speech in {end-start:.0f}s chapter', flush=True)
    peak = float(np.max(np.abs(track)))
    if peak < 0.001:
        raise ValueError('The generated narration is silent')
    track *= min(0.89 / peak, 2.0)
    wav = OUT / 'TransitOpt-ML-Demo-AI-Narration.wav'
    with wave.open(str(wav), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes((track * 32767).astype('<i2').tobytes())
    subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-n',
                    '-i', str(original), '-i', str(wav),
                    '-map', '0:v:0', '-map', '1:a:0', '-map', '0:s?',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k', '-c:s', 'copy',
                    '-metadata:s:a:0', 'language=eng',
                    '-metadata:s:a:0', 'title=AI narration - English (India)',
                    '-metadata', 'comment=AI-generated narration; actual-results walkthrough, not an app screen recording.',
                    '-t', str(total), '-movflags', '+faststart', str(destination)], check=True)
    (OUT / 'narration-manifest.json').write_text(json.dumps({
        'voice': VOICE, 'language': 'English (India)', 'ai_generated': True,
        'duration_seconds': total, 'chapters': records,
    }, indent=2), encoding='utf-8')
    print(f'Created: {destination}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
