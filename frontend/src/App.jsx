import { useState, useEffect, useCallback, useRef } from 'react'
import Sidebar from './components/Sidebar'
import Toolbar from './components/Toolbar'
import FileGrid from './components/FileGrid'
import FileListView from './components/FileList'
import MediaModal from './components/MediaModal'
import ContextMenu from './components/ContextMenu'
import AIPanel from './components/AIPanel'
import { fetchFiles, searchFiles } from './api'
import useStore from './store/useStore'

export default function App() {
  const {
    activeWorkspaceId, files, setFiles, appendFiles, nextCursor,
    isLoadingFiles, setLoadingFiles, totalCount, setScanProgress,
    sortBy, sortOrder, filterMediaType, filterFolder, searchQuery,
    viewMode, modalFile, scanProgress, setAiProgress, setAiDownloadProgress,
  } = useStore()

  const loadingRef = useRef(false)

  const loadFiles = useCallback(async (append = false) => {
    if (!activeWorkspaceId || loadingRef.current) return
    loadingRef.current = true
    setLoadingFiles(true)
    try {
      const cursor = append ? nextCursor : undefined
      const params = {
        cursor,
        sortBy,
        sortOrder,
        mediaType: filterMediaType,
        folder: filterFolder || undefined,
      }
      const result = await fetchFiles(activeWorkspaceId, params)
      if (append) {
        appendFiles(result.files, result.next_cursor)
      } else {
        setFiles(result.files, result.next_cursor, result.total_count)
      }
    } catch (e) {
      console.error('Failed to load files', e)
    } finally {
      setLoadingFiles(false)
      loadingRef.current = false
    }
  }, [activeWorkspaceId, nextCursor, sortBy, sortOrder, filterMediaType, filterFolder, setFiles, appendFiles, setLoadingFiles])

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
  }, [activeWorkspaceId, sortBy, sortOrder, filterMediaType, filterFolder, searchQuery])

  const handleLoadMore = useCallback(() => {
    if (nextCursor && !isLoadingFiles) {
      loadFiles(true)
    }
  }, [nextCursor, isLoadingFiles, loadFiles])

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
            const type = e.type === 'batch' ? e.event : e.type || e.event
            const data = e.data || e
            if (type === 'scan_progress') {
              setScanProgress(data)
            } else if (type === 'scan_complete') {
              setScanProgress(null)
              loadFiles()
            } else if (type === 'ai_progress') {
              setAiProgress(data)
              if (data.phase === 'complete') loadFiles()
            } else if (type === 'ai_download_progress') {
              setAiDownloadProgress(data)
            } else if (['file_moved', 'file_deleted', 'file_created', 'file_modified'].includes(type)) {
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

  const hasMore = nextCursor != null

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
        <div className="file-view">
          {isLoadingFiles && files.length === 0 ? (
            <div className="loading-state">
              <div className="spinner" />
              <span>파일 불러오는 중...</span>
            </div>
          ) : files.length === 0 ? (
            <div className="empty-state">
              <p>파일이 없습니다</p>
              <p className="text-sm">워크스페이스를 추가하거나 기존 항목을 검색하세요</p>
            </div>
          ) : viewMode === 'grid' ? (
            <FileGrid files={files} onLoadMore={handleLoadMore} hasMore={hasMore} />
          ) : (
            <FileListView files={files} onLoadMore={handleLoadMore} hasMore={hasMore} />
          )}
        </div>
      </main>
      <AIPanel />
      {modalFile && <MediaModal />}
      <ContextMenu />
    </div>
  )
}
