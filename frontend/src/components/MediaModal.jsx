import { useCallback, useEffect, useState } from 'react'
import { X, ChevronLeft, ChevronRight, Download, Star } from 'lucide-react'
import useStore from '../store/useStore'
import { getMediaUrl, toggleFavorite } from '../api'

export default function MediaModal() {
  const { modalFile, closeModal, files, toggleSelectFile } = useStore()
  const [imgError, setImgError] = useState(false)

  useEffect(() => {
    setImgError(false)
  }, [modalFile?.id])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape') closeModal()
    if (e.key === 'ArrowLeft') navigate(-1)
    if (e.key === 'ArrowRight') navigate(1)
  }, [modalFile, files, closeModal])

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
  }

  const handleToggleFav = async () => {
    if (!modalFile) return
    try {
      const res = await toggleFavorite(modalFile.id)
      useStore.setState({
        modalFile: { ...modalFile, is_favorite: res.is_favorite },
      })
    } catch (e) {
      console.error('Failed to toggle favorite', e)
    }
  }

  if (!modalFile) return null

  const mediaUrl = `${getMediaUrl(modalFile.id)}`

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
          {modalFile.tags?.length > 0 && (
            <span>태그: {modalFile.tags.join(', ')}</span>
          )}
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
