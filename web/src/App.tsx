import { useState, useRef, useEffect } from 'react'
import './App.css'
import * as THREE from 'three'

const API_BASE = 'http://100.120.0.2:8000' 

type StatusType = 'info' | 'success' | 'error'
type ScanStatus = 'queued' | 'processing' | 'done' | 'failed'
type HistoryItem = { file: File; id: string; name: string }

function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [scanId, setScanId] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [statusType, setStatusType] = useState<StatusType>('info')
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [previewFile, setPreviewFile] = useState<File | null>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<THREE.Scene | null>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const [modelHistory, setModelHistory] = useState<HistoryItem[]>([])

  // 3D プレビューの初期化
  useEffect(() => {
    if (previewFile && canvasRef.current) {
      initializePreview(previewFile)
    }
    return () => {
      if (rendererRef.current && canvasRef.current?.contains(rendererRef.current.domElement)) {
        canvasRef.current?.removeChild(rendererRef.current.domElement)
      }
    }
  }, [previewFile])

  const selectHistoryModel = (historyItem: HistoryItem) => {
    setPreviewFile(historyItem.file)
    setScanId(historyItem.id)
    setSelectedFile(historyItem.file)
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
        throw new Error('アップロードに失敗しました:${response.status}')
      }
      const data = await response.json() as { scan_id: string }
      setScanId(data.scan_id)
      setStatus(null)
      setModelHistory(prev => [...prev, { file: selectedFile, id: data.scan_id, name: selectedFile.name }])
      checkStatus(data.scan_id)
    } catch (error) {
      showStatus('error', `エラー: ${error instanceof Error ? error.message : '不明なエラー'}`)
      setProgress(0)
    } finally {
      setUploading(false)
    }
  }

  const initializePreview = async (file: File) => {
    try {
      const reader = new FileReader()
      reader.onload = async (e) => {
        const arrayBuffer = e.target?.result as ArrayBuffer
        await loadGLBModel(arrayBuffer)
      }
      reader.readAsArrayBuffer(file)
    } catch (error) {
      console.error('プレビュー初期化エラー:', error)
      showStatus('error', 'プレビューの読み込みに失敗しました。')
    }
  }

  const loadGLBModel = async (arrayBuffer: ArrayBuffer) => {
    if (!canvasRef.current) return

    try {
      // シーンの初期化
      const scene = new THREE.Scene()
      scene.background = new THREE.Color(0xf5f5f5)
      sceneRef.current = scene

      // ライティング設定
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.8)
      scene.add(ambientLight)

      const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8)
      directionalLight.position.set(5, 5, 5)
      scene.add(directionalLight)

      // カメラ設定
      const camera = new THREE.PerspectiveCamera(
        75,
        canvasRef.current.clientWidth / canvasRef.current.clientHeight,
        0.1,
        1000
      )
      camera.position.z = 3

      // レンダラー設定
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
      renderer.setSize(canvasRef.current.clientWidth, canvasRef.current.clientHeight)
      renderer.setPixelRatio(window.devicePixelRatio)

      if (rendererRef.current && canvasRef.current.contains(rendererRef.current.domElement)) {
        canvasRef.current.removeChild(rendererRef.current.domElement)
      }

      canvasRef.current.appendChild(renderer.domElement)
      rendererRef.current = renderer

      // GLTFLoader を使用してモデルを読み込む
      const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
      const loader = new GLTFLoader()

      loader.parse(arrayBuffer, '', (gltf) => {
        const model = gltf.scene

        // モデルのサイズを計算して調整
        const box = new THREE.Box3().setFromObject(model)
        const size = box.getSize(new THREE.Vector3())
        const maxDim = Math.max(size.x, size.y, size.z)
        const scale = 2 / maxDim
        model.scale.multiplyScalar(scale)

        // モデルの中心をシーンの原点に配置
        const center = box.getCenter(new THREE.Vector3())
        model.position.sub(center.multiplyScalar(scale))

        scene.add(model)

        // アニメーションループ
        let animationId: number
        const animate = () => {
          animationId = requestAnimationFrame(animate)
          model.rotation.y += 0.005
          renderer.render(scene, camera)
        }
        animate()

        // ウィンドウリサイズ対応
        const handleResize = () => {
          if (!canvasRef.current) return
          const width = canvasRef.current.clientWidth
          const height = canvasRef.current.clientHeight
          camera.aspect = width / height
          camera.updateProjectionMatrix()
          renderer.setSize(width, height)
        }
        window.addEventListener('resize', handleResize)

        return () => {
          window.removeEventListener('resize', handleResize)
          cancelAnimationFrame(animationId)
        }
      }, (error) => {
        console.error('GLB ロードエラー:', error)
        showStatus('error', 'プレビューの読み込みに失敗しました。')
      })
    } catch (error) {
      console.error('3Dモデル読み込みエラー:', error)
      showStatus('error', 'プレビューの読み込みに失敗しました。')
    }
  }

  const handleFileSelect = (file: File) => {
    const validExtensions = ['.glb', '.gltf']
    const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase()

    if (!validExtensions.includes(fileExtension || '')) {
      showStatus('error', '対応していないファイル形式です。.glb または .gltf ファイルを選択してください。')
      return
    }

    setSelectedFile(file)
    setPreviewFile(file)
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

  const checkStatus = async (id: string = scanId || '') => {
    if (!id) return

    try {
      const response = await fetch(`${API_BASE}/scan/${id}/status`)
      const data = await response.json() as { status: ScanStatus; error?: string }

      setScanStatus(data.status)

      if (data.status === 'done') {
        setStatus(null)
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
    <div className="app-wrapper">
      <div className="stars"></div>

      <div className="container">
        {/* ヘッダーセクション */}
        <div className="header-section">
          <div className="header-content">
            <h1 className="title">🎭 3D Head Scan</h1>
            <p className="subtitle">GLB/GLTF ファイルをアップロードして<br />あなただけのアバターを生成</p>
          </div>
          <div className="decorative-circle"></div>
        </div>

        {/* 修正: content-wrapper を正しく閉じる */}
        <div className="content-wrapper">
          {/* アップロードエリア */}
          <div className="upload-section">
            <h2>ファイルアップロード</h2>
            {!previewFile && (
              <div
                className={`upload-area ${dragOver ? 'dragover' : ''}`}
                onClick={() => document.getElementById('fileInput')?.click()}
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
              >
                <div className="upload-icon">📦</div>
                <div className="upload-text">ファイルを選択またはドラッグ</div>
                <div className="upload-hint">対応形式: .glb, .gltf</div>
              </div>
            )}

            <input
              type="file"
              id="fileInput"
              accept=".glb,.gltf"
              style={{ display: 'none' }}
              onChange={(e) => e.target.files && e.target.files.length > 0 && handleFileSelect(e.target.files[0])}
            />

            {/* ファイル情報 */}
            {selectedFile && (
              <div className="file-info-card">
                <div className="file-info-icon">📄</div>
                <div className="file-info-details">
                  <div className="file-name">{selectedFile.name}</div>
                  <div className="file-size">{formatFileSize(selectedFile.size)}</div>
                </div>
              </div>
            )}

            {/* アップロードボタン */}
            <button
              className="btn-upload"
              disabled={!selectedFile || uploading}
              onClick={handleUpload}
            >
              {uploading ? '処理中...' : 'アップロード & 変換'}
            </button>

            {/* プログレスバー */}
            {uploading && (
              <div className="progress-container">
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${progress}%` }}></div>
                </div>
                <div className="progress-text">{progress}%</div>
              </div>
            )}

            {/* 修正: クラス名のスペースを追加 */}
            {status && (
              <div className={`status-message ${statusType} show`}>
                {status}
              </div>
            )}

            {/* 結果ボックス */}
            {scanId && (
  <div className="result-box show">
    <h3 style={{ marginBottom: '8px', color: '#333' }}>✨ アップロード完了</h3>
    {scanStatus === 'done' && (
      <p style={{ fontSize: '12px', color: '#666', marginBottom: '12px' }}>処理が完了しました</p>
    )}
    <p style={{ fontSize: '12px', color: '#666', marginBottom: '12px' }}>Scan ID: </p>
    <div className="scan-id">{scanId}</div>
    
    <button className="btn-check" onClick={() => checkStatus()}>
      ステータス確認
    </button>
    {scanStatus === 'done' && (
      <button className="btn-download" onClick={handleDownload}>
        ダウンロード
      </button>
    )}

    {scanStatus && (
      <div style={{ marginTop: '12px', fontSize: '12px', fontWeight: '600' }}>
        ステータス: 
        {scanStatus === 'done' && ' ✅ 完了'}
        {scanStatus === 'processing' && ' ⏳ 処理中'}
        {scanStatus === 'queued' && ' 📋 キュー待ち'}
        {scanStatus === 'failed' && ' ❌ エラー'}
      </div>
    )}
  </div>
)}
              
          </div>

          {/* 修正: 履歴セクションを content-wrapper 内に移動し、構造をシンプルに */}
          {modelHistory.length > 0 && (
            <div className="history-section">
              <h3>過去モデル</h3>
              <div className="history-list">
                {modelHistory.map((item, index) => (
                  <div key={index} className="history-item" onClick={() => selectHistoryModel(item)}>
                    <div className="history-icon">👤</div>
                    <span className="history-name">{item.name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* プレビューセクション */}
          {previewFile && (
            <div className="preview-section show">
              <div className="preview-container" ref={canvasRef}></div>
              <button
                className="btn-change-file"
                onClick={() => document.getElementById('fileInput')?.click()}
              >
                別のファイルを選択
              </button>
            </div>
          )}
        </div> {/* content-wrapper の閉じタグ */}
      </div>
    </div>
  )
}

export default App