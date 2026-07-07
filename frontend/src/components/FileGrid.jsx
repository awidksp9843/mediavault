import { useCallback, useRef, useEffect, useState } from 'react'
import { Grid } from 'react-window'
import { Star, Play, Image } from 'lucide-react'
import useStore from '../store/useStore'
import { getThumbnailUrl } from '../api'

const CARD_WIDTH = 180
const CARD_HEIGHT = 200
const GAP = 8

const CellComponent = ({ data, rowIndex, columnIndex, style }) => {
  const { files, columnCount, selectedFileIds, thumbnails, toggleSelectFile, openModal, showContextMenu } = data
  const index = rowIndex * columnCount + columnIndex
  if (index >= files.length) return null
  const file = files[index]
  const isSelected = selectedFileIds.has(file.id)
  const thumbUrl = thumbnails[file.id]

  return (
    <div
      style={{
        ...style,
        left: style.left + GAP,
        top: style.top + GAP,
        width: style.width - GAP,
        height: style.height - GAP,
      }}
      className={`file-card ${isSelected ? 'selected' : ''}`}
      onClick={() => toggleSelectFile(file.id)}
      onDoubleClick={() => openModal(file)}
      onContextMenu={(e) => {
        e.preventDefault()
        showContextMenu(e.clientX, e.clientY, file.id)
      }}
    >
      <div className="file-card-thumb">
        {thumbUrl ? (
          <img src={thumbUrl} alt={file.filename} loading="lazy" />
        ) : (
          <div className="file-card-placeholder">
            {file.media_type === 'video' ? <Play size={32} /> : <Image size={32} />}
          </div>
        )}
        {file.is_favorite && <Star size={14} className="star-icon" />}
        {file.media_type === 'video' && file.duration && (
          <span className="duration-badge">{Math.round(file.duration)}s</span>
        )}
      </div>
      <div className="file-card-info">
        <span className="file-card-name" title={file.filename}>{file.filename}</span>
        <span className="file-card-date">
          {file.media_created_at ? new Date(file.media_created_at).toLocaleDateString() : ''}
        </span>
      </div>
    </div>
  )
}

export default function FileGrid({ files, onLoadMore, hasMore }) {
  const { toggleSelectFile, selectedFileIds, openModal, showContextMenu } = useStore()
  const containerRef = useRef(null)
  const [containerWidth, setContainerWidth] = useState(800)
  const [containerHeight, setContainerHeight] = useState(600)
  const [thumbnails, setThumbnails] = useState({})

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width)
        setContainerHeight(entry.contentRect.height)
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const map = {}
    for (const f of files) {
      if (f.thumbnail_path) {
        map[f.id] = getThumbnailUrl(f.id)
      }
    }
    setThumbnails(map)
  }, [files])

  const columnCount = Math.max(1, Math.floor((containerWidth - GAP) / (CARD_WIDTH + GAP)))
  const rowCount = Math.max(0, Math.ceil(files.length / columnCount))

  const handleScroll = useCallback(({ scrollDirection, scrollOffset, scrollUpdateWasRequested }) => {
    if (!scrollUpdateWasRequested && hasMore) {
      const totalHeight = rowCount * (CARD_HEIGHT + GAP)
      if (scrollOffset + containerHeight * 0.8 >= totalHeight) {
        onLoadMore?.()
      }
    }
  }, [hasMore, rowCount, containerHeight, onLoadMore])

  if (files.length === 0) return null

  return (
    <div ref={containerRef} className="file-grid-container">
      <Grid
        columnCount={columnCount}
        columnWidth={CARD_WIDTH + GAP}
        defaultHeight={containerHeight}
        defaultWidth={containerWidth}
        rowCount={rowCount}
        rowHeight={CARD_HEIGHT + GAP}
        overscanCount={3}
        onScroll={handleScroll}
        cellComponent={CellComponent}
        cellProps={{
          files,
          columnCount,
          selectedFileIds,
          thumbnails,
          toggleSelectFile,
          openModal,
          showContextMenu,
        }}
      />
    </div>
  )
}
