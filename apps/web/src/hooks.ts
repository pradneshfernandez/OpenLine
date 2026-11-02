import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { api } from './api'

/** Stage 1 works in a single project: the first one (created on demand by the API). */
export function useProjectId(): number | undefined {
  const q = useQuery({ queryKey: ['projects'], queryFn: api.projects, staleTime: Infinity })
  return q.data?.[0]?.id
}

/** The version in a `/forms/:formId/versions/:versionNo` route. Invalidate with `['version']`. */
export function useRouteVersion() {
  const { formId, versionNo } = useParams()
  return useQuery({
    queryKey: ['version', Number(formId), Number(versionNo)],
    queryFn: () => api.versionByNo(Number(formId), Number(versionNo)),
  })
}
