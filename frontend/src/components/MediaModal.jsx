import { useCallback, useEffect, useState } from 'react'
import { X, ChevronLeft, ChevronRight, Download, Star, Sparkles } from 'lucide-react'
import useStore from '../store/useStore'
import { getMediaUrl, toggleFavorite, addTags, smartTagFile } from '../api'

export default function MediaModal() {
  const { modalFile, closeModal, files } = useStore()
  const [imgError, setImgError] = useState(false)
  const [tagInput, setTagInput] = useState('')
  const [localTags, setLocalTags] = useState([])
  const [smartTagging, setSmartTagging] = useState(false)

  useEffect(() => {
    setImgError(false)
    setTagInput('')
    setLocalTags(modalFile?.tags || [])
  }, [modalFile?.id])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape') closeModal()
    if (e.key === 'ArrowLeft') navigate(-1)
    if (e.key === 'ArrowRight') navigate(1)
    if (e.key === 'Enter' && tagInput.trim()) handleAddTag()
  }, [modalFile, files, closeModal, tagInput])

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  const navigate = (dir) => {
    if (!modalFile || files.length === 0) return
    const idx = files.findIndex((f) => f.id === modalFile.id)
    if (idx === -1) return
    const next = files[(idx + dir + files.length) % files.length]
    useStore.setState({ modalFile: next })
    setImgError(false)
    setLocalTags(next.tags || [])
    setTagInput('')
  }

  const handleToggleFav = async () => {
    if (!modalFile) return
    try {
      const res = await toggleFavorite(modalFile.id)
      const state = useStore.getState()
      const newFiles = state.files.map(f =>
        f.id === modalFile.id ? { ...f, is_favorite: res.is_favorite } : f
      )
      useStore.setState({
        files: newFiles,
        modalFile: { ...modalFile, is_favorite: res.is_favorite },
      })
    } catch (e) {
      console.error('Failed to toggle favorite', e)
    }
  }

  const handleSmartTag = async () => {
    if (!modalFile || smartTagging) return
    setSmartTagging(true)
    try {
      const res = await smartTagFile(modalFile.id)
      if (res.tags) {
        const updated = res.tags
        setLocalTags(updated)
        useStore.setState(s => ({
          files: s.files.map(f => f.id === modalFile.id ? { ...f, tags: updated } : f),
          modalFile: { ...modalFile, tags: updated },
        }))
      }
    } catch (e) {
      console.error('Smart tag failed', e)
    } finally {
      setSmartTagging(false)
    }
  }

  const updateFilesInStore = (fileId, updated) => {
    const state = useStore.getState()
    const newFiles = state.files.map(f => f.id === fileId ? { ...f, tags: updated } : f)
    useStore.setState({ files: newFiles, modalFile: { ...state.modalFile, tags: updated } })
  }

  const handleAddTag = async () => {
    const tag = tagInput.trim().toLowerCase()
    if (!tag || !modalFile) return
    if (localTags.includes(tag)) { setTagInput(''); return }
    try {
      await addTags([modalFile.id], [tag])
      const updated = [...localTags, tag]
      setLocalTags(updated)
      updateFilesInStore(modalFile.id, updated)
      setTagInput('')
    } catch (e) {
      console.error('Failed to add tag', e)
    }
  }

  const handleRemoveTag = async (tag) => {
    if (!modalFile) return
    try {
      await addTags([modalFile.id], [tag], 'remove')
      const updated = localTags.filter(t => t !== tag)
      setLocalTags(updated)
      updateFilesInStore(modalFile.id, updated)
    } catch (e) {
      console.error('Failed to remove tag', e)
    }
  }

  if (!modalFile) return null

  const mediaUrl = getMediaUrl(modalFile.id)

  return (
    <div className="modal-overlay" onClick={closeModal}>
      <div className="modal-container" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-filename" title={modalFile.filename}>{modalFile.filename}</span>
          <div className="modal-actions">
            <button className="btn-icon" onClick={handleToggleFav} title="즐겨찾기">
              <Star size={18} className={modalFile.is_favorite ? 'star-filled' : ''} />
            </button>
            <a href={mediaUrl} download={modalFile.filename} className="btn-icon" title="다운로드">
              <Download size={18} />
            </a>
            {modalFile.media_type === 'image' && (
              <button className="btn-icon" onClick={handleSmartTag} disabled={smartTagging} title="자동 태깅 (YOLO+BLIP)">
                <Sparkles size={18} className={smartTagging ? 'spin' : ''} />
              </button>
            )}
            <button className="btn-icon" onClick={closeModal} title="닫기">
              <X size={20} />
            </button>
          </div>
        </div>

        <div className="modal-body">
          <button className="modal-nav modal-nav-prev" onClick={() => navigate(-1)}>
            <ChevronLeft size={24} />
          </button>

          <div className="modal-media-wrapper">
            {modalFile.media_type === 'video' ? (
              <video controls autoPlay className="modal-media" key={modalFile.id}>
                <source src={mediaUrl} />
              </video>
            ) : (
              !imgError ? (
                <img
                  src={mediaUrl}
                  alt={modalFile.filename}
                  className="modal-media"
                  onError={() => setImgError(true)}
                />
              ) : (
                <div className="modal-error">미디어를 불러올 수 없습니다</div>
              )
            )}
          </div>

          <button className="modal-nav modal-nav-next" onClick={() => navigate(1)}>
            <ChevronRight size={24} />
          </button>
        </div>

        <div className="modal-footer">
          <span>크기: {modalFile.size ? formatSize(modalFile.size) : '-'}</span>
          {modalFile.dimensions && <span>해상도: {modalFile.width} x {modalFile.height}</span>}
          {modalFile.duration && <span>길이: {Math.round(modalFile.duration)}s</span>}
          <div className="modal-tags">
            <span style={{color:'var(--text-secondary)',fontWeight:500,whiteSpace:'nowrap',marginRight:2}}>태그</span>
            {localTags.map(tag => (
              <span key={tag} className="tag-chip">
                {tag}
                <button className="tag-chip-remove" onClick={() => handleRemoveTag(tag)}>
                  <X size={12} />
                </button>
              </span>
            ))}
            <input
              className="tag-input"
              type="text"
              placeholder="태그 입력 후 Enter..."
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleAddTag() }}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)}GB`
}
