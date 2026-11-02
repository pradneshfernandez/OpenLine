import { Accordion, Alert, Anchor, Box, Button, Group, Menu, Paper, Select, SimpleGrid, Table, Text, TextInput } from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  IconCalendarTime,
  IconChevronDown,
  IconClock,
  IconDownload,
  IconPlayerPauseFilled,
  IconPlayerPlayFilled,
  IconRefresh,
  IconSearch,
} from '@tabler/icons-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { ApiError, campaignApi, problemsCsvUrl, type RespondentRow } from '../api'
import { CampaignStatusBadge, InterviewStatusBadge, ToneBadge } from '../components/badges'
import { ErrorNotice, fmtDate, PageBody, PageHeader, SkeletonRows } from '../components/layout'
import { CampaignProgress, OUTCOMES } from './Campaigns'

const time = (s: string | null) => (s ? new Date(s).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '—')
const elapsed = (s: string) => {
  const t = Math.max(0, (Date.now() - new Date(s).getTime()) / 1000)
  return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(Math.floor(t % 60)).padStart(2, '0')}`
}
const STATE_LABEL: Record<RespondentRow['state'], string> = { waiting: 'to call', calling: 'on a call', done: 'done', stopped: 'never call again' }

export default function CampaignDetail() {
  const id = Number(useParams().campaignId)
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [outcome, setOutcome] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['campaign', id], queryFn: () => campaignApi.get(id),
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 4000 : false),
  })
  const navigate = useNavigate()
  const remove = useMutation({
    mutationFn: () => campaignApi.remove(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['campaigns'] }); navigate('/campaigns') },
  })
  const act = useMutation({
    mutationFn: (a: 'start' | 'pause' | 'resume' | 'finish') => campaignApi.action(id, a),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['campaign', id] }); qc.invalidateQueries({ queryKey: ['campaigns'] }) },
  })

  if (q.isLoading) return <><PageHeader title="Campaign" /><PageBody><SkeletonRows /></PageBody></>
  const c = q.data
  if (!c) return <PageBody><ErrorNotice title="Campaign not found" detail={(q.error as Error | null)?.message} /></PageBody>
  const s = c.settings
  const gap = s.min_gap_minutes >= 60 ? `${+(s.min_gap_minutes / 60).toFixed(1)} h` : `${s.min_gap_minutes} min`
  const rows = c.respondents.filter((r) => (!search || r.respondent_id.toLowerCase().includes(search.toLowerCase()))
    && (!outcome || (outcome === 'none' ? !r.last_outcome : r.last_outcome === outcome)))
  const primary = c.status === 'draft' ? ['start', 'Start campaign', IconPlayerPlayFilled] as const
    : c.status === 'running' ? ['pause', 'Pause campaign', IconPlayerPauseFilled] as const
      : c.status === 'paused' ? ['resume', 'Resume campaign', IconPlayerPlayFilled] as const : null
  const PrimaryIcon = primary?.[2] ?? IconPlayerPlayFilled

  return (
    <>
      <PageHeader crumbs={[{ label: 'Campaigns', to: '/campaigns' }, { label: c.name }]} title={c.name} extra={<CampaignStatusBadge status={c.status} />}
        subtitle={`${c.form.title} · v${c.form.version_no} · ${s.calling_start}–${s.calling_end} · ${s.max_attempts} attempts, ${gap} apart · ${s.concurrency} at a time`}
        actions={<>
          {primary && (
            <Button variant={c.status === 'running' ? 'default' : 'filled'} leftSection={<PrimaryIcon size={14} />} loading={act.isPending}
              onClick={() => act.mutate(primary[0])}>{primary[1]}</Button>
          )}
          <Menu position="bottom-end">
            <Menu.Target><Button variant="default" px={8} aria-label="More actions"><IconChevronDown size={16} /></Button></Menu.Target>
            <Menu.Dropdown>
              {c.status !== 'finished' && <Menu.Item onClick={() => act.mutate('finish')}>Finish now (stop calling)</Menu.Item>}
              <Menu.Item color="red" disabled={c.status === 'running' || c.status === 'paused'} onClick={() => remove.mutate()}>
                Delete campaign{c.status === 'running' || c.status === 'paused' ? ' (finish it first)' : ''}
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </>}>
        <Group gap="md" py="sm">
          <CampaignProgress c={c} width={560} />
          <Text size="sm" className="vs-num"><b>{c.completed.toLocaleString()} of {c.total.toLocaleString()}</b> completed · {c.done.toLocaleString()} finished in total (any outcome)</Text>
        </Group>
      </PageHeader>
      <PageBody maw={1500}>
        {act.error && <ErrorNotice title="Couldn't change the campaign" message={(act.error as ApiError).message} />}
        {c.status === 'running' && !c.in_window && (
          <Alert color="blue" icon={<IconClock />}>Outside calling hours ({s.calling_start}–{s.calling_end} IST). Calls resume when the window opens.</Alert>
        )}
        {c.status === 'paused' && <Alert color="yellow" icon={<IconPlayerPauseFilled />}>Paused — no new calls are placed. If calling isn't set up, the campaign pauses itself; check <Anchor component={Link} to="/settings">Settings</Anchor>.</Alert>}

        <SimpleGrid cols={{ base: 4, lg: 8 }} spacing="sm">
          {OUTCOMES.map((o) => (
            <Paper key={o} bg="white" p="sm">
              <InterviewStatusBadge status={o} />
              <Text fz={22} fw={600} mt={4} className="vs-num">{(c.outcomes[o] ?? 0).toLocaleString()}</Text>
            </Paper>
          ))}
        </SimpleGrid>

        <SimpleGrid cols={2} spacing="md">
          <Paper bg="white" style={{ overflow: 'hidden' }}>
            <Group gap={8} px="md" py={10} style={{ borderBottom: '1px solid var(--vs-line)' }}>
              <Text fw={600}>In progress now</Text><Text size="xs" c="gray.7">{c.in_progress.length} of {s.concurrency} lines busy</Text>
            </Group>
            <Table>
              <Table.Tbody>
                {c.in_progress.map((p) => (
                  <Table.Tr key={p.interview_id}>
                    <Table.Td><InterviewStatusBadge status={p.status} /></Table.Td>
                    <Table.Td className="vs-mono">{p.phone}</Table.Td>
                    <Table.Td className="vs-mono">{elapsed(p.started_at)}</Table.Td>
                    <Table.Td><Text size="sm">{p.respondent_id}</Text></Table.Td>
                    <Table.Td ta="right"><Anchor component={Link} to={`/interviews/${p.interview_id}`} size="sm" underline="always">Watch live</Anchor></Table.Td>
                  </Table.Tr>
                ))}
                {!c.in_progress.length && <Table.Tr><Table.Td><Text size="sm" c="gray.7" py="sm">No calls right now.</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Paper>
          <Paper bg="white" style={{ overflow: 'hidden' }}>
            <Group gap={8} px="md" py={10} style={{ borderBottom: '1px solid var(--vs-line)' }}>
              <Text fw={600}>Coming up</Text><Text size="xs" c="gray.7">Retries and callbacks</Text>
            </Group>
            <Table>
              <Table.Tbody>
                {c.upcoming.map((r) => (
                  <Table.Tr key={r.id}>
                    <Table.Td className="vs-mono" fw={600}>{time(r.next_attempt_at)}</Table.Td>
                    <Table.Td>{r.last_outcome === 'callback'
                      ? <ToneBadge tone="info" icon={IconCalendarTime} size="sm">callback</ToneBadge>
                      : <ToneBadge tone="neutral" icon={IconRefresh} size="sm">retry</ToneBadge>}</Table.Td>
                    <Table.Td className="vs-mono">{r.phone}</Table.Td>
                    <Table.Td><Text size="xs" c="gray.7">{r.last_outcome === 'callback' && r.callback_when ? `Asked: ${r.callback_when}` : `Attempt ${r.attempts + 1} · last: ${r.last_outcome.replace('-', ' ')}`}</Text></Table.Td>
                  </Table.Tr>
                ))}
                {!c.upcoming.length && <Table.Tr><Table.Td><Text size="sm" c="gray.7" py="sm">No retries or callbacks scheduled.</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Paper>
        </SimpleGrid>

        <Group justify="space-between">
          <Group gap={8} align="baseline"><Text fw={600}>Respondents</Text><Text size="xs" c="gray.7" className="vs-num">{rows.length} of {c.total}</Text></Group>
          <Group gap="sm">
            <TextInput w={240} placeholder="Respondent ID" leftSection={<IconSearch size={14} />} value={search} onChange={(e) => setSearch(e.currentTarget.value)} aria-label="Search respondents" />
            <Select w={170} placeholder="Any outcome" clearable value={outcome} onChange={setOutcome} aria-label="Filter by outcome"
              data={[{ value: 'none', label: 'not called yet' }, ...OUTCOMES.map((o) => ({ value: o, label: o.replace('-', ' ') }))]} />
          </Group>
        </Group>
        <Paper bg="white" style={{ overflow: 'hidden' }}>
          <Table>
            <Table.Thead>
              <Table.Tr><Table.Th>Respondent</Table.Th><Table.Th>Phone</Table.Th><Table.Th>Language</Table.Th><Table.Th ta="right">Attempts</Table.Th>
                <Table.Th>Last outcome</Table.Th><Table.Th>Next attempt</Table.Th><Table.Th>Interviews</Table.Th></Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.slice(0, 500).map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td className="vs-mono">{r.respondent_id}</Table.Td>
                  <Table.Td className="vs-mono">{r.phone}</Table.Td>
                  <Table.Td>{r.language === 'hi' ? 'Hindi' : 'English'}</Table.Td>
                  <Table.Td ta="right" className="vs-num">{r.attempts} of {s.max_attempts}</Table.Td>
                  <Table.Td>{r.last_outcome ? <InterviewStatusBadge status={r.last_outcome} /> : <Text size="xs" c="gray.7">{STATE_LABEL[r.state]}</Text>}
                    {r.state === 'stopped' && <Text size="xs" c="gray.7">never called again</Text>}</Table.Td>
                  <Table.Td className="vs-num">{r.state === 'waiting' && r.next_attempt_at ? fmtDate(r.next_attempt_at) : r.state === 'calling' ? 'now' : '—'}</Table.Td>
                  <Table.Td>
                    <Group gap={6}>{r.interview_ids.map((iid) => <Anchor key={iid} component={Link} to={`/interviews/${iid}`} size="sm" className="vs-mono">#{String(iid).padStart(4, '0')}</Anchor>)}</Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {rows.length > 500 && <Text size="xs" c="gray.7" p="sm">Showing the first 500 — search to find a respondent.</Text>}
        </Paper>

        {c.rejected_rows.length > 0 && (
          <Accordion variant="contained" chevronPosition="left" bg="white">
            <Accordion.Item value="left">
              <Accordion.Control><Text size="sm" fw={600} span>Left out of the CSV</Text> <Text span size="sm" c="gray.7">{c.rejected_rows.length} rows from {c.csv_filename}</Text></Accordion.Control>
              <Accordion.Panel>
                <Button size="xs" variant="default" component="a" href={problemsCsvUrl(c.id)} leftSection={<IconDownload size={14} />} mb="sm">Download rows with problems</Button>
                <Table withTableBorder>
                  <Table.Thead><Table.Tr><Table.Th ta="right">Row</Table.Th><Table.Th>respondent_id</Table.Th><Table.Th>phone</Table.Th><Table.Th>language</Table.Th><Table.Th>Problem</Table.Th></Table.Tr></Table.Thead>
                  <Table.Tbody>
                    {c.rejected_rows.map((p) => (
                      <Table.Tr key={p.row}><Table.Td ta="right">{p.row}</Table.Td><Table.Td className="vs-mono">{p.respondent_id}</Table.Td>
                        <Table.Td className="vs-mono">{p.phone}</Table.Td><Table.Td>{p.language}</Table.Td><Table.Td>{p.problem}</Table.Td></Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        )}
        <Box h={1} />
      </PageBody>
    </>
  )
}
