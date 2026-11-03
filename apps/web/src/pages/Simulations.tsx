import {
  Alert,
  Anchor,
  Box,
  Button,
  Checkbox,
  Collapse,
  Group,
  Modal,
  NumberInput,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { IconEye, IconFlask, IconPlayerPlay, IconPlugConnectedX } from '@tabler/icons-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api, ApiError, type Noise, type Persona, simulationApi, type SimulationRow, voiceApi } from '../api'
import { RunStatusBadge } from '../components/badges'
import { ErrorNotice, fmtDate, PageBody, PageHeader, SkeletonRows } from '../components/layout'
import { useProjectId } from '../hooks'
import { langAttr, langName } from '../languages'

export const PERSONAS: { value: Persona; label: string; help: string }[] = [
  { value: 'cooperative', label: 'Cooperative', help: 'Says the answer plainly' },
  { value: 'vague', label: 'Vague', help: '"Umm... I think it\'s 34"' },
  { value: 'correcting', label: 'Correcting', help: 'Says a wrong answer, then corrects it' },
  { value: 'mixed', label: 'Mixed language', help: 'Hinglish answers' },
  { value: 'dont_know', label: "Doesn't know", help: 'Says "pata nahi" to about a third of questions' },
]
export const NOISES: { value: Noise; label: string; help: string }[] = [
  { value: 'clean', label: 'Clean line', help: 'Phone audio only (8 kHz μ-law)' },
  { value: '15db', label: 'Some noise', help: 'Street / fan rumble at 15 dB below speech' },
  { value: '5db', label: 'Loud noise', help: 'Market-level noise, 5 dB below speech' },
]
export const noiseLabel = (n: string) => NOISES.find((x) => x.value === n)?.label ?? n
export const pct = (r: number | null | undefined) => (r == null ? '—' : `${Math.round(r * 100)}%`)

export default function Simulations() {
  const projectId = useProjectId()
  const [open, setOpen] = useState(false)
  const runs = useQuery({
    queryKey: ['simulations', projectId], queryFn: () => simulationApi.list(projectId!), enabled: projectId != null,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'running' || r.status === 'queued') ? 5000 : false),
  })
  const rows = runs.data ?? []
  return (
    <>
      <PageHeader title="Simulations" subtitle="Simulated respondents with an answer key call the real agent. Measure accuracy before calling people."
        actions={<Button leftSection={<IconFlask size={16} />} onClick={() => setOpen(true)}>New simulation</Button>} />
      <PageBody maw={1300}>
        {runs.isLoading && <SkeletonRows />}
        {runs.isError && <ErrorNotice title="Couldn't load simulations" detail={(runs.error as Error).message} />}
        {runs.isSuccess && !rows.length && (
          <Paper bg="white" p={48} maw={720} mx="auto" w="100%">
            <Title order={2} fz={20}>Test the agent with simulated respondents</Title>
            <Text size="sm" c="gray.8" mt={6}>
              Each simulated respondent gets an answer key that follows the form's skip logic, then phones the agent over the same
              path as a real call and speaks its answers (Gnani voice) as one of four personas. The report compares what the agent
              saved with the key: accuracy by question and language, re-asks, and every miss.
            </Text>
            <Button mt="lg" leftSection={<IconFlask size={16} />} onClick={() => setOpen(true)}>New simulation</Button>
          </Paper>
        )}
        {!!rows.length && (
          <Paper bg="white" style={{ overflow: 'hidden' }}>
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Run</Table.Th><Table.Th>Form</Table.Th><Table.Th>Status</Table.Th><Table.Th ta="right">Calls</Table.Th>
                <Table.Th ta="right">Accuracy</Table.Th><Table.Th ta="right">Completion</Table.Th><Table.Th>Started</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {rows.map((r) => <RunRow key={r.id} r={r} />)}
              </Table.Tbody>
            </Table>
          </Paper>
        )}
      </PageBody>
      <NewSimulation opened={open} onClose={() => setOpen(false)} />
    </>
  )
}

function RunRow({ r }: { r: SimulationRow }) {
  return (
    <Table.Tr>
      <Table.Td><Anchor component={Link} to={`/simulations/${r.id}`} fw={600} size="sm">Run #{r.id}</Anchor></Table.Td>
      <Table.Td><Text size="sm">{r.form.title} · v{r.form.version_no}</Text>
        <Text size="xs" c="gray.7">{r.settings.personas.join(', ')} · {r.settings.languages.map(langName).join(' + ')}
          {r.settings.noise && r.settings.noise.some((n) => n !== 'clean') && <> · {r.settings.noise.map(noiseLabel).join(', ')}</>}</Text></Table.Td>
      <Table.Td><RunStatusBadge status={r.status} />{r.error && <Text size="xs" c="red.6">{r.error}</Text>}</Table.Td>
      <Table.Td ta="right" className="vs-num">{r.finished} of {r.runs}</Table.Td>
      <Table.Td ta="right"><Text size="sm" fw={600} className="vs-num">{pct(r.accuracy.rate)}</Text>
        <Text size="xs" c="gray.7" className="vs-num">{r.accuracy.correct} of {r.accuracy.total}</Text></Table.Td>
      <Table.Td ta="right" className="vs-num">{pct(r.completion_rate)}</Table.Td>
      <Table.Td className="vs-num">{fmtDate(r.created_at)}</Table.Td>
    </Table.Tr>
  )
}

export function NewSimulation({ opened, onClose, initial }: {
  opened: boolean; onClose: () => void; initial?: Partial<{ version: string; runs: number; personas: Persona[]; languages: string[]; noise: Noise[] }>
}) {
  const projectId = useProjectId()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const forms = useQuery({ queryKey: ['forms', projectId], queryFn: () => api.forms(projectId!), enabled: projectId != null && opened })
  const status = useQuery({ queryKey: ['voice-status'], queryFn: voiceApi.status, enabled: opened })
  const [version, setVersion] = useState<string | null>(initial?.version ?? null)
  const [runs, setRuns] = useState<number | string>(initial?.runs ?? 20)
  const [personas, setPersonas] = useState<string[]>(initial?.personas ?? PERSONAS.slice(0, 4).map((p) => p.value))
  const [noise, setNoise] = useState<string[]>(initial?.noise ?? ['clean'])
  const [languages, setLanguages] = useState<string[]>(initial?.languages ?? ['en', 'hi'])
  const [parallel, setParallel] = useState('2')
  const [preview, setPreview] = useState(false)
  const [pvLang, setPvLang] = useState('en')
  const [pvPersona, setPvPersona] = useState<Persona>('cooperative')
  const start = useMutation({
    mutationFn: () => simulationApi.start(projectId!, {
      form_version_id: Number(version), runs: Number(runs) || 1, personas: personas as Persona[], languages, parallel: Number(parallel),
      noise: noise as Noise[],
    }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ['simulations'] }); onClose(); navigate(`/simulations/${r.id}`) },
  })
  const key = useQuery({
    queryKey: ['answer-key', version, pvLang, pvPersona], enabled: preview && !!version,
    queryFn: () => simulationApi.preview(Number(version), pvLang, pvPersona),
  })
  const versions = (forms.data ?? []).filter((f) => f.latest_version).map((f) => ({
    value: String(f.latest_version!.id), label: `${f.title} · v${f.latest_version!.version_no}`,
  }))
  const missing = (status.data?.missing ?? []).filter((m) => ['GNANI_API_KEY', 'LLM_API_KEY'].includes(m))

  return (
    <Modal opened={opened} onClose={onClose} size="lg" title={<Text fw={600}>New simulation</Text>}>
      <Stack>
        {missing.length > 0 && (
          <Alert color="yellow" icon={<IconPlugConnectedX size={16} />} title="The agent can't run yet">
            Simulated calls use the real agent, which needs {missing.join(' and ')} in <span className="vs-mono">apps/api/.env</span>.
            You can still preview the answer keys below.
          </Alert>
        )}
        <Select label="Form version" placeholder="Pick a form" data={versions} value={version} onChange={setVersion} allowDeselect={false} />
        <Group grow align="flex-start">
          <NumberInput label="Number of calls" min={1} max={100} value={runs} onChange={setRuns} description="Spread evenly over personas and languages" />
          <div>
            <Text size="xs" fw={600} mb={4}>Calls at a time</Text>
            <SegmentedControl value={parallel} onChange={setParallel} data={['1', '2', '3', '4']} />
          </div>
        </Group>
        <Checkbox.Group label="Personas" value={personas} onChange={setPersonas}>
          <Stack gap={6} mt={6}>{PERSONAS.map((p) => <Checkbox key={p.value} value={p.value} label={<><b>{p.label}</b> <Text span size="xs" c="gray.7">— {p.help}</Text></>} />)}</Stack>
        </Checkbox.Group>
        <Checkbox.Group label="Languages" value={languages} onChange={setLanguages}>
          <Group mt={6}><Checkbox value="en" label="English" /><Checkbox value="hi" label={<span lang="hi">हिन्दी Hindi</span>} /></Group>
        </Checkbox.Group>
        <Checkbox.Group label="Line noise" description="Calls cycle through personas, then languages, then noise levels" value={noise} onChange={setNoise}>
          <Stack gap={6} mt={6}>{NOISES.map((n) => <Checkbox key={n.value} value={n.value} label={<><b>{n.label}</b> <Text span size="xs" c="gray.7">— {n.help}</Text></>} />)}</Stack>
        </Checkbox.Group>

        <Box>
          <Button variant="subtle" size="xs" px={0} leftSection={<IconEye size={14} />} disabled={!version} onClick={() => setPreview((p) => !p)}>
            {preview ? 'Hide' : 'Preview'} an answer key
          </Button>
          <Collapse expanded={preview && !!version}>
            <Group gap="sm" my="xs">
              <SegmentedControl size="xs" value={pvLang} onChange={setPvLang} data={[{ value: 'en', label: 'English' }, { value: 'hi', label: 'हिन्दी' }]} />
              <SegmentedControl size="xs" value={pvPersona} onChange={(v) => setPvPersona(v as Persona)} data={PERSONAS.map((p) => ({ value: p.value, label: p.label }))} />
            </Group>
            <Box mah={240} style={{ overflowY: 'auto', border: '1px solid var(--vs-line)', borderRadius: 4 }}>
              <Table>
                <Table.Thead><Table.Tr><Table.Th>Question</Table.Th><Table.Th>Key</Table.Th><Table.Th>Respondent says</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {(key.data?.script ?? []).map((s, n) => (
                    <Table.Tr key={n}>
                      <Table.Td className="vs-mono" fz={12}>{s.key ?? '(another?)'}</Table.Td>
                      <Table.Td className="vs-mono" fz={12}>{s.value}</Table.Td>
                      <Table.Td fz={13} lang={langAttr(pvLang)}>“{s.utterance}”</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Box>
          </Collapse>
        </Box>

        {start.error && <ErrorNotice title="Couldn't start the simulation" message={(start.error as ApiError).message} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button leftSection={<IconPlayerPlay size={16} />} disabled={!version || !personas.length || !languages.length || !noise.length || missing.length > 0}
            loading={start.isPending} onClick={() => start.mutate()}>Start {Number(runs) || 0} calls</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
