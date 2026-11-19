import { useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  LayoutDashboard,
  LoaderCircle,
  Search,
  Settings,
  Upload,
  X,
} from 'lucide-react'

const API_BASE = import.meta.env.DEV ? '/api' : (import.meta.env.VITE_API_URL || '')

type DashboardRun = {
  source_path?: string
  status?: string
  rows_in?: number
  rows_out?: number
  rejected_rows?: number
  sensitive_columns?: Record<string, string[]>
  created_at?: string
}

type Dashboard = {
  total_runs: number
  successful_runs: number
  failed_runs: number
  recent_runs: DashboardRun[]
}

type Job = {
  job_id: string
  file_id: string
  filename: string
  status: 'queued' | 'running' | 'completed' | 'failed' | string
  rows_in?: number
  rows_out?: number
  rejected_rows?: number
  report_available?: boolean
  error?: string
}

function App() {
  const [page, setPage] = useState<'dashboard' | 'files' | 'settings'>('dashboard')
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [dashboardError, setDashboardError] = useState('')
  const [apiKey, setApiKey] = useState(localStorage.getItem('datake_api_key') || '')
  const [health, setHealth] = useState<'checking' | 'online' | 'offline'>('checking')
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [message, setMessage] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const headers = (): HeadersInit => {
    const value: HeadersInit = {}
    if (apiKey) value['X-API-Key'] = apiKey
    return value
  }

  const loadDashboard = async () => {
    setDashboardError('')
    try {
      const response = await fetch(`${API_BASE}/dashboard`, { headers: headers() })
      if (!response.ok) throw new Error(`Request failed (${response.status})`)
      setDashboard(await response.json())
    } catch (error) {
      setDashboardError(error instanceof Error ? error.message : 'Unable to load dashboard')
    }
  }

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await fetch(`${API_BASE}/health`)
        setHealth(response.ok ? 'online' : 'offline')
      } catch {
        setHealth('offline')
      }
    }
    checkHealth()
    loadDashboard()
  }, [])

  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/jobs/${job.job_id}`, { headers: headers() })
        if (response.ok) setJob(await response.json())
      } catch {
        // Keep the last known status while polling.
      }
    }, 1500)
    return () => window.clearInterval(timer)
  }, [job?.job_id, job?.status, apiKey])

  const saveApiKey = () => {
    localStorage.setItem('datake_api_key', apiKey)
    setMessage('API key saved')
    loadDashboard()
  }

  const uploadAndProcess = async () => {
    if (!file) return
    setUploading(true)
    setMessage('')
    setJob(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const uploadHeaders = apiKey ? { 'X-API-Key': apiKey } : undefined
      const upload = await fetch(`${API_BASE}/files`, {
        method: 'POST',
        headers: uploadHeaders,
        body: form,
      })
      if (!upload.ok) throw new Error((await upload.json()).detail || 'Upload failed')
      const uploaded = await upload.json()

      const process = await fetch(`${API_BASE}/files/${uploaded.file_id}/process`, {
        method: 'POST',
        headers: headers(),
      })
      if (!process.ok) throw new Error((await process.json()).detail || 'Processing failed')
      setJob(await process.json())
      setFile(null)
      if (fileInput.current) fileInput.current.value = ''
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to process file')
    } finally {
      setUploading(false)
    }
  }

  const download = async () => {
    if (!job) return
    const response = await fetch(`${API_BASE}/files/${job.file_id}/download`, { headers: headers() })
    if (!response.ok) {
      setMessage('The processed file is not available yet.')
      return
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = job.filename.replace(/\.[^.]+$/, '_cleaned.csv')
    link.click()
    URL.revokeObjectURL(url)
  }

  const openReport = async () => {
    if (!job) return
    const response = await fetch(`${API_BASE}/jobs/${job.job_id}/report`, { headers: headers() })
    if (!response.ok) {
      setMessage('The report is not available.')
      return
    }
    const report = await response.json()
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">D</span><span>Datake</span></div>
        <nav>
          <button className={page === 'dashboard' ? 'nav-item active' : 'nav-item'} onClick={() => setPage('dashboard')}>
            <LayoutDashboard size={18} /> Dashboard
          </button>
          <button className={page === 'files' ? 'nav-item active' : 'nav-item'} onClick={() => setPage('files')}>
            <FileSpreadsheet size={18} /> Files
          </button>
          <button className={page === 'settings' ? 'nav-item active' : 'nav-item'} onClick={() => setPage('settings')}>
            <Settings size={18} /> Settings
          </button>
        </nav>
        <div className={`server-status ${health}`}>
          <span /> API {health}
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <p className="eyebrow">Workspace</p>
            <h1>{page === 'dashboard' ? 'Dashboard' : page === 'files' ? 'File processing' : 'Settings'}</h1>
          </div>
          <button className="icon-button" aria-label="Search"><Search size={18} /></button>
        </header>

        <div className="content">
          {page === 'dashboard' && (
            <>
              <div className="metric-grid">
                <Metric label="Total runs" value={dashboard?.total_runs ?? '—'} icon={<Activity size={18} />} />
                <Metric label="Successful" value={dashboard?.successful_runs ?? '—'} icon={<CheckCircle2 size={18} />} />
                <Metric label="Failed" value={dashboard?.failed_runs ?? '—'} icon={<AlertCircle size={18} />} />
              </div>

              {dashboardError && <div className="notice error"><AlertCircle size={16} /> {dashboardError}</div>}

              <section className="panel">
                <div className="panel-header"><div><h2>Recent runs</h2><p>Latest processing activity</p></div></div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>File</th><th>Status</th><th>Rows</th><th>Rejected</th><th>Completed</th></tr></thead>
                    <tbody>
                      {(dashboard?.recent_runs || []).map((run, index) => (
                        <tr key={`${run.source_path}-${index}`}>
                          <td>{run.source_path ? run.source_path.split('/').pop() : '—'}</td>
                          <td><span className={`status ${run.status}`}>{run.status || 'unknown'}</span></td>
                          <td>{run.rows_out ?? run.rows_in ?? '—'}</td>
                          <td>{run.rejected_rows ?? '—'}</td>
                          <td>{run.created_at ? new Date(run.created_at).toLocaleString() : '—'}</td>
                        </tr>
                      ))}
                      {!dashboard?.recent_runs?.length && (
                        <tr><td colSpan={5} className="empty">No processing runs yet</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}

          {page === 'files' && (
            <div className="file-layout">
              <section className="panel upload-panel">
                <div className="panel-header"><div><h2>Upload and process</h2><p>CSV, Excel, JSON, JSON Lines, or Parquet</p></div></div>
                <div
                  className={file ? 'dropzone selected' : 'dropzone'}
                  onClick={() => fileInput.current?.click()}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => {
                    event.preventDefault()
                    setFile(event.dataTransfer.files[0] || null)
                  }}
                >
                  <input
                    ref={fileInput}
                    type="file"
                    accept=".csv,.xlsx,.json,.jsonl,.parquet"
                    onChange={(event) => setFile(event.target.files?.[0] || null)}
                  />
                  {file ? <FileSpreadsheet size={28} /> : <Upload size={28} />}
                  <strong>{file ? file.name : 'Choose a file or drop it here'}</strong>
                  <span>{file ? `${(file.size / 1024).toFixed(1)} KB` : 'Maximum size 50 MB'}</span>
                </div>
                {file && <button className="text-button remove" onClick={() => setFile(null)}><X size={15} /> Remove file</button>}
                {message && <div className="notice error"><AlertCircle size={16} /> {message}</div>}
                <button className="primary-button" disabled={!file || uploading} onClick={uploadAndProcess}>
                  {uploading ? <LoaderCircle className="spin" size={17} /> : <Upload size={17} />}
                  {uploading ? 'Uploading' : 'Process file'}
                </button>
              </section>

              <section className="panel job-panel">
                <div className="panel-header"><div><h2>Processing status</h2><p>Current job</p></div></div>
                {!job ? (
                  <div className="empty-state"><FileSpreadsheet size={26} /><span>No active job</span></div>
                ) : (
                  <div className="job-status">
                    <div className="job-title"><strong>{job.filename}</strong><span className={`status ${job.status}`}>{job.status}</span></div>
                    {['queued', 'running'].includes(job.status) && <div className="progress"><span /></div>}
                    {job.status === 'failed' && <div className="notice error"><AlertCircle size={16} /> {job.error || 'Processing failed'}</div>}
                    {job.status === 'completed' && (
                      <>
                        <div className="job-metrics">
                          <div><span>Rows in</span><strong>{job.rows_in ?? '—'}</strong></div>
                          <div><span>Rows out</span><strong>{job.rows_out ?? '—'}</strong></div>
                          <div><span>Rejected</span><strong>{job.rejected_rows ?? '—'}</strong></div>
                        </div>
                        <div className="job-actions">
                          <button className="secondary-button" onClick={openReport}>View report</button>
                          <button className="primary-button" onClick={download}><Download size={16} /> Download</button>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </section>
            </div>
          )}

          {page === 'settings' && (
            <section className="panel settings-panel">
              <div className="panel-header"><div><h2>API connection</h2><p>Configure access to the Datake backend</p></div></div>
              <label>API key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Optional — only required when enabled on the server" /></label>
              {message && <div className="notice success"><CheckCircle2 size={16} /> {message}</div>}
              <button className="primary-button" onClick={saveApiKey}>Save settings</button>
            </section>
          )}
        </div>
      </main>
    </div>
  )
}

function Metric({ label, value, icon }: { label: string; value: number | string; icon: React.ReactNode }) {
  return (
    <div className="metric">
      <div className="metric-icon">{icon}</div>
      <div><span>{label}</span><strong>{value}</strong></div>
    </div>
  )
}

export default App
