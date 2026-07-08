import { useState } from 'react'
import { Grid3X3, List, ArrowUpDown, Filter, Image, Video, Star, Tag, Sparkles } from 'lucide-react'
import useStore from '../store/useStore'
import { addTags, autoTagFiles, autoTagAllFiles } from '../api'

export default function Toolbar({ onRefresh }) {
  const {
    viewMode, setViewMode,
    sortBy, setSortBy, sortOrder, setSortOrder,
    filterMediaType, setFilterMediaType,
    filterFavorites, setFilterFavorites,
    selectedFileIds, clearSelection, selectAll, files, totalCount,
    activeWorkspaceId,
  } = useStore()

  const autoTagProgress = useStore(s => s.autoTagProgress)
  const [showTagInput, setShowTagInput] = useState(false)
  const [batchTagText, setBatchTagText] = useState('')

  const handleBatchTag = async () => {
    const tags = batchTagText.split(',').map(t => t.trim().toLowerCase()).filter(Boolean)
    if (tags.length === 0 || selectedFileIds.size === 0) return
    try {
      const fileIds = Array.from(selectedFileIds)
      await addTags(fileIds, tags)
      setBatchTagText('')
      setShowTagInput(false)
    } catch (e) {
      console.error('Batch tag failed', e)
    }
  }

  const handleAutoTag = async () => {
    if (selectedFileIds.size === 0 || autoTagProgress) return
    try {
      const fileIds = Array.from(selectedFileIds)
      await autoTagFiles(fileIds)
    } catch (e) {
      console.error('Auto-tag failed', e)
    }
  }

  const handleAutoTagAll = async () => {
    if (!activeWorkspaceId || autoTagProgress) return
    try {
      await autoTagAllFiles(activeWorkspaceId)
    } catch (e) {
      console.error('Auto-tag all failed', e)
    }
  }

  return (
    <div className="toolbar">
      <div className="toolbar-left">
        <span className="toolbar-count">{totalCount}개 파일</span>
        {selectedFileIds.size > 0 && (
          <>
            <span className="toolbar-selected">{selectedFileIds.size}개 선택됨</span>
            <div className="toolbar-divider" />
            <button className={`btn-icon ${showTagInput ? 'active' : ''}`} onClick={() => setShowTagInput(!showTagInput)} title="태그 추가">
              <Tag size={14} />
            </button>
            {showTagInput && (
              <div className="toolbar-tag-input">
                <input
                  type="text"
                  placeholder="태그 입력 (쉼표 구분)..."
                  value={batchTagText}
                  onChange={(e) => setBatchTagText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleBatchTag() }}
                  autoFocus
                />
                <button className="btn-primary btn-sm" onClick={handleBatchTag}>추가</button>
              </div>
            )}
            <div className="toolbar-divider" />
            <button className="btn-icon" onClick={handleAutoTag} disabled={!!autoTagProgress} title="자동 태깅 (YOLO)">
              <Sparkles size={14} />
            </button>
          </>
        )}
      </div>

      <div className="toolbar-right">
        <div className="toolbar-group">
          <button
            className={`btn-icon ${filterMediaType === null ? 'active' : ''}`}
            onClick={() => setFilterMediaType(null)} title="전체"
          >
            <Filter size={14} />
          </button>
          <button
            className={`btn-icon ${filterMediaType === 'image' ? 'active' : ''}`}
            onClick={() => setFilterMediaType('image')} title="이미지만"
          >
            <Image size={14} />
          </button>
          <button
            className={`btn-icon ${filterMediaType === 'video' ? 'active' : ''}`}
            onClick={() => setFilterMediaType('video')} title="동영상만"
          >
            <Video size={14} />
          </button>
          <button
            className={`btn-icon ${filterFavorites ? 'active' : ''}`}
            onClick={() => setFilterFavorites(filterFavorites ? null : true)} title="즐겨찾기만"
          >
            <Star size={14} />
          </button>
        </div>

        <div className="toolbar-divider" />

        <div className="toolbar-group">
          <select
            className="toolbar-select"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
          >
            <option value="media_created_at">날짜</option>
            <option value="filename">이름</option>
            <option value="size">크기</option>
            <option value="extension">유형</option>
          </select>
          <button
            className="btn-icon"
            onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
            title={sortOrder === 'asc' ? '오름차순' : '내림차순'}
          >
            <ArrowUpDown size={14} />
          </button>
        </div>

        <div className="toolbar-divider" />

        <div className="toolbar-group">
          <button className="btn-icon" onClick={handleAutoTagAll} disabled={!!autoTagProgress} title="모든 이미지 자동 태깅 (YOLO)">
            <Sparkles size={14} />
          </button>
        </div>

        <div className="toolbar-divider" />

        <div className="toolbar-group">
          <button
            className={`btn-icon ${viewMode === 'grid' ? 'active' : ''}`}
            onClick={() => setViewMode('grid')} title="그리드 보기"
          >
            <Grid3X3 size={14} />
          </button>
          <button
            className={`btn-icon ${viewMode === 'list' ? 'active' : ''}`}
            onClick={() => setViewMode('list')} title="목록 보기"
          >
            <List size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}
