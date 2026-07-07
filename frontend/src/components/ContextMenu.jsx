import { useCallback, useEffect, useRef } from 'react'
import { Star, Trash2, Download, ExternalLink } from 'lucide-react'
import useStore from '../store/useStore'
import { deleteFile, toggleFavorite, getMediaUrl } from '../api'

export default function ContextMenu() {
  const { contextMenu, hideContextMenu, files } = useStore()
  const ref = useRef(null)

  useEffect(() => {
    const handler = () => hideContextMenu()
    window.addEventListener('click', handler)
    return () => window.removeEventListener('click', handler)
  }, [hideContextMenu])

  useEffect(() => {
    if (contextMenu) {
      const menu = ref.current
      if (!menu) return
      const rect = menu.getBoundingClientRect()
      if (rect.right > window.innerWidth) {
        menu.style.left = `${window.innerWidth - rect.width - 8}px`
      }
      if (rect.bottom > window.innerHeight) {
        menu.style.top = `${window.innerHeight - rect.height - 8}px`
      }
    }
  }, [contextMenu])

  const getFile = useCallback(() => {
    if (!contextMenu) return null
    return files.find((f) => f.id === contextMenu.fileId) || null
  }, [contextMenu, files])

  const handleToggleFav = async () => {
    const file = getFile()
    if (!file) return
    try {
      await toggleFavorite(file.id)
    } catch (e) {
      console.error(e)
    }
    hideContextMenu()
  }

  const handleDelete = async () => {
    const file = getFile()
    if (!file) return
    if (!confirm(`${file.filename}을(를) 삭제할까요?`)) return
    try {
      await deleteFile(file.id)
    } catch (e) {
      console.error(e)
    }
    hideContextMenu()
  }

  const handleOpen = () => {
    const file = getFile()
    if (!file) return
    const url = getMediaUrl(file.id)
    window.open(url, '_blank')
    hideContextMenu()
  }

  if (!contextMenu) return null

  return (
    <div
      ref={ref}
      className="context-menu"
      style={{ left: contextMenu.x, top: contextMenu.y }}
      onClick={(e) => e.stopPropagation()}
    >
      <button className="context-item" onClick={handleOpen}>
        <ExternalLink size={14} /> 열기
      </button>
      <button className="context-item" onClick={handleToggleFav}>
        <Star size={14} /> 즐겨찾기
      </button>
      <button className="context-item" onClick={handleDelete}>
        <Trash2 size={14} /> 삭제
      </button>
    </div>
  )
}
