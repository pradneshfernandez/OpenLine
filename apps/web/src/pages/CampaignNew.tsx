import { Alert, Anchor, Box, Button, Group, NumberInput, Paper, SegmentedControl, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { Dropzone } from '@mantine/dropzone'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { IconBan, IconCopy, IconCsv, IconFileUpload, IconLanguage, IconLock, IconPhoneOff, IconPlayerPlay, IconPlugConnectedX, IconUsers } from '@tabler/icons-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api, ApiError, campaignApi, type CsvCheck, voiceApi } from '../api'
import { StatusBadge, ToneBadge } from '../components/badges'
import { ErrorNotice, PageBody, PageHeader } from '../components/layout'
import { useProjectId } from '../hooks'

function Step({ n, title, meta, children }: { n: number; title: string; meta?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Paper bg="white" p="md">
      <Group gap={8} mb="sm" align="center">
        <Box w={20} h={20} bg="#121417" c="white" fz={12} fw={600} style={{ borderRadius: 3, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{n}</Box>
        <Title order={3}>{title}</Title>
        {meta && <Text size="xs" c="gray.7">{meta}</Text>}
      </Group>
      {children}
    </Paper>
  )
}

const TILES: [keyof CsvCheck['counts'], string, typeof IconUsers, 'success' | 'danger' | 'warning'][] = [
  ['ok', 'Rows OK', IconUsers, 'success'], ['invalid_number', 'Invalid numbers', IconPhoneOff, 'danger'],
  ['duplicate', 'Duplicates', IconCopy, 'warning'], ['unknown_language', 'Unknown language', IconLanguage, 'warning'],
]
const TONE = {
  success: ['#e7f3ec', '#a9d3b8', '#1d6b3a'], danger: ['#fbe9e7', '#efb2ab', '#a3221b'], warning: ['#fdf3dc', '#ecc979', '#7a4b00'],
}

export default function CampaignNew() {
  const projectId = useProjectId()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const forms = useQuery({ queryKey: ['forms', projectId], queryFn: () => api.forms(projectId!), enabled: projectId != null })
  const status = useQuery({ queryKey: ['voice-status'], queryFn: voiceApi.status })
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [versionId, setVersionId] = useState<string | null>(null)
  const [start, setStart] = useState('09:00')
  const [end, setEnd] = useState('19:00')
  const [attempts, setAttempts] = useState<number | string>(3)
  const [gapHours, setGapHours] = useState<number | string>(2)
  const [concurrency, setConcurrency] = useState('1')

  const check = useMutation({ mutationFn: (f: File) => campaignApi.validate(projectId!, f) })
  const create = useMutation({
    mutationFn: (startNow: boolean) => campaignApi.create(projectId!, {
      name, form_version_id: Number(versionId), file: file!, start: startNow,
      settings: { calling_start: start, calling_end: end, max_attempts: Number(attempts) || 3,
        min_gap_minutes: Math.round((Number(gapHours) || 2) * 60), concurrency: Number(concurrency), timezone: 'Asia/Kolkata' },
    }),
    onSuccess: (c) => { qc.invalidateQueries({ queryKey: ['campaigns'] }); navigate(`/campaigns/${c.id}`) },
  })

  const versions = (forms.data ?? []).filter((f) => f.latest_version).map((f) => ({
    value: String(f.latest_version!.id), label: `${f.title} · v${f.latest_version!.version_no}`,
    disabled: f.phone_status === 'not_ready', status: f.phone_status,
  }))
  const chosen = versions.find((v) => v.value === versionId)
  const res = check.data
  const ready = !!(name.trim() && file && res?.counts.ok && versionId)
  const missing = status.data?.missing ?? []

  return (
    <>
      <PageHeader crumbs={[{ label: 'Campaigns', to: '/campaigns' }, { label: 'New' }]} title="New campaign" />
      <PageBody maw={1300}>
        <Group align="flex-start" gap="lg" wrap="nowrap">
          <Stack gap="md" style={{ flex: 1, minWidth: 0 }}>
            <TextInput label="Campaign name" placeholder="e.g. Varanasi – Wave 1" maw={420} value={name} onChange={(e) => setName(e.currentTarget.value)} />

            <Step n={1} title="Respondents" meta={<>CSV with columns <span className="vs-mono">respondent_id, phone, language</span></>}>
              {!file ? (
                <Dropzone accept={['text/csv', 'application/vnd.ms-excel', '.csv']} multiple={false} maxSize={5 * 1024 * 1024}
                  onDrop={(f) => { setFile(f[0]); check.mutate(f[0]) }}
                  styles={{ root: { border: '2px dashed #8a919a', borderRadius: 4 } }}>
                  <Stack align="center" gap={6} py="md" style={{ pointerEvents: 'none' }}>
                    <IconFileUpload size={26} color="#424851" />
                    <Text size="sm"><b>Drop the respondent CSV here</b> or click to choose</Text>
                    <Text size="xs" c="gray.7">language is <span className="vs-mono">en</span> or <span className="vs-mono">hi</span>; Indian 10-digit mobiles are read as +91</Text>
                  </Stack>
                </Dropzone>
              ) : (
                <Stack gap="sm">
                  <Group justify="space-between" p="sm" style={{ border: '1px solid var(--vs-line)', borderRadius: 4 }}>
                    <Group gap="sm"><IconCsv size={22} color="#424851" />
                      <div><Text size="sm" className="vs-mono">{file.name}</Text>
                        <Text size="xs" c="gray.7">{res ? `${res.counts.ok + res.problems.length} rows` : 'Checking…'} · {Math.max(1, Math.round(file.size / 1024))} KB</Text></div>
                    </Group>
                    <Button variant="default" onClick={() => { setFile(null); check.reset() }}>Replace file</Button>
                  </Group>
                  {check.error && <ErrorNotice title="The CSV couldn't be read" message={(check.error as ApiError).message} />}
                  {res && (
                    <>
                      <SimpleGrid cols={4} spacing="sm">
                        {TILES.map(([k, label, I, t]) => (
                          <Box key={k} p="sm" bg={TONE[t][0]} style={{ border: `1px solid ${TONE[t][1]}`, borderRadius: 4 }}>
                            <Group gap={4}><I size={13} color={TONE[t][2]} /><Text size="xs" fw={500} c={TONE[t][2]}>{label}</Text></Group>
                            <Text fz={22} fw={600} className="vs-num">{res.counts[k].toLocaleString()}</Text>
                          </Box>
                        ))}
                      </SimpleGrid>
                      {res.problems.length > 0 && <Text size="xs" c="gray.8">Rows with problems are left out. Fix them in the CSV and upload a new campaign for them.</Text>}
                      <Table withTableBorder>
                        <Table.Thead><Table.Tr><Table.Th w={60} ta="right">Row</Table.Th><Table.Th>respondent_id</Table.Th><Table.Th>phone</Table.Th><Table.Th>language</Table.Th><Table.Th>Check</Table.Th></Table.Tr></Table.Thead>
                        <Table.Tbody>
                          {res.preview.map((r) => (
                            <Table.Tr key={r.row}>
                              <Table.Td ta="right" className="vs-num">{r.row}</Table.Td>
                              <Table.Td className="vs-mono">{r.respondent_id}</Table.Td>
                              <Table.Td className="vs-mono">{r.phone}</Table.Td>
                              <Table.Td>{r.language}</Table.Td>
                              <Table.Td>{r.problem ? <Text size="xs" c={r.kind === 'invalid_number' ? 'red.6' : 'yellow.7'} fw={500}>{r.problem}</Text>
                                : <ToneBadge tone="success" size="sm">OK</ToneBadge>}</Table.Td>
                            </Table.Tr>
                          ))}
                        </Table.Tbody>
                      </Table>
                      <Group gap={4}><IconLock size={12} color="#5c636d" /><Text size="xs" c="gray.7">Numbers are masked in the preview and everywhere after upload.</Text></Group>
                    </>
                  )}
                </Stack>
              )}
            </Step>

            <Step n={2} title="Form version">
              <Group align="center" gap="md">
                <Select w={380} placeholder="Pick a form" data={versions} value={versionId} onChange={setVersionId} allowDeselect={false} />
                {chosen && <StatusBadge status={chosen.status} />}
                <Text size="xs" c="gray.7" maw={240}>Versions that are Not ready can't be picked. Each form's latest version is used.</Text>
              </Group>
            </Step>

            <Step n={3} title="Calling rules" meta="Times are the respondent's local time (IST)">
              <Group align="flex-end" gap="md" wrap="wrap">
                <div>
                  <Text size="xs" fw={600} mb={4}>Calling hours</Text>
                  <Group gap={6}>
                    <TextInput type="time" w={110} value={start} onChange={(e) => setStart(e.currentTarget.value)} aria-label="Calling hours start" />
                    <Text>–</Text>
                    <TextInput type="time" w={110} value={end} onChange={(e) => setEnd(e.currentTarget.value)} aria-label="Calling hours end" />
                  </Group>
                </div>
                <NumberInput label="Max attempts per person" w={180} min={1} max={10} value={attempts} onChange={setAttempts} />
                <NumberInput label="Minimum gap between attempts" w={220} min={0.25} max={72} step={0.5} decimalScale={2} suffix=" hours" value={gapHours} onChange={setGapHours} />
                <div>
                  <Text size="xs" fw={600} mb={4}>Calls at a time</Text>
                  <SegmentedControl value={concurrency} onChange={setConcurrency} data={['1', '2', '3', '4', '5']} />
                </div>
              </Group>
              <Group gap={6} mt="sm"><IconBan size={14} color="#5c636d" /><Text size="sm" c="gray.8">Anyone who refuses or opts out is never called again, whatever the attempt count.</Text></Group>
            </Step>
          </Stack>

          <Paper bg="white" p="md" w={300} style={{ position: 'sticky', top: 24, flexShrink: 0 }}>
            <Text fw={600} mb="sm">Summary</Text>
            <Stack gap={6}>
              <Row k="Will be called" v={res ? res.counts.ok.toLocaleString() : '—'} />
              <Row k="Left out" v={res ? String(res.problems.length) : '—'} />
              <Row k="Languages" v={res ? `Hindi ${res.languages.hi} · English ${res.languages.en}` : '—'} />
              <Row k="Form" v={chosen?.label ?? '—'} />
              <Row k="Hours" v={`${start}–${end}`} />
            </Stack>
            {missing.length > 0 && (
              <Alert color="yellow" icon={<IconPlugConnectedX size={16} />} mt="md" p="xs">
                <Text size="xs">Calling isn't set up yet. A started campaign pauses until <Anchor component={Link} to="/settings" size="xs">the keys are set</Anchor>.</Text>
              </Alert>
            )}
            {create.error && <Box mt="sm"><ErrorNotice title="Couldn't create the campaign" message={(create.error as ApiError).message} /></Box>}
            <Stack gap="xs" mt="md">
              <Button leftSection={<IconPlayerPlay size={16} />} disabled={!ready} loading={create.isPending && create.variables} onClick={() => create.mutate(true)}>Start campaign</Button>
              <Button variant="default" disabled={!ready} loading={create.isPending && !create.variables} onClick={() => create.mutate(false)}>Save as draft</Button>
            </Stack>
          </Paper>
        </Group>
      </PageBody>
    </>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <Group justify="space-between" gap="xs" wrap="nowrap" align="flex-start">
      <Text size="xs" c="gray.7">{k}</Text>
      <Text size="xs" fw={600} ta="right" className="vs-num">{v}</Text>
    </Group>
  )
}
