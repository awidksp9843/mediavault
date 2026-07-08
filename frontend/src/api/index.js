import axios from 'axios'

const API_BASE = `http://${import.meta.env.VITE_BACKEND_HOST || '127.0.0.1'}:${import.meta.env.VITE_BACKEND_PORT || 8000}`

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

export async function fetchWorkspaces() {
  const { data } = await api.get('/api/workspaces')
  return data
}

export async function createWorkspace(absolutePath, alias) {
  const { data } = await api.post('/api/workspaces', { absolute_path: absolutePath, alias })
  return data
}

export async function deleteWorkspace(workspaceId) {
  const { data } = await api.delete(`/api/workspaces/${workspaceId}`)
  return data
}

export async function fetchFiles(workspaceId, { cursor, limit = 50, sortBy = 'media_created_at', sortOrder = 'desc', mediaType, folder } = {}) {
  const params = { workspace_id: workspaceId, limit, sort_by: sortBy, sort_order: sortOrder }
  if (cursor != null) params.cursor = cursor
  if (mediaType) params.media_type = mediaType
  if (folder !== undefined) params.folder = folder
  const { data } = await api.get('/api/files', { params })
  return data
}

export async function searchFiles(workspaceId, { query, person, tag, mediaType, limit = 50 } = {}) {
  const params = { workspace_id: workspaceId, limit }
  if (query) params.query = query
  if (person) params.person = person
  if (tag) params.tag = tag
  if (mediaType) params.media_type = mediaType
  const { data } = await api.get('/api/files/search', { params })
  return data
}

export function getThumbnailUrl(fileId) {
  return `${API_BASE}/api/thumbnails/${fileId}`
}

export function getMediaUrl(fileId) {
  return `${API_BASE}/api/media/${fileId}`
}

export async function moveFiles(fileIds, destinationPath) {
  const { data } = await api.post('/api/files/move', { file_ids: fileIds, destination_path: destinationPath })
  return data
}

export async function deleteFile(fileId, hard = false) {
  const { data } = await api.delete(`/api/files/${fileId}`, { params: { hard } })
  return data
}

export async function toggleFavorite(fileId) {
  const { data } = await api.patch(`/api/files/${fileId}/favorite`)
  return data
}

export async function addTags(fileIds, tags) {
  const { data } = await api.post('/api/files/tags', { file_ids: fileIds, tags })
  return data
}

export async function fetchFolders(workspaceId) {
  const { data } = await api.get('/api/folders', { params: { workspace_id: workspaceId } })
  return data
}



export default api
