import { Anchor, Box, Button, Group, Paper, Progress, SimpleGrid, Table, Text } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { IconRefresh } from '@tabler/icons-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { type Ratio, simulationApi } from '../api'
import { InterviewStatusBadge, PersonaBadge, RunStatusBadge } from '../components/badges'
import { ErrorNotice, fmtDate, PageBody, PageHeader, SkeletonRows, Tile } from '../components/layout'
import { tone } from '../theme'
import { NewSimulation, noiseLabel, pct } from './Simulations'
import { type LangCode, langAttr, langName } from '../languages'

const cellTone = (r: Ratio | undefined) => {
  if (!r || !r.total) return null
  const p = r.correct / r.total
  return p >= 0.95 ? tone.success : p >= 0.85 ? tone.warning : tone.danger
}

function Cell({ r }: { r: Ratio | undefined }) {
  const t = cellTone(r)
  if (!r || !t) return <Text size="sm" c="gray.6" ta="center">—</Text>
  return (
    <Box px={8} py={2} bg={t.bg} c={t.fg} ta="center" style={{ border: `1px solid ${t.bd}`, borderRadius: 3 }}>
      <Text size="sm" fw={600} span className="vs-num">{pct(r.correct / r.total)}</Text>
      <Text size="xs" span className="vs-num"> {r.correct}/{r.total}</Text>
    </Box>
  )
}

export default function SimulationReport() {
  const id = Number(useParams().runId)
  const [again, setAgain] = useState(false)
  const q = useQuery({
    queryKey: ['simulation', id], queryFn: () => simulationApi.get(id),
    refetchInterval: (query) => (['queued', 'running'].includes(query.state.data?.status ?? '') ? 4000 : false),
  })
  if (q.isLoading) return <><PageHeader title={`Simulation run #${id}`} /><PageBody><SkeletonRows /></PageBody></>
  const run = q.data
  if (!run) return <PageBody><ErrorNotice title="Run not found" detail={(q.error as Error | null)?.message} /></PageBody>
  const r = run.report
  const s = run.settings
  const live = run.status === 'running' || run.status === 'queued'
  const langs = s.languages as LangCode[]

  return (
    <>
      <PageHeader crumbs={[{ label: 'Simulations', to: '/simulations' }, { label: `Run #${run.id}` }]}
        title={`Simulation run #${run.id}`} extra={<RunStatusBadge status={run.status} />}
        subtitle={`${run.form.title} · v${run.form.version_no} · ${run.finished_at ? `finished ${fmtDate(run.finished_at)}` : `started ${fmtDate(run.created_at)}`}`}
        actions={<Button leftSection={<IconRefresh size={16} />} disabled={live} onClick={() => setAgain(true)}>Run again</Button>} />
      <PageBody maw={1500}>
        {run.error && <ErrorNotice title="The run stopped" message={run.error} />}
        <Paper bg="white" p="md">
          <Group gap="xl">
            <Text size="sm" fw={600}>Run settings</Text>
            <Text size="sm" c="gray.8">Calls <b>{s.runs}</b></Text>
            <Group gap={4}><Text size="sm" c="gray.8">Personas</Text>{s.personas.map((p) => <PersonaBadge key={p} persona={p} />)}</Group>
            <Text size="sm" c="gray.8">Languages <b>{langs.map(langName).join(' · ')}</b></Text>
            {s.noise && <Text size="sm" c="gray.8">Noise <b>{s.noise.map(noiseLabel).join(' · ')}</b></Text>}
            <Text size="sm" c="gray.8">{s.parallel} at a time</Text>
          </Group>
          <Text size="xs" c="gray.7" mt={6}>Each persona has an answer key that follows the form's skip logic; the agent doesn't see it.</Text>
          {live && (
            <Group mt="sm" gap="sm">
              <Progress value={(r.finished / Math.max(1, r.runs)) * 100} w={360} animated aria-label="Calls finished" />
              <Text size="sm" className="vs-num">{r.finished} of {r.runs} calls finished</Text>
            </Group>
          )}
        </Paper>

        <SimpleGrid cols={{ base: 2, lg: 5 }} spacing="sm">
          <Paper p="md" bg="#121417" c="white" style={{ borderColor: '#121417' }}>
            <Text size="xs" c="#c9ced4" fw={500}>Accuracy vs answer key</Text>
            <Text fz={44} lh="52px" fw={600} className="vs-num">{pct(r.accuracy.rate)}</Text>
            <Text size="xs" c="#c9ced4" className="vs-num">{r.accuracy.correct} of {r.accuracy.total} answers correct · {r.runs} calls</Text>
          </Paper>
          <Tile label="Completion rate" value={pct(r.completion_rate)} note={`${r.completed} of ${r.runs} reached the end`} />
          <Tile label="Re-asks" value={r.reasks} note={r.reasks_per_call != null ? `${r.reasks_per_call.toFixed(1)} per call` : '—'} />
          <Tile label="Avg time per question" value={r.seconds_per_question != null ? `${r.seconds_per_question.toFixed(1)} s` : '—'} note="ask + answer + confirm" />
          <Tile label="Reply delay" value={r.reply_delay ? `${r.reply_delay.avg.toFixed(2)} s` : '—'}
            note={r.reply_delay ? `p90 ${r.reply_delay.p90.toFixed(2)} s · target under 1.5 s` : 'respondent stops → agent speaks'} />
        </SimpleGrid>

        {(r.by_noise.length > 1 || r.by_persona.length > 1) && (
          <SimpleGrid cols={2} spacing="md">
            <Breakdown title="Accuracy by line noise" rows={r.by_noise.map((x) => ({ label: noiseLabel(x.noise), correct: x.correct, total: x.total }))} />
            <Breakdown title="Accuracy by persona" rows={r.by_persona.map((x) => ({ label: x.persona.replace('_', ' '), correct: x.correct, total: x.total }))} />
          </SimpleGrid>
        )}

        <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
          <Paper bg="white" style={{ overflow: 'hidden' }}>
            <Group justify="space-between" px="md" py={10} style={{ borderBottom: '1px solid var(--vs-line)' }}>
              <Text fw={600}>Accuracy by question × language</Text>
              <Group gap="sm">{[['≥ 95%', tone.success], ['85–94%', tone.warning], ['< 85%', tone.danger]].map(([l, t]) => (
                <Group key={l as string} gap={4}><Box w={10} h={10} bg={(t as typeof tone.success).bg} style={{ border: `1px solid ${(t as typeof tone.success).bd}` }} /><Text size="xs" c="gray.8">{l as string}</Text></Group>
              ))}</Group>
            </Group>
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Question</Table.Th>{langs.map((l) => <Table.Th key={l} w={110} ta="center">{langName(l)}</Table.Th>)}<Table.Th w={110} ta="center">All</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {r.grid.map((g) => (
                  <Table.Tr key={g.question}>
                    <Table.Td className="vs-mono">{g.question}</Table.Td>
                    {langs.map((l) => <Table.Td key={l}><Cell r={g[l]} /></Table.Td>)}
                    <Table.Td><Cell r={g.all} /></Table.Td>
                  </Table.Tr>
                ))}
                {!r.grid.length && <Table.Tr><Table.Td colSpan={4}><Text size="sm" c="gray.7" py="sm">No answers scored yet.</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Paper>
          <Paper bg="white" style={{ overflow: 'hidden' }}>
            <Group gap={8} px="md" py={10} style={{ borderBottom: '1px solid var(--vs-line)' }}>
              <Text fw={600}>Misses</Text><Text size="xs" c="gray.7">{r.misses.length} answers didn't match the key</Text>
            </Group>
            <Table>
              <Table.Thead><Table.Tr><Table.Th>Question</Table.Th><Table.Th>Persona</Table.Th><Table.Th>Heard</Table.Th><Table.Th>Expected → got</Table.Th><Table.Th /></Table.Tr></Table.Thead>
              <Table.Tbody>
                {r.misses.map((m, n) => (
                  <Table.Tr key={n}>
                    <Table.Td className="vs-mono">{m.key}</Table.Td>
                    <Table.Td><PersonaBadge persona={m.persona} /><Text size="xs" c="gray.7">{langName(m.language)}</Text></Table.Td>
                    <Table.Td maw={220}><Text size="sm" lang={langAttr(m.language)}>{m.heard ? `“${m.heard}”` : '—'}</Text></Table.Td>
                    <Table.Td><Text size="sm"><Text span c="green.7" fw={600}>{m.expected}</Text> → <Text span c="red.6" fw={600}>{m.got == null ? '(none)' : String(m.got)}</Text></Text></Table.Td>
                    <Table.Td><Anchor component={Link} to={`/interviews/${m.interview_id}`} size="sm" className="vs-mono">#{String(m.interview_id).padStart(4, '0')}</Anchor></Table.Td>
                  </Table.Tr>
                ))}
                {!r.misses.length && <Table.Tr><Table.Td colSpan={5}><Text size="sm" c="gray.7" py="sm">{r.accuracy.total ? 'Every scored answer matched the key.' : 'Nothing scored yet.'}</Text></Table.Td></Table.Tr>}
              </Table.Tbody>
            </Table>
          </Paper>
        </SimpleGrid>

        <Paper bg="white" style={{ overflow: 'hidden' }}>
          <Text fw={600} px="md" py={10} style={{ borderBottom: '1px solid var(--vs-line)' }}>Calls</Text>
          <Table>
            <Table.Thead><Table.Tr><Table.Th>Interview</Table.Th><Table.Th>Persona</Table.Th><Table.Th>Language</Table.Th><Table.Th>Status</Table.Th><Table.Th ta="right">Correct</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {r.interviews.map((i) => (
                <Table.Tr key={i.id}>
                  <Table.Td><Anchor component={Link} to={`/interviews/${i.id}`} className="vs-mono" size="sm">#{String(i.id).padStart(4, '0')}</Anchor></Table.Td>
                  <Table.Td><PersonaBadge persona={i.persona} /></Table.Td>
                  <Table.Td>{langName(i.language)}</Table.Td>
                  <Table.Td><InterviewStatusBadge status={i.status} />{i.error && <Text size="xs" c="red.6" lineClamp={1} maw={360}>{i.error}</Text>}</Table.Td>
                  <Table.Td ta="right" className="vs-num">{i.total ? `${i.correct} of ${i.total}` : '—'}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      </PageBody>
      {again && <NewSimulation opened onClose={() => setAgain(false)}
        initial={{ version: String(run.form.version_id), runs: s.runs, personas: s.personas, languages: s.languages }} />}
    </>
  )
}

function Breakdown({ title, rows }: { title: string; rows: { label: string; correct: number; total: number }[] }) {
  return (
    <Paper bg="white" style={{ overflow: 'hidden' }}>
      <Text fw={600} px="md" py={10} style={{ borderBottom: '1px solid var(--vs-line)' }}>{title}</Text>
      <Table>
        <Table.Tbody>
          {rows.map((x) => (
            <Table.Tr key={x.label}>
              <Table.Td w={180}><Text size="sm" tt="capitalize">{x.label}</Text></Table.Td>
              <Table.Td><Progress value={x.total ? (x.correct / x.total) * 100 : 0} color={cellTone(x)?.ic} aria-label={x.label} /></Table.Td>
              <Table.Td w={140}><Cell r={x} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Paper>
  )
}
