import {
  Anchor,
  Box,
  Button,
  Collapse,
  Group,
  Modal,
  MultiSelect,
  NumberInput,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  TagsInput,
  Text,
  Textarea,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { IconAdjustments, IconArrowBackUp, IconArrowRight, IconMessageCheck, IconRefresh } from '@tabler/icons-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiError, type Issue, type Thresholds, versionPath } from '../api'
import {
  IssueStateBadge,
  SEVERITIES,
  SEVERITY_ICON,
  SEVERITY_LABEL,
  SEVERITY_TONE,
  SeverityBadge,
  SeverityLegend,
  StatusBadge,
} from '../components/badges'
import { ErrorNotice, fmtDate, PageBody, PageHeader, SkeletonRows, Tile } from '../components/layout'
import { useRouteVersion } from '../hooks'
import { tone } from '../theme'

export default function Report() {
  const qc = useQueryClient()
  const version = useRouteVersion()
  const versionId = version.data?.id ?? 0
  const [severity, setSeverity] = useState('all')
  const [state, setState] = useState('open')
  const [accepting, setAccepting] = useState<Issue | null>(null)
  const [settingsOpen, { toggle: toggleSettings }] = useDisclosure(false)

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['version'] })
    qc.invalidateQueries({ queryKey: ['forms'] })
  }
  const rerun = useMutation({
    mutationFn: () => api.rerunCheck(versionId),
    onSuccess: () => { refresh(); notifications.show({ message: 'Phone check re-run', color: 'green' }) },
  })
  const reopen = useMutation({ mutationFn: (id: number) => api.reopenIssue(id), onSuccess: refresh })

  const v = version.data
  if (version.isLoading) return <><PageHeader title="Phone-check report" /><PageBody><SkeletonRows /></PageBody></>
  if (!v) return <PageBody><ErrorNotice title="Version not found" detail={(version.error as Error | null)?.message} /></PageBody>
  const r = v.report
  const crumbs = [{ label: 'Forms', to: '/' }, { label: v.form.title, to: versionPath(v) }, { label: 'Phone-check report' }]
  if (!r) {
    return (
      <>
        <PageHeader crumbs={crumbs} title="Phone-check report" />
        <PageBody><Paper bg="white" p={48} ta="center"><Text c="gray.7" mb="md">This version hasn't been checked yet.</Text>
          <Button leftSection={<IconRefresh size={16} />} loading={rerun.isPending} onClick={() => rerun.mutate()}>Run check</Button></Paper></PageBody>
      </>
    )
  }

  const issues = r.issues.filter((i) => (severity === 'all' || i.severity === severity) && (state === 'all' || i.state === state))
  const open = r.issues.filter((i) => i.state === 'open')
  const stateCount = (s: string) => r.issues.filter((i) => s === 'all' || i.state === s).length

  return (
    <>
      <PageHeader crumbs={crumbs} title="Phone-check report"
        subtitle={<><Anchor component={Link} to={versionPath(v)}>{v.form.title}</Anchor> · v{v.version_no}{!v.is_latest && ' (older version)'} · checked {fmtDate(r.run_at)}</>}
        actions={<>
          <Button variant={settingsOpen ? 'light' : 'default'} leftSection={<IconAdjustments size={16} />} onClick={toggleSettings} aria-expanded={settingsOpen}>Thresholds</Button>
          <Button leftSection={<IconRefresh size={16} />} loading={rerun.isPending} onClick={() => rerun.mutate()}>Run check again</Button>
        </>} />
      <PageBody maw={1400}>
        <Collapse expanded={settingsOpen}>
          <ThresholdsEditor projectId={v.form.project_id} onSaved={() => rerun.mutate()} />
        </Collapse>

        <SimpleGrid cols={{ base: 2, md: 5 }} spacing="sm">
          <Tile label="Status"><Box mt={6}><StatusBadge status={r.status} /></Box></Tile>
          <Tile label="Estimated call" value={`~${r.estimated_minutes} min`}
            note={`words ÷ ${r.thresholds.words_per_minute} wpm + ${r.thresholds.seconds_per_answer} s per answer`} />
          {SEVERITIES.map((s) => {
            const I = SEVERITY_ICON[s]
            const n = open.filter((i) => i.severity === s).length
            return (
              <Tile key={s} label={`Open ${SEVERITY_LABEL[s].toLowerCase()}s`} icon={<I size={14} color={tone[SEVERITY_TONE[s]].ic} />}
                value={<Text span inherit c={n ? tone[SEVERITY_TONE[s]].fg : undefined}>{n}</Text>} note={`open of ${r.counts[s]}`} />
            )
          })}
        </SimpleGrid>

        <Paper bg="white" style={{ overflow: 'hidden' }}>
          <Group p="sm" justify="space-between" style={{ borderBottom: '1px solid var(--vs-line)' }}>
            <Group gap="md">
              <Group gap={6}><Text size="xs" c="gray.7" fw={500}>Severity</Text>
                <SegmentedControl value={severity} onChange={setSeverity} data={[
                  { value: 'all', label: 'All' }, ...SEVERITIES.map((s) => ({ value: s, label: SEVERITY_LABEL[s] })),
                ]} /></Group>
              <Group gap={6}><Text size="xs" c="gray.7" fw={500}>State</Text>
                <SegmentedControl value={state} onChange={setState} data={[
                  { value: 'open', label: `Open ${stateCount('open')}` }, { value: 'accepted', label: `Accepted ${stateCount('accepted')}` },
                  { value: 'fixed', label: `Fixed ${stateCount('fixed')}` }, { value: 'all', label: 'All' },
                ]} /></Group>
            </Group>
            <SeverityLegend />
          </Group>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={110}>Severity</Table.Th>
                <Table.Th w={190}>Check</Table.Th>
                <Table.Th w={180}>Question</Table.Th>
                <Table.Th>Message and suggested fix</Table.Th>
                <Table.Th w={250} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {issues.map((i) => (
                <Table.Tr key={i.id}>
                  <Table.Td><SeverityBadge severity={i.severity} /></Table.Td>
                  <Table.Td><Text size="sm" fw={500}>{i.check_title}</Text></Table.Td>
                  <Table.Td>{i.question_name ? <Text size="sm" className="vs-mono">{i.question_name}</Text> : <Text size="sm" c="gray.7" fs="italic">whole form</Text>}</Table.Td>
                  <Table.Td>
                    <Text size="sm">{i.message}</Text>
                    {i.state !== 'fixed' && <Text size="xs" c="gray.7" mt={2}><b>Fix:</b> {i.suggestion}</Text>}
                    {i.state === 'accepted' && (
                      <Group gap={4} mt={4} wrap="nowrap" align="flex-start">
                        <IconMessageCheck size={14} color="#1f4fa3" style={{ marginTop: 1, flexShrink: 0 }} />
                        <Text size="xs" c="brand.6"><b>Accepted:</b> {i.accepted_reason}</Text>
                      </Group>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={6} justify="flex-end" wrap="nowrap">
                      {i.state !== 'open' && <IssueStateBadge state={i.state} />}
                      {i.question_name && (
                        <Button size="compact-sm" variant="default" rightSection={<IconArrowRight size={13} />}
                          component={Link} to={`${versionPath(v)}?q=${encodeURIComponent(i.question_name)}`}>Go to question</Button>
                      )}
                      {i.state === 'open' && <Button size="compact-sm" variant="default" onClick={() => setAccepting(i)}>Accept…</Button>}
                      {i.state === 'accepted' && (
                        <Button size="compact-sm" variant="subtle" leftSection={<IconArrowBackUp size={13} />} onClick={() => reopen.mutate(i.id)}>Reopen</Button>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
              {!issues.length && (
                <Table.Tr><Table.Td colSpan={5}><Text c="gray.7" ta="center" py="lg" size="sm">
                  {r.issues.length ? 'No issues match these filters.' : 'No phone issues — every question can be asked as written.'}
                </Text></Table.Td></Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Paper>
      </PageBody>

      <AcceptModal issue={accepting} onClose={() => setAccepting(null)} onDone={refresh} />
    </>
  )
}

function AcceptModal({ issue, onClose, onDone }: { issue: Issue | null; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState('')
  const accept = useMutation({
    mutationFn: () => api.acceptIssue(issue!.id, reason),
    onSuccess: () => { setReason(''); onClose(); onDone() },
  })
  return (
    <Modal opened={!!issue} onClose={onClose} title={<Text fw={600}>Accept issue</Text>}>
      {issue && (
        <Stack>
          <Paper p="sm" bg="#f8f9fa">
            <Group gap={6} mb={4}><SeverityBadge severity={issue.severity} /><Text size="sm" fw={500}>{issue.check_title}</Text>
              {issue.question_name && <Text size="xs" className="vs-mono">{issue.question_name}</Text>}</Group>
            <Text size="sm">{issue.message}</Text>
          </Paper>
          <Textarea label="Reason" required description="Kept with the issue and shown in the report and editor." minRows={3}
            value={reason} onChange={(e) => setReason(e.currentTarget.value)} error={(accept.error as ApiError | null)?.message} data-autofocus />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>Cancel</Button>
            <Button disabled={!reason.trim()} loading={accept.isPending} onClick={() => accept.mutate()}>Accept issue</Button>
          </Group>
        </Stack>
      )}
    </Modal>
  )
}

/** Project thresholds; also used on the Settings page. */
export function ThresholdsEditor({ projectId, onSaved, saveLabel = 'Save and re-run' }: { projectId: number; onSaved?: () => void; saveLabel?: string }) {
  const settings = useQuery({ queryKey: ['settings', projectId], queryFn: () => api.settings(projectId) })
  const [edited, setValues] = useState<Thresholds | null>(null)
  const values = edited ?? settings.data?.thresholds
  const save = useMutation({
    mutationFn: () => api.saveSettings(projectId, values!),
    onSuccess: () => { setValues(null); settings.refetch(); onSaved?.(); notifications.show({ color: 'green', message: 'Thresholds saved' }) },
  })
  if (!values || !settings.data) return <SkeletonRows rows={3} />
  const num = (key: keyof Thresholds, label: string, suffix?: string) => (
    <NumberInput label={label} value={values[key] as number} min={1} suffix={suffix}
      onChange={(n) => setValues({ ...values, [key]: Number(n) || 1 })} />
  )
  return (
    <Paper bg="white" p="md">
      <Group gap={8} mb="sm" align="baseline">
        <Text fw={600}>Project thresholds</Text>
        <Text size="xs" c="gray.7">Apply to every form in this project</Text>
      </Group>
      <SimpleGrid cols={{ base: 2, md: 5 }}>
        {num('max_words', 'Max spoken words')}
        {num('max_options', 'Max options read aloud')}
        {num('max_call_minutes', 'Max call minutes')}
        {num('words_per_minute', 'Words per minute')}
        {num('seconds_per_answer', 'Seconds per answer', ' s')}
      </SimpleGrid>
      <SimpleGrid cols={2} mt="sm">
        <TagsInput label={'"Don\'t know" / "refuse" codes'} value={values.dont_know_refuse_codes}
          onChange={(v) => setValues({ ...values, dont_know_refuse_codes: v })} />
        <MultiSelect label="Disabled checks" data={settings.data.checks.map((c) => ({ value: c.code, label: c.title }))}
          value={values.disabled_checks} onChange={(v) => setValues({ ...values, disabled_checks: v })} />
      </SimpleGrid>
      <Group justify="flex-end" mt="md">
        {edited && <Button variant="default" onClick={() => setValues(null)}>Reset</Button>}
        <Button loading={save.isPending} onClick={() => save.mutate()}>{saveLabel}</Button>
      </Group>
    </Paper>
  )
}
