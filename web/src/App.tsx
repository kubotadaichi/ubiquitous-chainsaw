import { useState } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

type StatusType = 'info' | 'success' | 'error'
type ScanStatus = 'queued' | 'processing' | 'done' | 'failed'

function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [scanId, setScanId] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [statusType, setStatusType] = useState<StatusType>('info')
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null)
  const [dragOver, setDragOver] = useState(false)

  const handleFileSelect = (file: File) => {
    const validExtensions = ['.glb', '.gltf']
    const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase()

    if (!validExtensions.includes(fileExtension || '')) {
      showStatus('error', '対応していないファイル形式です。.glb または .gltf ファイルを選択してください。')
      return
    }

    setSelectedFile(file)
    setScanId(null)
    setStatus(null)
    setScanStatus(null)
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    const files = e.dataTransfer.files
    if (files.length > 0) {
      handleFileSelect(files[0])
    }
  }

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(true)
  }

  const handleDragLeave = () => {
    setDragOver(false)
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  const showStatus = (type: StatusType, message: string) => {
    setStatusType(type)
    setStatus(message)
  }

  const handleUpload = async () => {
    if (!selectedFile) return

    const formData = new FormData()
    formData.append('head', selectedFile)

    setUploading(true)
    setProgress(30)
    showStatus('info', 'アップロード中...')

    try {
      const response = await fetch(`${API_BASE}/scan`, {
        method: 'POST',
        body: formData
      })

      setProgress(100)

      if (!response.ok) {
        throw new Error('アップロードに失敗しました')
      }

      const data = await response.json() as { scan_id: string }
      setScanId(data.scan_id)
      setStatus(null)

      checkStatus(data.scan_id)

    } catch (error) {
      showStatus('error', `エラー: ${error instanceof Error ? error.message : '不明なエラー'}`)
      setProgress(0)
    } finally {
      setUploading(false)
    }
  }

  const checkStatus = async (id: string = scanId || '') => {
    if (!id) return

    try {
      const response = await fetch(`${API_BASE}/scan/${id}/status`)
      const data = await response.json() as { status: ScanStatus; error?: string }

      setScanStatus(data.status)

      if (data.status === 'done') {
        showStatus('success', '✅ 処理が完了しました！ダウンロードできます。')
      } else if (data.status === 'failed') {
        showStatus('error', '❌ 処理に失敗しました: ' + (data.error || '不明なエラー'))
      } else {
        showStatus('info', `⏳ 処理中... (${data.status})`)
      }

    } catch (error) {
      showStatus('error', `ステータス確認エラー: ${error instanceof Error ? error.message : '不明なエラー'}`)
    }
  }

  const handleDownload = async () => {
    if (!scanId) return

    try {
      const response = await fetch(`${API_BASE}/scan/${scanId}/download`)

      if (!response.ok) {
        throw new Error('ダウンロードに失敗しました')
      }

      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `avatar_${scanId}.fbx`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)

      showStatus('success', 'ダウンロードを開始しました！')

    } catch (error) {
      showStatus('error', `ダウンロードエラー: ${error instanceof Error ? error.message : '不明なエラー'}`)
    }
  }

  return (
    <div className="container">
      <h1>🎭 3D Head Scan Upload</h1>
      <p className="subtitle">GLB/GLTFファイルをアップロードしてアバターを生成</p>

      <div
        className={`upload-area ${dragOver ? 'dragover' : ''}`}
        onClick={() => document.getElementById('fileInput')?.click()}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
      >
        <div className="upload-icon">📦</div>
        <div className="upload-text">ファイルを選択またはドラッグ&ドロップ</div>
        <div className="upload-hint">対応形式: .glb, .gltf</div>
      </div>

      <input
        type="file"
        id="fileInput"
        accept=".glb,.gltf"
        style={{ display: 'none' }}
        onChange={(e) => e.target.files && e.target.files.length > 0 && handleFileSelect(e.target.files[0])}
      />

      {selectedFile && (
        <div className="file-info">
          <div className="file-name">{selectedFile.name}</div>
          <div className="file-size">{formatFileSize(selectedFile.size)}</div>
        </div>
      )}

      <button
        className="btn-upload"
        disabled={!selectedFile || uploading}
        onClick={handleUpload}
      >
        アップロード
      </button>

      {uploading && (
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progress}%` }}></div>
        </div>
      )}

      {status && (
        <div className={`status ${statusType}`}>
          {status}
        </div>
      )}

      {scanId && (
        <div className="result-box">
          <h3>✅ アップロード完了</h3>
          <p style={{ margin: '10px 0', color: '#666' }}>Scan ID:</p>
          <div className="scan-id">{scanId}</div>
          <button className="btn-check" onClick={() => checkStatus()}>
            ステータス確認
          </button>
          {scanStatus === 'done' && (
            <button className="btn-download" onClick={handleDownload}>
              ダウンロード
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export default App
