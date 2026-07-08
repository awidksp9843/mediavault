import { create } from 'zustand'

const useStore = create((set, get) => ({
  // Workspace
  workspaces: [],
  activeWorkspaceId: null,
  setWorkspaces: (workspaces) => set({ workspaces }),
  setActiveWorkspace: (id) => set({ activeWorkspaceId: id }),

  // Files
  files: [],
  nextCursor: null,
  totalCount: 0,
  isLoadingFiles: false,
  selectedFileIds: new Set(),
  setFiles: (files, nextCursor, totalCount) => set({ files, nextCursor, totalCount }),
  appendFiles: (files, nextCursor) =>
    set((state) => ({ files: [...state.files, ...files], nextCursor })),
  setLoadingFiles: (v) => set({ isLoadingFiles: v }),
  toggleSelectFile: (id) =>
    set((state) => {
      const next = new Set(state.selectedFileIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { selectedFileIds: next }
    }),
  clearSelection: () => set({ selectedFileIds: new Set() }),
  selectAll: () =>
    set((state) => ({ selectedFileIds: new Set(state.files.map((f) => f.id)) })),

  // Sort & Filter
  sortBy: 'media_created_at',
  sortOrder: 'desc',
  filterMediaType: null,
  filterFavorites: null, // null=all, true=favorites only
  filterFolder: '',
  searchQuery: '',
  setSortBy: (sortBy) => set({ sortBy }),
  setSortOrder: (sortOrder) => set({ sortOrder }),
  setFilterMediaType: (v) => set({ filterMediaType: v }),
  setFilterFavorites: (v) => set({ filterFavorites: v }),
  setFilterFolder: (v) => set({ filterFolder: v }),
  setSearchQuery: (v) => set({ searchQuery: v }),

  // View mode
  viewMode: 'grid', // 'grid' | 'list'
  setViewMode: (v) => set({ viewMode: v }),

  // Modal
  modalFile: null,
  openModal: (file) => set({ modalFile: file }),
  closeModal: () => set({ modalFile: null }),

  // Context menu
  contextMenu: null, // { x, y, fileId }
  showContextMenu: (x, y, fileId) => set({ contextMenu: { x, y, fileId } }),
  hideContextMenu: () => set({ contextMenu: null }),

  // Folders
  folders: [],
  setFolders: (folders) => set({ folders }),

  // WebSocket connection status
  wsConnected: false,
  setWsConnected: (v) => set({ wsConnected: v }),

  // Scan progress
  scanProgress: null,
  setScanProgress: (v) => set({ scanProgress: v }),

  // Auto-tag progress
  autoTagProgress: null, // { current, total, filename?, tags? }
  setAutoTagProgress: (v) => set({ autoTagProgress: v }),

}))

export default useStore
