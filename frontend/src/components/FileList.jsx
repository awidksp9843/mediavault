import { useCallback, useRef, useEffect, useState } from 'react'
import { List } from 'react-window'
import { Star, Play, Image } from 'lucide-react'
import useStore from '../store/useStore'
import { getThumbnailUrl } from '../api'

const ROW_HEIGHT = 48

const RowComponent = ({ index, style, files, selectedFileIds, thumbnails, selectSingleFile, toggleSelectFile, openModal, showContextMenu }) => {
  const file = files[index]
  if (!file) return null
  const isSelected = selectedFileIds.has(file.id)
  const thumbUrl = thumbnails[file.id]

  const handleClick = (e) => {
    if (e.ctrlKey || e.metaKey) {
      toggleSelectFile(file.id)
    } else {
      selectSingleFile(file.id)
    }
  }

  return (
    <div
      style={style}
      className={`file-row ${isSelected ? 'selected' : ''}`}
      onClick={handleClick}
      onDoubleClick={() => openModal(file)}
      onContextMenu={(e) => {
        e.preventDefault()
        showContextMenu(e.clientX, e.clientY, file.id)
      }}
    >
      <div className="file-row-select">
        <input type="checkbox" checked={isSelected} readOnly />
      </div>
      <div className="file-row-thumb">
        {thumbUrl ? (
          <img src={thumbUrl} alt="" />
        ) : file.media_type === 'video' ? (
          <Play size={14} />
        ) : (
          <Image size={14} />
        )}
      </div>
      <div className="file-row-name" title={file.filename}>{file.filename}</div>
      <div className="file-row-date">
        {file.media_created_at ? new Date(file.media_created_at).toLocaleDateString() : '-'}
      </div>
      <div className="file-row-size">
        {file.size > 0 ? formatSize(file.size) : '-'}
      </div>
      <div className="file-row-type">{file.extension.toUpperCase()}</div>
      {file.is_favorite && <Star size={14} className="star-icon" />}
    </div>
  )
}

export default function FileListView({ files, onLoadMore, hasMore }) {
  const { selectSingleFile, toggleSelectFile, selectedFileIds, openModal, showContextMenu } = useStore()
  const [containerHeight, setContainerHeight] = useState(600)
  const [thumbnails, setThumbnails] = useState({})

  const containerRef = useCallback((node) => {
    if (node) {
      setContainerHeight(node.clientHeight)
    }
  }, [])

  useEffect(() => {
    const map = {}
    for (const f of files.slice(0, 50)) {
      map[f.id] = getThumbnailUrl(f.id)
    }
    setThumbnails(map)
  }, [files])

  const handleScroll = useCallback(({ scrollOffset, scrollUpdateWasRequested }) => {
    if (!scrollUpdateWasRequested && hasMore) {
      const totalHeight = files.length * ROW_HEIGHT
      if (scrollOffset + containerHeight * 0.8 >= totalHeight) {
        onLoadMore?.()
      }
    }
  }, [hasMore, files.length, containerHeight, onLoadMore])

  if (files.length === 0) return null

  return (
    <div ref={containerRef} className="file-list-container">
      <div className="file-list-header">
        <div className="file-row-select" />
        <div className="file-row-thumb" />
        <div className="file-row-name">이름</div>
        <div className="file-row-date">날짜</div>
        <div className="file-row-size">크기</div>
        <div className="file-row-type">유형</div>
        <div style={{ width: 20 }} />
      </div>
      <List
        defaultHeight={containerHeight - 32}
        rowCount={files.length}
        rowHeight={ROW_HEIGHT}
        overscanCount={10}
        onScroll={handleScroll}
        rowComponent={RowComponent}
        rowProps={{
          files,
          selectedFileIds,
          thumbnails,
          selectSingleFile,
          toggleSelectFile,
          openModal,
          showContextMenu,
        }}
      />
    </div>
  )
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)}MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)}GB`
}
