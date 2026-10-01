import { useCallback, useState, useEffect } from "react";
import { useDropzone } from "react-dropzone";
import { Upload, Image as ImageIcon, Film, X } from "lucide-react";

interface Props {
  onFile: (f: File | null) => void;
  accept?: Record<string, string[]>;
  label?: string;
  hint?: string;
}

const IMAGE_ACCEPT = { "image/*": [".jpg", ".jpeg", ".png", ".webp"] };
const VIDEO_ACCEPT = { "video/*": [".mp4", ".avi", ".mov", ".mkv"] };

export function ImageDropzone({ onFile, accept = IMAGE_ACCEPT, label = "Drop an image", hint = "JPG, JPEG, PNG, WEBP" }: Props) {
  const [error,setError] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview);},[preview]);

  const onDrop = useCallback((accepted: File[]) => {
    const f = accepted[0];
    if (!f) return;
    setError("");
    setFileName(f.name);
    const url = URL.createObjectURL(f);
    setPreview(url);
    onFile(f);
  }, [onFile]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, accept, multiple: false, maxSize:100*1024*1024, onDropRejected:()=>setError("Choose a supported file under 100 MB.") });

  const clear = (e: React.MouseEvent) => {
    e.stopPropagation();
    onFile(null);
    setPreview(null);
    setFileName(null);
  };

  return (
    <div {...getRootProps()} className={`dropzone relative flex flex-col items-center justify-center text-center p-8 min-h-48 ${isDragActive ? "active" : ""}`}>
      <input {...getInputProps()} />
      {error && <p role="alert" className="text-red-400 text-sm">{error}</p>}
      {preview ? (
        <div className="relative w-full">
          {accept === VIDEO_ACCEPT ? <video src={preview} controls onClick={e=>e.stopPropagation()} className="max-h-72 mx-auto rounded-xl" /> : <img src={preview} alt="Original image preview" className="max-h-72 mx-auto rounded-xl object-contain" />}
          <button aria-label="Remove selected file" onClick={clear} className="absolute top-2 right-2 bg-red-500/80 rounded-full p-1 text-white hover:bg-red-500 transition-colors">
            <X size={14} />
          </button>
          <p className="mt-2 text-xs text-slate-400 truncate">{fileName}</p>
        </div>
      ) : (
        <>
          <div className="w-16 h-16 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center mb-4">
            <Upload size={28} className="text-blue-400" />
          </div>
          <p className="text-slate-300 font-semibold mb-1">{isDragActive ? "Release to upload" : label}</p>
          <p className="text-slate-500 text-sm">or click to browse</p>
          <p className="text-slate-600 text-xs mt-2">{hint}</p>
        </>
      )}
    </div>
  );
}

export function VideoDropzone({ onFile }: { onFile: (f: File | null) => void }) {
  return (
    <ImageDropzone
      onFile={onFile}
      accept={VIDEO_ACCEPT}
      label="Drop a video file"
      hint="MP4, AVI, MOV, MKV"
    />
  );
}
