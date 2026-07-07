import { useState, useEffect, useCallback, useRef } from 'react'
import { FolderOpen, Folder, Plus, Trash2, HardDrive, Search, X } from 'lucide-react'
import { fetchWorkspaces, createWorkspace, deleteWorkspace, fetchFolders } from '../api'
import useStore from '../store/useStore'

export default function Sidebar() {
  const {
    workspaces, setWorkspaces, activeWorkspaceId, setActiveWorkspace,
    folders, setFolders, filterFolder, setFilterFolder, searchQuery, setSearchQuery,
  } = useStore()

  const [showAdd, setShowAdd] = useState(false)
  const [newPath, setNewPath] = useState('')
  const [newAlias, setNewAlias] = useState('')
  const fileInputRef = useRef(null)

  const handleBrowse = () => fileInputRef.current?.click()

  const handleFolderSelect = (e) => {
    const files = e.target.files
    if (files && files.length > 0) {
      if (files[0].path) {
        const fullPath = files[0].path
        const folderPath = fullPath.substring(0, fullPath.lastIndexOf('\\'))
        setNewPath(folderPath)
      } else {
        const relPath = files[0].webkitRelativePath
        setNewPath(relPath.split('/')[0])
      }
    }
    e.target.value = ''
  }

  const loadWorkspaces = useCallback(async () => {
    try {
      const data = await fetchWorkspaces()
      setWorkspaces(data)
      if (data.length > 0 && !activeWorkspaceId) {
        setActiveWorkspace(data[0].id)
      }
    } catch (e) {
      console.error('Failed to load workspaces', e)
    }
  }, [setWorkspaces, setActiveWorkspace])

  useEffect(() => { loadWorkspaces() }, [loadWorkspaces])

  useEffect(() => {
    if (activeWorkspaceId) {
      fetchFolders(activeWorkspaceId).then(setFolders).catch(() => {})
    }
  }, [activeWorkspaceId, setFolders])

  const handleAddWorkspace = async () => {
    if (!newPath) return
    try {
      await createWorkspace(newPath, newAlias || undefined)
      setNewPath('')
      setNewAlias('')
      setShowAdd(false)
      await loadWorkspaces()
    } catch (e) {
      console.error('Failed to create workspace', e)
    }
  }

  const handleDeleteWorkspace = async (id) => {
    try {
      await deleteWorkspace(id)
      await loadWorkspaces()
    } catch (e) {
      console.error('Failed to delete workspace', e)
    }
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <HardDrive size={18} />
        <span>워크스페이스</span>
        <button className="btn-icon ml-auto" onClick={() => setShowAdd(!showAdd)} title="워크스페이스 추가">
          <Plus size={16} />
        </button>
      </div>

      {showAdd && (
        <div className="sidebar-add">
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              type="text"
              placeholder="폴더 경로"
              value={newPath}
              onChange={(e) => setNewPath(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAddWorkspace()}
              style={{ flex: 1, minWidth: 0 }}
            />
            <button className="btn btn-secondary btn-sm" onClick={handleBrowse}>탐색</button>
          </div>
          <input
            type="text"
            placeholder="별칭 (선택사항)"
            value={newAlias}
            onChange={(e) => setNewAlias(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAddWorkspace()}
          />
          <button className="btn btn-primary btn-sm" onClick={handleAddWorkspace}>추가</button>
          <input ref={fileInputRef} type="file" webkitdirectory directory style={{ display: 'none' }} onChange={handleFolderSelect} />
        </div>
      )}

      <div className="sidebar-workspaces">
        {workspaces.map((ws) => (
          <div
            key={ws.id}
            className={`sidebar-item ${activeWorkspaceId === ws.id ? 'active' : ''}`}
            onClick={() => setActiveWorkspace(ws.id)}
          >
            <HardDrive size={14} />
            <span className="sidebar-label">{ws.alias || ws.absolute_path}</span>
            <span className="sidebar-count">{ws.file_count}</span>
            <button className="btn-icon" onClick={(e) => { e.stopPropagation(); handleDeleteWorkspace(ws.id) }} title="워크스페이스 제거">
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>

      <div className="sidebar-divider" />

      <div className="sidebar-search">
        <Search size={14} />
        <input
          type="text"
          placeholder="파일 검색..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        {searchQuery && (
          <button className="btn-icon" onClick={() => setSearchQuery('')}>
            <X size={14} />
          </button>
        )}
      </div>

      <div className="sidebar-folders">
        <div
          className={`sidebar-item ${filterFolder === '' ? 'active' : ''}`}
          onClick={() => setFilterFolder('')}
        >
          <FolderOpen size={14} />
          <span className="sidebar-label">전체 파일</span>
        </div>
        {folders
          .filter((f) => f.path !== '')
          .map((f) => (
            <div
              key={f.path}
              className={`sidebar-item ${filterFolder === f.path ? 'active' : ''}`}
              onClick={() => setFilterFolder(f.path)}
              style={{ paddingLeft: 12 + f.depth * 16 }}
            >
              <Folder size={14} />
              <span className="sidebar-label">{f.name}</span>
              <span className="sidebar-count">{f.file_count}</span>
            </div>
          ))}
      </div>
    </aside>
  )
}
