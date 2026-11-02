import { AppShell, Box, Stack, Text, TextInput, Tooltip, UnstyledButton } from '@mantine/core'
import { useLocalStorage } from '@mantine/hooks'
import { useQuery } from '@tanstack/react-query'
import {
  IconChecklist,
  IconCloudUpload,
  IconFileSpreadsheet,
  IconFlask,
  IconLayoutSidebarLeftCollapse,
  IconLayoutSidebarLeftExpand,
  IconPhoneCalling,
  IconSettings,
  type Icon,
} from '@tabler/icons-react'
import { useState } from 'react'
import { Link, matchPath, Route, Routes, useLocation } from 'react-router-dom'

import { reviewApi } from './api'
import LegacyVersionRedirect from './components/LegacyVersionRedirect'
import { useProjectId } from './hooks'
import CampaignDetail from './pages/CampaignDetail'
import CampaignNew from './pages/CampaignNew'
import Campaigns from './pages/Campaigns'
import FormsList from './pages/FormsList'
import History from './pages/History'
import Inspector from './pages/Inspector'
import InterviewDetail from './pages/InterviewDetail'
import Interviews from './pages/Interviews'
import KoboExport from './pages/KoboExport'
import Report from './pages/Report'
import Review from './pages/Review'
import Settings from './pages/Settings'
import SimulationReport from './pages/SimulationReport'
import Simulations from './pages/Simulations'
import Upload from './pages/Upload'

type NavItem = { id: string; label: string; icon: Icon; to: string }

const NAV: NavItem[] = [
  { id: 'forms', label: 'Forms', icon: IconFileSpreadsheet, to: '/' },
  { id: 'campaigns', label: 'Campaigns', icon: IconPhoneCalling, to: '/campaigns' },
  { id: 'review', label: 'Review', icon: IconChecklist, to: '/review' },
  { id: 'simulations', label: 'Simulations', icon: IconFlask, to: '/simulations' },
  { id: 'export', label: 'Kobo export', icon: IconCloudUpload, to: '/export' },
  { id: 'settings', label: 'Settings', icon: IconSettings, to: '/settings' },
]

/** The editor and interview detail need the width: the sidebar collapses to a 56px rail there. */
const RAIL_ROUTES = ['/forms/:formId/versions/:versionNo', '/interviews/:interviewId']

export default function App() {
  const { pathname } = useLocation()
  const [user, setUser] = useLocalStorage({
    key: 'forms.user',
    defaultValue: '',
    serialize: (v) => v,
    deserialize: (v) => v ?? '',
  })
  const autoRail = RAIL_ROUTES.some((p) => matchPath(p, pathname))
  // A manual toggle holds until the user moves between a rail screen and a full-sidebar screen.
  const [override, setOverride] = useState<{ auto: boolean; rail: boolean } | null>(null)
  const rail = override?.auto === autoRail ? override.rail : autoRail
  const setRail = (r: boolean) => setOverride({ auto: autoRail, rail: r })
  const active = NAV.find((n) => n.to !== '/' && pathname.startsWith(n.to))?.id ?? 'forms'
  const projectId = useProjectId()
  const reviewCount = useQuery({
    queryKey: ['review-count', projectId], queryFn: () => reviewApi.count(projectId!), enabled: projectId != null, refetchInterval: 30000,
  }).data?.pending

  return (
    <AppShell navbar={{ width: rail ? 56 : 220, breakpoint: 0 }} padding={0}>
      <AppShell.Navbar bg="#16191d" withBorder={false} className={rail ? 'vs-rail' : undefined}>
        <Stack gap={0} h="100%" c="#c9ced4">
          <Box component={Link} to="/" h={56} px={rail ? 0 : 16} display="flex"
            style={{ alignItems: 'center', justifyContent: rail ? 'center' : 'flex-start', gap: 10, borderBottom: '1px solid #2a2f36', textDecoration: 'none' }}>
            <Box w={28} h={28} bg="#ffcc00" c="#16191d" fw={700} fz={13}
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 3, flexShrink: 0 }}>VS</Box>
            {!rail && (
              <div>
                <Text c="white" fw={600} size="md" lh="18px">Voice Survey</Text>
                <Text fz={11} c="#9aa1a9">AI enumerator · Gnani</Text>
              </div>
            )}
          </Box>

          <Stack component="nav" gap={rail ? 4 : 2} p={rail ? '10px 8px' : '12px 8px'} align={rail ? 'center' : 'stretch'} style={{ flex: 1 }}>
            {NAV.map((it) => {
              const I = it.icon
              const count = it.id === 'review' && reviewCount ? reviewCount : 0
              return (
                <Tooltip key={it.id} label={count ? `${it.label} · ${count} waiting` : it.label} position="right" disabled={!rail}>
                  <Link to={it.to} className="vs-nav-item" data-active={active === it.id} aria-label={count ? `${it.label}, ${count} waiting` : it.label}
                    style={{ position: 'relative' }}>
                    <I size={rail ? 20 : 18} stroke={1.7} />
                    {!rail && <span style={{ flex: 1 }}>{it.label}</span>}
                    {count > 0 && (
                      <Text span fz={11} fw={600} bg="#ffcc00" c="#16191d" px={6} className="vs-num"
                        style={{ borderRadius: 9, lineHeight: '16px', ...(rail ? { position: 'absolute', top: 2, right: 0, fontSize: 9, padding: '0 4px' } : {}) }}>
                        {count}
                      </Text>
                    )}
                  </Link>
                </Tooltip>
              )
            })}
          </Stack>

          {rail ? (
            <Tooltip label={user || 'Set your name'} position="right">
              <UnstyledButton onClick={() => setRail(false)} mx="auto" mb={10} w={32} h={32} bg="#2a2f36" c="white" fz={12} fw={600}
                style={{ borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center' }} aria-label="Your name">
                {initials(user)}
              </UnstyledButton>
            </Tooltip>
          ) : (
            <Box px={16} pt={12} pb={10} style={{ borderTop: '1px solid #2a2f36' }}>
              <Text component="label" htmlFor="vs-user" fz={11} c="#9aa1a9" fw={500}>Your name (used in the edit log)</Text>
              <TextInput id="vs-user" mt={6} size="xs" value={user} placeholder="e.g. Priya Sharma"
                onChange={(e) => setUser(e.currentTarget.value)}
                styles={{ input: { background: '#23282e', borderColor: '#3a4048', color: '#fff' } }} />
            </Box>
          )}
          <Tooltip label={rail ? 'Expand sidebar' : 'Collapse sidebar'} position="right">
            <UnstyledButton onClick={() => setRail(!rail)} h={36} c="#9aa1a9" aria-label={rail ? 'Expand sidebar' : 'Collapse sidebar'}
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', borderTop: '1px solid #2a2f36' }}>
              {rail ? <IconLayoutSidebarLeftExpand size={18} /> : <IconLayoutSidebarLeftCollapse size={18} />}
            </UnstyledButton>
          </Tooltip>
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main>
        <Routes>
          <Route path="/" element={<FormsList />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/campaigns" element={<Campaigns />} />
          <Route path="/campaigns/new" element={<CampaignNew />} />
          <Route path="/campaigns/:campaignId" element={<CampaignDetail />} />
          <Route path="/review" element={<Review />} />
          <Route path="/simulations" element={<Simulations />} />
          <Route path="/simulations/:runId" element={<SimulationReport />} />
          <Route path="/export" element={<KoboExport />} />
          <Route path="/forms/:formId/upload" element={<Upload />} />
          <Route path="/forms/:formId/history" element={<History />} />
          <Route path="/forms/:formId/versions/:versionNo" element={<Inspector />} />
          <Route path="/forms/:formId/versions/:versionNo/report" element={<Report />} />
          <Route path="/versions/:versionId" element={<LegacyVersionRedirect />} />
          <Route path="/versions/:versionId/report" element={<LegacyVersionRedirect sub="/report" />} />
          <Route path="/forms/:formId/interviews" element={<Interviews />} />
          <Route path="/interviews/:interviewId" element={<InterviewDetail />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  )
}

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  return parts.length ? parts.slice(0, 2).map((p) => p[0].toUpperCase()).join('') : '?'
}
