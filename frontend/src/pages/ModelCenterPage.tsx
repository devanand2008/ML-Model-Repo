import { useState, useEffect } from "react";
import { Brain, Upload, CheckCircle, AlertCircle, Trash2, ToggleLeft, ToggleRight } from "lucide-react";
import { api, AIModel } from "../services/api";
import { PageHeader, ErrorBanner, Spinner } from "../components/ResultsPanel";

const MODEL_TYPE_COLORS: Record<string, string> = {
  general:   "badge-blue",
  human:     "badge-purple",
  ship:      "badge-cyan",
  container: "badge-orange",
  condition: "badge-red",
};

export default function ModelCenterPage() {
  const [models,    setModels]    = useState<AIModel[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  // Upload form state
  const [upFile,   setUpFile]   = useState<File | null>(null);
  const [upName,   setUpName]   = useState("");
  const [upType,   setUpType]   = useState("general");
  const [upDesc,   setUpDesc]   = useState("");
  const [upVer,    setUpVer]    = useState("1.0.0");
  const [upClasses,setUpClasses]= useState("");
  const [upConf,   setUpConf]   = useState(0.5);
  const [datasetInfo,setDatasetInfo] = useState("{}");
  const [metricsInfo,setMetricsInfo] = useState("{}");
  const [upSuccess,setUpSuccess]= useState(false);

  const fetchModels = async () => {
    try {
      setLoading(true);
      const res = await api.getModels();
      setModels(res.models);
    } catch (e: any) {
      setError(e?.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchModels(); }, []);

  const handleUpload = async () => {
    if (!upFile || !upName) return;
    setUploading(true);
    try {
      await api.uploadModel(upFile, {
        dataset_info: datasetInfo, metrics: metricsInfo,
        name: upName,
        model_type: upType,
        description: upDesc,
        version: upVer,
        class_names: JSON.stringify(upClasses.split(",").map(s => s.trim()).filter(Boolean)),
        confidence_threshold: upConf,
      });
      setUpSuccess(true);
      setUpFile(null); setUpName(""); setUpDesc("");
      await fetchModels();
    } catch (e: any) {
      setError(e?.message);
    } finally {
      setUploading(false);
    }
  };

  const toggleActive = async (m: AIModel) => {
    try { await api.updateModel(m.id, { is_active: !m.is_active }); await fetchModels(); } catch(e:any) {setError(e.message);}
  };

  const deleteModel = async (m: AIModel) => {
    if (!confirm(`Delete model "${m.name}"? This cannot be undone.`)) return;
    try {
      await api.deleteModel(m.id);
      await fetchModels();
    } catch (e: any) { setError(e?.message); }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <PageHeader icon={Brain} title="Model Center" subtitle="Manage, upload, and configure AI detection models" iconColor="text-indigo-400" />

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
      {upSuccess && (
        <div className="flex items-center gap-2 bg-green-500/10 border border-green-500/30 rounded-xl px-4 py-3 text-green-400 text-sm">
          <CheckCircle size={16} /> Model uploaded successfully and set as default.
        </div>
      )}

      <div className="grid lg:grid-cols-5 gap-6">
        {/* Upload panel */}
        <div className="lg:col-span-2">
          <div className="glass p-5 space-y-4">
            <h2 className="font-semibold text-slate-300 text-sm flex items-center gap-2">
              <Upload size={16} className="text-indigo-400" /> Upload Custom Model
            </h2>

            <div>
              <label className="text-xs text-slate-500 mb-1 block">Model File (.pt)</label>
              <input
                type="file"
                accept=".pt"
                onChange={e => setUpFile(e.target.files?.[0] ?? null)}
                className="text-xs text-slate-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-blue-500/20 file:text-blue-400 file:text-xs file:cursor-pointer"
              />
              {upFile && <p className="text-xs text-green-400 mt-1">✓ {upFile.name}</p>}
            </div>

            {[
              { label: "Model Name", val: upName, set: setUpName, placeholder: "e.g. Container Detector v2" },
              { label: "Version",    val: upVer,  set: setUpVer,  placeholder: "1.0.0" },
              { label: "Description",val: upDesc, set: setUpDesc, placeholder: "Brief description…" },
              { label: "Class Names (comma-separated)", val: upClasses, set: setUpClasses, placeholder: "container, intermodal container" },
            ].map(({ label, val, set, placeholder }) => (
              <div key={label}>
                <label className="text-xs text-slate-500 mb-1 block">{label}</label>
                <input className="input-field" value={val} onChange={e => set(e.target.value)} placeholder={placeholder} />
              </div>
            ))}

            <div>
              <label className="text-xs text-slate-500 mb-1 block">Model Type</label>
              <select value={upType} onChange={e => setUpType(e.target.value)} className="input-field">
                {["general","human","ship","container","condition"].map(t => (
                  <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between text-xs text-slate-500">
                <span>Default Confidence</span>
                <span className="text-cyan-400 font-mono">{(upConf * 100).toFixed(0)}%</span>
              </div>
              <input type="range" min={0.1} max={0.95} step={0.05} value={upConf} onChange={e => setUpConf(parseFloat(e.target.value))} />
            </div>

            <label className="block text-xs">Dataset metadata (JSON)<textarea className="input-field mt-2" value={datasetInfo} onChange={e=>setDatasetInfo(e.target.value)} /></label>
            <label className="block text-xs">Evaluation metrics (JSON)<textarea className="input-field mt-2" value={metricsInfo} onChange={e=>setMetricsInfo(e.target.value)} /></label>
            <p className="text-xs text-amber-300">Only upload weights from a trusted source. PyTorch checkpoints may execute code.</p>
            <button onClick={handleUpload} disabled={!upFile || !upName || uploading} className="btn-primary w-full">
              {uploading ? "Uploading…" : "Upload & Activate Model"}
            </button>
          </div>
        </div>

        {/* Model list */}
        <div className="lg:col-span-3">
          {loading ? (
            <div className="glass p-5"><Spinner label="Loading models…" /></div>
          ) : (
            <div className="space-y-3">
              <h2 className="font-semibold text-slate-300 text-sm">Installed Models ({models.length})</h2>
              {models.map(m => (
                <div key={m.id} className={`glass p-4 space-y-3 transition-opacity ${!m.is_active ? "opacity-50" : ""}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-slate-200 text-sm truncate">{m.name}</span>
                        <span className={`badge ${MODEL_TYPE_COLORS[m.model_type] ?? "badge-blue"}`}>{m.model_type}</span>
                        {m.is_default && <span className="badge badge-green">Default</span>}
                        {!m.is_active && <span className="badge badge-red">Disabled</span>}
                      </div>
                      <p className="text-xs text-slate-500 mt-1 truncate">{m.description}</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button onClick={() => toggleActive(m)} className="text-slate-500 hover:text-blue-400 transition-colors">
                        {m.is_active ? <ToggleRight size={20} className="text-green-400" /> : <ToggleLeft size={20} />}
                      </button>
                      {!m.is_default && (
                        <button onClick={() => deleteModel(m)} className="text-slate-600 hover:text-red-400 transition-colors">
                          <Trash2 size={15} />
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-3 text-xs">
                    <div><span className="text-slate-600">File: </span><span className="font-mono text-slate-400">{m.filename}</span></div>
                    <div><span className="text-slate-600">Version: </span><span className="text-slate-400">{m.version}</span></div>
                    <div><span className="text-slate-600">Threshold: </span><span className="text-cyan-400">{(m.confidence_threshold * 100).toFixed(0)}%</span></div>
                  </div>

                  {m.class_names.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {m.class_names.slice(0, 8).map(cls => (
                        <span key={cls} className="text-xs px-2 py-0.5 rounded bg-slate-800/60 text-slate-400 capitalize">{cls}</span>
                      ))}
                      {m.class_names.length > 8 && (
                        <span className="text-xs px-2 py-0.5 rounded bg-slate-800/60 text-slate-500">+{m.class_names.length - 8} more</span>
                      )}
                    </div>
                  )}

                  <div className="flex flex-wrap gap-2">
                    <button className="btn-secondary text-xs" onClick={async()=>{const name=prompt('Model name',m.name);if(name)try{await api.updateModel(m.id,{name});await fetchModels();}catch(e:any){setError(e.message);}}}>Rename</button>
                    <button className="btn-secondary text-xs" onClick={async()=>{try{await api.updateModel(m.id,{is_default:true,is_active:true});await fetchModels();}catch(e:any){setError(e.message);}}}>Set default</button>
                    <button className="btn-secondary text-xs" onClick={async()=>{const v=prompt('Default confidence (0.10 to 0.95)',String(m.confidence_threshold));if(v)try{await api.updateModel(m.id,{confidence_threshold:Number(v)});await fetchModels();}catch(e:any){setError(e.message);}}}>Set threshold</button>
                  </div>
                  {Object.keys(m.metrics).length > 0 && (
                    <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                      {Object.entries(m.metrics).map(([k, v]) => (
                        typeof v === "number" && <span key={k}><span className="text-slate-600">{k}: </span><span className="text-green-400">{(v as number).toFixed(3)}</span></span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
