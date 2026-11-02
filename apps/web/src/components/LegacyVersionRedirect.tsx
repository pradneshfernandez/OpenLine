import { Alert, Group, Loader } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { Navigate, useLocation, useParams } from 'react-router-dom'

import { api, versionPath } from '../api'

/** Old `/versions/:id[/report]` links → `/forms/:formId/versions/:versionNo[/report]`. */
export default function LegacyVersionRedirect({ sub = '' }: { sub?: '' | '/report' }) {
  const id = Number(useParams().versionId)
  const { search } = useLocation()
  const v = useQuery({ queryKey: ['version-id', id], queryFn: () => api.version(id) })
  if (v.isLoading) return <Group justify="center" p="xl"><Loader /></Group>
  if (!v.data) return <Alert color="red">Version not found.</Alert>
  return <Navigate replace to={`${versionPath(v.data, sub)}${search}`} />
}
