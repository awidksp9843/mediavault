import { useState, useEffect, useCallback, useRef } from 'react'
import Sidebar from './components/Sidebar'
import Toolbar from './components/Toolbar'
import FileGrid from './components/FileGrid'
import FileListView from './components/FileList'
import MediaModal from './components/MediaModal'
import ContextMenu from './components/ContextMenu'
import { fetchFiles, searchFiles, deleteFile } from './api'
import useStore from './store/useStore'

export default function App() {
  const {
    activeWorkspaceId, files, setFiles,
    isLoadingFiles, setLoadingFiles, totalCount, setScanProgress,
    sortBy, sortOrder, filterMediaType, filterFavorites, filterFolder, searchQuery,
    viewMode, modalFile, scanProgress, autoTagProgress, setAutoTagProgress,
  } = useStore()

  const loadingRef = useRef(false)

  const loadFiles = useCallback(async () => {
    if (!activeWorkspaceId || loadingRef.current) return
    loadingRef.current = true
    setLoadingFiles(true)
    try {
      const params = {
        sortBy,
        sortOrder,
        mediaType: filterMediaType,
        folder: filterFolder || undefined,
        isFavorite: filterFavorites || undefined,
      }
      const result = await fetchFiles(activeWorkspaceId, params)
      setFiles(result.files, result.total_count)
    } catch (e) {
      console.error('Failed to load files', e)
    } finally {
      setLoadingFiles(false)
      loadingRef.current = false
    }
  }, [activeWorkspaceId, sortBy, sortOrder, filterMediaType, filterFavorites, filterFolder, setFiles, setLoadingFiles])

  const handleSearch = useCallback(async () => {
    if (!activeWorkspaceId || !searchQuery.trim()) {
      loadFiles()
      return
    }
    setLoadingFiles(true)
    try {
      const result = await searchFiles(activeWorkspaceId, {
        query: searchQuery,
        mediaType: filterMediaType,
      })
      setFiles(result.files, null, result.total_count)
    } catch (e) {
      console.error('Search failed', e)
    } finally {
      setLoadingFiles(false)
    }
  }, [activeWorkspaceId, searchQuery, filterMediaType, setFiles, setLoadingFiles, loadFiles])

  useEffect(() => {
    if (!activeWorkspaceId) return
    if (searchQuery) {
      handleSearch()
    } else {
      loadFiles()
    }
  }, [activeWorkspaceId, sortBy, sortOrder, filterMediaType, filterFavorites, filterFolder, searchQuery])

  useEffect(() => {
    let ws = null
    let reconnectTimer = null

    const connect = () => {
      ws = new WebSocket(`ws://${import.meta.env.VITE_BACKEND_HOST || '127.0.0.1'}:${import.meta.env.VITE_BACKEND_PORT || 8000}/ws`)

      ws.onopen = () => {
        useStore.setState({ wsConnected: true })
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          const events = msg.type === 'batch' ? msg.events : [msg]
          for (const e of events) {
            const type = e.type === 'batch' ? e.event : e.event || e.type
            const data = e.data || e
            if (type === 'scan_progress') {
              setScanProgress(data)
            } else if (type === 'scan_complete') {
              setScanProgress(null)
              useStore.setState({ isAddingWorkspace: false })
              loadFiles()
            } else if (type === 'auto_tag_started') {
              setAutoTagProgress({ current: 0, total: data.total })
            } else if (type === 'auto_tag_progress') {
              setAutoTagProgress({ current: data.current, total: data.total, filename: data.filename, tags: data.tags })
              if (data.tags?.length > 0) {
                useStore.setState(s => ({
                  files: s.files.map(f =>
                    f.id === data.file_id ? { ...f, tags: data.tags } : f
                  ),
                  modalFile: s.modalFile?.id === data.file_id
                    ? { ...s.modalFile, tags: data.tags } : s.modalFile,
                }))
              }
            } else if (type === 'auto_tag_completed') {
              const errs = data.errors || 0
              const msg = errs > 0
                ? `자동 태깅 완료 (${errs}개 오류)`
                : `자동 태깅 완료 (${data.total}개)`
              setAutoTagProgress({ done: true, message: msg })
              setTimeout(() => setAutoTagProgress(null), 3000)
              loadFiles()
            } else if (['file_moved', 'file_deleted', 'file_created', 'file_modified', 'tags_updated'].includes(type)) {
              loadFiles()
            }
          }
        } catch {}
      }

      ws.onclose = () => {
        useStore.setState({ wsConnected: false })
        reconnectTimer = setTimeout(connect, 3000)
      }

      ws.onerror = () => {
        ws?.close()
      }
    }

    connect()
    return () => {
      clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [])

  useEffect(() => {
    const handleDrop = (e) => e.preventDefault()
    const handleDragOver = (e) => e.preventDefault()
    window.addEventListener('drop', handleDrop)
    window.addEventListener('dragover', handleDragOver)
    return () => {
      window.removeEventListener('drop', handleDrop)
      window.removeEventListener('dragover', handleDragOver)
    }
  }, [])

  useEffect(() => {
    const handleKeyDown = async (e) => {
      if (e.repeat) return
      const state = useStore.getState()
      if (state.modalFile) return

      if (e.key === 'a' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        state.selectAll()
        return
      }

      if (e.key !== 'Delete') return
      const ids = Array.from(state.selectedFileIds)
      if (ids.length === 0) return
      if (!window.confirm(`${ids.length}개 파일을 삭제하시겠습니까?`)) return
      for (const id of ids) {
        try { await deleteFile(id) } catch {}
      }
      useStore.setState({
        selectedFileIds: new Set(),
        files: useStore.getState().files.filter(f => !ids.includes(f.id)),
      })
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        <Toolbar />
        {scanProgress && (
          <div className="scan-banner">
            검색 중... {scanProgress.indexed || 0} / {scanProgress.total || 0}개 파일
            {scanProgress.phase && ` (${scanProgress.phase})`}
          </div>
        )}
        {autoTagProgress && (
          <div className={`auto-tag-banner ${autoTagProgress.done ? 'auto-tag-done' : ''}`}>
            {autoTagProgress.done ? (
              <div className="auto-tag-info">{autoTagProgress.message}</div>
            ) : (
              <>
                <div className="auto-tag-info">
                  자동 태깅 중... {autoTagProgress.current} / {autoTagProgress.total}
                  {autoTagProgress.filename && ` (${autoTagProgress.filename})`}
                </div>
                <div className="auto-tag-bar">
                  <div className="auto-tag-fill" style={{ width: `${(autoTagProgress.current / autoTagProgress.total) * 100}%` }} />
                </div>
              </>
            )}
          </div>
        )}
        <div className="file-view">
          {isLoadingFiles && files.length === 0 ? (
            <div className="loading-state">
              <div className="spinner" />
              <span>파일 불러오는 중...</span>
            </div>
          ) : files.length === 0 ? (
            <div className="empty-state">
              <p>파일이 없습니다</p>
              <p className="text-sm">워크스페이스를 추가하세요</p>
            </div>
          ) : viewMode === 'grid' ? (
            <FileGrid files={files} />
          ) : (
            <FileListView files={files} />
          )}
        </div>
      </main>
      {modalFile && <MediaModal />}
      <ContextMenu />
    </div>
  )
}
