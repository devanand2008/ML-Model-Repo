"""Convert a browser recording to a new H.264 MP4 beside the original."""
import argparse
from pathlib import Path
import subprocess
import imageio_ffmpeg

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('recording',type=Path)
args=parser.parse_args()
source=args.recording.resolve(strict=True)
output=source.with_name(source.stem+'-converted.mp4')
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-n','-i',str(source),
    '-c:v','libx264','-preset','medium','-crf','20','-pix_fmt','yuv420p',
    '-c:a','aac','-movflags','+faststart',str(output)],check=True)
print('MP4 saved:',output)
