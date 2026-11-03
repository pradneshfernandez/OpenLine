import { Alert, Anchor, Box, Button, Group, List, Paper, Select, Switch, Table, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { IconFileExport, IconFlag, IconLock, IconPhoneOutgoing, IconPlugConnectedX } from '@tabler/icons-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api, ApiError, csvUrl, versionPath, voiceApi } from '../api'
import { ChannelBadge, InterviewStatusBadge, StatusBadge, ToneBadge } from '../components/badges'
import { ErrorNotice, fmtDate, maskPhone, PageBody, PageHeader, SkeletonRows } from '../components/layout'
import { LANG_OPTIONS, type LangCode, langName } from '../languages'

const STATUSES = ['queued', 'ringing', 'in-progress', 'completed', 'partial', 'refused', 'callback', 'no-answer', 'busy', 'failed']
const MISSING_HELP: Record<string, string> = {
  GNANI_API_KEY: 'Speech — GNANI_API_KEY',
  LLM_API_KEY: 'LLM — LLM_API_KEY (or the provider key)',
  TWILIO_ACCOUNT_SID: 'Telephony — TWILIO_ACCOUNT_SID',
  TWILIO_AUTH_TOKEN: 'Telephony — TWILIO_AUTH_TOKEN',
  TWILIO_FROM_NUMBER: 'Telephony — TWILIO_FROM_NUMBER',
  PUBLIC_BASE_URL: 'Tunnel — PUBLIC_BASE_URL (ngrok)',
}

export default function Interviews() {
  const formId = Number(useParams().formId)
  const qc = useQueryClient()
  const form = useQuery({ queryKey: ['form', formId], queryFn: () => api.form(formId) })
  const status = useQuery({ queryKey: ['voice-status'], queryFn: voiceApi.status })
  const interviews = useQuery({
    queryKey: ['interviews', formId],
    queryFn: () => voiceApi.interviews(formId),
    refetchInterval: 4000, // calls in progress update live
  })

  const [to, setTo] = useState('')
  const [focused, setFocused] = useState(false)
  const [language, setLanguage] = useState<LangCode>('en')
  const [label, setLabel] = useState('')
  const [versionId, setVersionId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  const [flaggedOnly, setFlaggedOnly] = useState(false)
  const converted = (form.data?.versions ?? []).filter((v) => v.has_xform)
  const chosenVersion = versionId ?? (form.data?.latest_version_id ? String(form.data.latest_version_id) : null)
  const chosen = converted.find((v) => String(v.id) === chosenVersion)
  const number = to.replace(/[\s()-]/g, '')
  const validNumber = /^\+[1-9]\d{6,14}$/.test(number)

  const call = useMutation({
    mutationFn: () => voiceApi.call({ to: number, form_version_id: Number(chosenVersion), language, participant_label: label }),
    onSuccess: (r) => {
      notifications.show({ color: 'blue', title: 'Calling…', message: <Anchor component={Link} to={`/interviews/${r.interview_id}`}>Open interview #{r.interview_id} to watch it live</Anchor> })
      setTo('')
      qc.invalidateQueries({ queryKey: ['interviews', formId] })
    },
  })

  if (form.isLoading) return <><PageHeader title="Phone interviews" /><PageBody><SkeletonRows /></PageBody></>
  if (!form.data) return <PageBody><ErrorNotice title="Form not found" detail={(form.error as Error | null)?.message} /></PageBody>
  const f = form.data
  const latest = f.versions.find((v) => v.id === f.latest_version_id)
  const missing = status.data?.missing ?? []
  const notConfigured = missing.length > 0
  const all = interviews.data ?? []
  const rows = all.filter((i) => (!statusFilter || i.status === statusFilter) && (!flaggedOnly || (i.flagged_count ?? 0) > 0))

  return (
    <>
      <PageHeader crumbs={[{ label: 'Forms', to: '/' }, { label: f.title, to: latest ? versionPath(latest) : undefined }, { label: 'Phone interviews' }]}
        title="Phone interviews"
        actions={<Button component="a" href={csvUrl(formId)} variant="default" leftSection={<IconFileExport size={16} />}>Export CSV</Button>} />
      <PageBody maw={1400}>
        <Paper bg="white" p="md">
          <Group gap={8} align="baseline" mb="sm">
            <Text fw={600}>Start a call</Text>
            <Text size="xs" c="gray.7">Try it on your own phone first. The call opens live in the interview page.</Text>
          </Group>
          {notConfigured && (
            <Alert color="yellow" icon={<IconPlugConnectedX />} mb="md" title="Calling isn't set up yet">
              <Text size="sm">Some keys are missing in <span className="vs-mono">apps/api/.env</span>, so the app can't place phone calls. Add them and restart the API.</Text>
              <List size="sm" mt={6}>
                {missing.map((m) => <List.Item key={m}>{MISSING_HELP[m.toUpperCase()] ?? m} <Text span size="sm" c="gray.7">missing</Text></List.Item>)}
              </List>
              <Button mt="sm" variant="default" component={Link} to="/settings">Open Settings</Button>
            </Alert>
          )}
          <Group align="flex-start" gap="sm" wrap="nowrap">
            <TextInput label="Phone number" w={240} placeholder="+91 98765 43210" disabled={notConfigured}
              value={focused || !to ? to : maskPhone(to)} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
              onChange={(e) => setTo(e.currentTarget.value)} error={to && !focused && !validNumber ? 'Use E.164, e.g. +91 98765 43210' : undefined}
              description={<Group gap={3} component="span"><IconLock size={11} />Not stored. E.164 format.</Group>} />
            <Select label="Language" w={160} data={LANG_OPTIONS} searchable value={language} disabled={notConfigured} allowDeselect={false}
              onChange={(v) => setLanguage((v ?? 'en') as LangCode)} />
            <TextInput label="Participant label" placeholder="e.g. Test – own phone" style={{ flex: 1 }} value={label} disabled={notConfigured}
              description="Shown instead of the number" onChange={(e) => setLabel(e.currentTarget.value)} />
            <Box w={200}>
              <Select label="Form version" value={chosenVersion} onChange={setVersionId} disabled={notConfigured} allowDeselect={false}
                data={converted.map((v) => ({ value: String(v.id), label: `v${v.version_no}${v.id === f.latest_version_id ? ' · latest' : ''}` }))} />
              {chosen && <Box mt={4}><StatusBadge status={chosen.phone_status} /></Box>}
            </Box>
            <Button mt={25} leftSection={<IconPhoneOutgoing size={16} />} loading={call.isPending}
              disabled={!validNumber || !chosenVersion || notConfigured} onClick={() => call.mutate()}>Call</Button>
          </Group>
          {chosen?.phone_status === 'not_ready' && (
            <Text size="xs" c="red.6" mt="xs">This version has open blockers; some questions can't be asked as written.</Text>
          )}
          {call.error && <Box mt="sm"><ErrorNotice title="The call couldn't be placed" detail={(call.error as ApiError).message} /></Box>}
        </Paper>

        <Group justify="space-between">
          <Group gap={8} align="baseline">
            <Text fw={600}>Interviews</Text>
            <Text size="xs" c="gray.7" className="vs-num">{rows.length} of {all.length}</Text>
          </Group>
          <Group gap="sm">
            <Select w={170} placeholder="Any status" clearable value={statusFilter} onChange={setStatusFilter} aria-label="Filter by status"
              data={STATUSES.map((s) => ({ value: s, label: s.replace('-', ' ') }))} />
            <Switch label="Flagged only" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.currentTarget.checked)} />
          </Group>
        </Group>

        {interviews.isLoading ? <SkeletonRows /> : (
          <Paper bg="white" style={{ overflow: 'hidden' }}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th w={80}>ID</Table.Th>
                  <Table.Th>Participant</Table.Th>
                  <Table.Th>Channel</Table.Th>
                  <Table.Th>Language</Table.Th>
                  <Table.Th>Version</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th ta="right">Answers</Table.Th>
                  <Table.Th ta="right">Flagged</Table.Th>
                  <Table.Th ta="right">Avg reply delay</Table.Th>
                  <Table.Th>Started at</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((i) => (
                  <Table.Tr key={i.id}>
                    <Table.Td><Anchor component={Link} to={`/interviews/${i.id}`} className="vs-mono" size="sm" fw={600}>#{String(i.id).padStart(4, '0')}</Anchor></Table.Td>
                    <Table.Td><Text size="sm">{i.participant_label || '—'}</Text></Table.Td>
                    <Table.Td><ChannelBadge channel={i.channel} /></Table.Td>
                    <Table.Td><Text size="sm">{langName(i.language)}</Text></Table.Td>
                    <Table.Td><Text size="sm">v{i.version_no}</Text></Table.Td>
                    <Table.Td>
                      <InterviewStatusBadge status={i.status} />
                      {i.status === 'callback' && i.callback_when && <Text size="xs" c="gray.7">{i.callback_when}</Text>}
                      {i.error && <Text size="xs" c="red.6" lineClamp={2} maw={260}>{i.error}</Text>}
                    </Table.Td>
                    <Table.Td ta="right" className="vs-num">{i.answer_count ?? 0}</Table.Td>
                    <Table.Td ta="right">
                      {i.flagged_count ? <ToneBadge tone="warning" icon={IconFlag} size="sm"><span className="vs-num">{i.flagged_count}</span></ToneBadge>
                        : <Text size="sm" c="gray.7">0</Text>}
                    </Table.Td>
                    <Table.Td ta="right" className="vs-num">{i.avg_latency_ms != null ? `${(i.avg_latency_ms / 1000).toFixed(2)} s` : '—'}</Table.Td>
                    <Table.Td className="vs-num" style={{ whiteSpace: 'nowrap' }}>{fmtDate(i.started_at ?? i.created_at)}</Table.Td>
                  </Table.Tr>
                ))}
                {!rows.length && (
                  <Table.Tr><Table.Td colSpan={10}><Text c="gray.7" ta="center" py="lg" size="sm">
                    {all.length ? 'No interviews match these filters.' : 'No interviews yet. Start a call above — try your own phone first.'}
                  </Text></Table.Td></Table.Tr>
                )}
              </Table.Tbody>
            </Table>
          </Paper>
        )}
      </PageBody>
    </>
  )
}
