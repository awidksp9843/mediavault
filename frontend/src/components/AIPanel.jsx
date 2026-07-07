import { useState, useEffect, useCallback } from 'react'
import { Brain, Cpu, Download, Activity, Check, RefreshCw, Sparkles } from 'lucide-react'
import useStore from '../store/useStore'
import { getAiStatus, analyzeWorkspace } from '../api'

export default function AIPanel() {
  const {
    aiStatus, setAiStatus,
    aiProgress, aiDownloadProgress,
    activeWorkspaceId,
  } = useStore()

  const [expanded, setExpanded] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)

  const loadStatus = useCallback(async () => {
    try {
      const s = await getAiStatus()
      setAiStatus(s)
    } catch {}
  }, [setAiStatus])

  useEffect(() => {
    loadStatus()
    const interval = setInterval(loadStatus, 10000)
    return () => clearInterval(interval)
  }, [loadStatus])

  const handleAnalyze = async () => {
    if (!activeWorkspaceId || analyzing) return
    setAnalyzing(true)
    try {
      await analyzeWorkspace(activeWorkspaceId)
    } catch (e) {
      console.error('Failed to start AI analysis', e)
    } finally {
      setAnalyzing(false)
    }
  }

  const isDownloading = aiDownloadProgress && aiDownloadProgress.status === 'downloading'

  return (
    <div className="ai-panel">
      <div className="ai-panel-header" onClick={() => setExpanded(!expanded)}>
        <Brain size={14} />
        <span>AI 분석</span>
        <span className="ml-auto">{expanded ? '−' : '+'}</span>
      </div>

      {expanded && (
        <div className="ai-panel-body">
          {/* Model status */}
          <div className="ai-section">
            <div className="ai-section-title">모델</div>
            {aiStatus?.models ? (
              Object.entries(aiStatus.models).map(([name, info]) => (
                <div key={name} className="ai-model-row">
                  <span className={`ai-dot ai-dot-${info.status === 'loaded' ? 'green' : info.status === 'downloading' ? 'yellow' : 'gray'}`} />
                  <span className="ai-model-name">{name}</span>
                  <span className={`ai-model-status status-${info.status}`}>{info.status}</span>
                </div>
              ))
            ) : (
              <div className="ai-model-row">
                <span className="ai-model-name dim">불러오는 중...</span>
              </div>
            )}
            <div className="ai-model-row">
              <Cpu size={12} />
              <span className="ai-model-name">장치</span>
              <span className="ai-model-status">{aiStatus?.hardware?.device || 'cpu'}</span>
            </div>
          </div>

          {/* Download progress */}
          {isDownloading && (
            <div className="ai-section">
              <div className="ai-section-title">
                <Download size={12} /> 모델 다운로드 중...
              </div>
              <div className="ai-progress-bar">
                <div className="ai-progress-fill" style={{ width: `${aiDownloadProgress.progress || 0}%` }} />
              </div>
              <div className="ai-progress-label">
                {aiDownloadProgress.model || '준비 중...'} ({aiDownloadProgress.progress || 0}%)
              </div>
            </div>
          )}

          {/* Analysis progress */}
          {aiProgress && aiProgress.phase !== 'complete' && aiProgress.phase !== 'no_files' && (
            <div className="ai-section">
              <div className="ai-section-title">
                <Activity size={12} /> 분석 중...
              </div>
              <div className="ai-progress-bar">
                <div
                  className="ai-progress-fill"
                  style={{ width: `${aiProgress.total > 0 ? (aiProgress.current / aiProgress.total) * 100 : 0}%` }}
                />
              </div>
              <div className="ai-progress-label">
                {aiProgress.filename || ''} ({aiProgress.current}/{aiProgress.total})
              </div>
            </div>
          )}

          {/* Analysis complete */}
          {aiProgress?.phase === 'complete' && (
            <div className="ai-section">
              <div className="ai-complete-msg">
                <Check size={14} /> 분석 완료 ({aiProgress.total}개 파일)
              </div>
            </div>
          )}

          {/* Trigger button */}
          <button
            className="btn btn-primary btn-sm ai-analyze-btn"
            onClick={handleAnalyze}
            disabled={analyzing || !activeWorkspaceId}
          >
            {analyzing ? (
              <><RefreshCw size={12} className="spin" /> 분석 중...</>
            ) : (
              <><Sparkles size={12} /> 워크스페이스 분석</>
            )}
          </button>
        </div>
      )}
    </div>
  )
}
