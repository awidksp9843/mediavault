import { Grid3X3, List, ArrowUpDown, Filter, Image, Video, Star } from 'lucide-react'
import useStore from '../store/useStore'

export default function Toolbar({ onRefresh }) {
  const {
    viewMode, setViewMode,
    sortBy, setSortBy, sortOrder, setSortOrder,
    filterMediaType, setFilterMediaType,
    filterFavorites, setFilterFavorites,
    selectedFileIds, clearSelection, selectAll, files, totalCount,
  } = useStore()

  return (
    <div className="toolbar">
      <div className="toolbar-left">
        <span className="toolbar-count">{totalCount}개 파일</span>
        {selectedFileIds.size > 0 && (
          <span className="toolbar-selected">{selectedFileIds.size}개 선택됨</span>
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
