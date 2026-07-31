import React, {useState} from 'react'
import { api } from '../api/client'

const ALLOWED_EXTENSIONS = ['.xlsx']
const ACCEPT_ATTR = ALLOWED_EXTENSIONS.join(',')

function SummaryMetric({label, value}){
  return (
    <div className="p-4 flex flex-col gap-2" style={{ borderRadius: 7, background: 'var(--panel)', border: '1px solid var(--line)' }}>
      <span className="uppercase" style={{ fontSize: 10, letterSpacing: '0.2em', color: 'var(--muted)' }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{value}</span>
    </div>
  )
}

export function UploadPage({onSuccess}){
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState({loading:false, error:null})

  const handleFileChange = (event) => {
    setStatus({loading:false, error:null})
    const selected = event.target.files[0]
    setFile(selected || null)
  }

  const handleUpload = async (event) => {
    event.preventDefault()
    setStatus({loading:false, error:null})
    if (!file) {
      setStatus({loading:false, error:new Error('Select a .xlsx workbook before uploading.')})
      return
    }
    const lower = file.name.toLowerCase()
    if (!ALLOWED_EXTENSIONS.some(ext => lower.endsWith(ext))) {
      setStatus({loading:false, error:new Error(`File must be one of: ${ACCEPT_ATTR}`)})
      return
    }

    setStatus({loading:true, error:null})
    try {
      const formData = new FormData()
      formData.append('file', file)
      const result = await api.upload(formData)
      setStatus({loading:false, error:null})
      onSuccess?.(result)
    } catch (error) {
      setStatus({loading:false, error})
    }
  }

  const {loading,error} = status

  return (
    <section className="space-y-6">
      <div className="p-6 shadow-xl" style={{ borderRadius: 7, background: 'var(--panel)', border: '1px solid var(--line)' }}>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="uppercase" style={{ fontSize: 10, letterSpacing: '0.3em', color: 'var(--orange)' }}>Workbook upload</p>
            <h2 className="mt-2" style={{ fontSize: 13, fontWeight: 800, color: 'var(--text)' }}>Upload your validated project file</h2>
            <p className="mt-3 max-w-2xl" style={{ fontSize: 10, color: 'var(--muted)' }}>Use the backend parser directly. The upload only accepts <span style={{ fontWeight: 700, color: 'var(--text)' }}>.xlsx</span>.</p>
          </div>
          <div className="p-4" style={{ borderRadius: 7, border: '1px solid var(--line)', background: 'var(--panel2)' }}>
            <form onSubmit={handleUpload} className="flex flex-col gap-4 sm:flex-row sm:items-center">
              <label className="overflow-hidden px-4 py-3 cursor-pointer" style={{ borderRadius: 7, border: '1px solid var(--line)', background: 'var(--panel)', color: 'var(--text)', fontSize: 10, boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.02)' }}>
                <span>{file ? file.name : 'Choose .xlsx file'}</span>
                <input type="file" accept={ACCEPT_ATTR} onChange={handleFileChange} className="sr-only" />
              </label>
              <button type="submit" disabled={loading} className="px-5 py-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60" style={{ borderRadius: 7, background: 'var(--teal)', color: 'var(--bg)', fontSize: 10 }}>
                {loading ? 'Uploading…' : 'Upload workbook'}
              </button>
            </form>
            <p className="mt-2" style={{ fontSize: 9, color: 'var(--muted)' }}>Allowed file type: {ACCEPT_ATTR}</p>
          </div>
        </div>

        {error && (
          <div className="mt-6 p-4" style={{ borderRadius: 7, border: '1px solid rgba(255, 151, 80, 0.24)', background: 'rgba(255, 151, 80, 0.08)', color: 'var(--orange)' }}>
            <strong>Error uploading file:</strong> {error.message}
          </div>
        )}

        {!loading && !error && (
          <div className="mt-6 p-4" style={{ borderRadius: 7, border: '1px solid var(--line)', background: 'var(--panel2)', color: 'var(--muted)' }}>
            Select a valid workbook and submit to proceed.
          </div>
        )}
      </div>
    </section>
  )
}
