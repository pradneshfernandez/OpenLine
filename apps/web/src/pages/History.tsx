import { Accordion, Anchor, Badge, Button, Group, Menu, Paper, Radio, Table, Text } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { type Icon, IconArrowRight, IconDownload, IconMinus, IconPencil, IconPlus, IconUpload } from '@tabler/icons-react'
import { useState } from 'react'
import ReactDiffViewer, { DiffMethod } from 'react-diff-viewer-continued'
import { Link, useParams } from 'react-router-dom'

import { api, downloadUrl, versionPath } from '../api'
import { StatusBadge, type Tone, ToneBadge } from '../components/badges'
import { ErrorNotice, fmtDate, PageBody, PageHeader, Panel, SkeletonRows } from '../components/layout'

// deepdiff change types (dictionary_item_added, values_changed, …) → added / removed / changed.
const changeKind = (c: string) => (/added/.test(c) ? 'added' : /removed/.test(c) ? 'removed' : 'changed')
const CHANGE: Record<string, [Icon, Tone]> = { added: [IconPlus, 'success'], removed: [IconMinus, 'danger'], changed: [IconPencil, 'info'] }

export default function History() {
  const formId = Number(useParams().formId)
  const form = useQuery({ queryKey: ['form', formId], queryFn: () => api.form(formId) })
  const log = useQuery({ queryKey: ['editlog', formId], queryFn: () => api.formEditLog(formId) })
  const [pickedA, setA] = useState<number | null>(null)
  const [pickedB, setB] = useState<number | null>(null)

  // Default comparison: the two most recent converted versions.
  const converted = (form.data?.versions ?? []).filter((v) => v.has_xform)
  const a = pickedA ?? converted[1]?.id ?? null
  const b = pickedB ?? converted[0]?.id ?? null

  if (form.isLoading) return <><PageHeader title="Version history" /><PageBody><SkeletonRows /></PageBody></>
  if (!form.data) return <PageBody><ErrorNotice title="Form not found" detail={(form.error as Error | null)?.message} /></PageBody>
  const f = form.data
  const latest = f.versions.find((v) => v.id === f.latest_version_id)

  return (
    <>
      <PageHeader crumbs={[{ label: 'Forms', to: '/' }, { label: f.title, to: latest ? versionPath(latest) : undefined }, { label: 'Version history' }]}
        title="Version history" subtitle={<>{f.title} · <span className="vs-mono">{f.form_id}</span> · saved versions never change</>}
        actions={<Button variant="default" leftSection={<IconUpload size={16} />} component={Link} to={`/forms/${f.id}/upload`}>Upload new version</Button>} />
      <PageBody maw={1400}>
        <Paper bg="white" style={{ overflow: 'hidden' }}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={56} ta="center">From</Table.Th>
                <Table.Th w={56} ta="center">To</Table.Th>
                <Table.Th w={190}>Version</Table.Th>
                <Table.Th>Change</Table.Th>
                <Table.Th>Author</Table.Th>
                <Table.Th>Time</Table.Th>
                <Table.Th>Phone check</Table.Th>
                <Table.Th w={130} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {f.versions.map((v) => (
                <Table.Tr key={v.id} bg={v.id === a || v.id === b ? 'var(--vs-brand-tint)' : undefined}>
                  <Table.Td ta="center">{v.has_xform && <Radio size="xs" checked={a === v.id} onChange={() => setA(v.id)} aria-label={`Compare from v${v.version_no}`} />}</Table.Td>
                  <Table.Td ta="center">{v.has_xform && <Radio size="xs" checked={b === v.id} onChange={() => setB(v.id)} aria-label={`Compare to v${v.version_no}`} />}</Table.Td>
                  <Table.Td>
                    <Group gap={6} wrap="nowrap">
                      {v.has_xform ? <Anchor component={Link} to={versionPath(v)} fw={600} size="sm">v{v.version_no}</Anchor> : <Text fw={600} size="sm">v{v.version_no}</Text>}
                      {v.id === f.latest_version_id && <Badge color="dark" variant="outline">latest</Badge>}
                      {v.version_no === 0 && <Text size="xs" c="gray.7">original upload</Text>}
                    </Group>
                  </Table.Td>
                  <Table.Td><Text size="sm">{v.message || '—'}</Text><Text size="xs" c="gray.7" className="vs-mono">{v.original_filename}</Text></Table.Td>
                  <Table.Td><Text size="sm">{v.created_by || '—'}</Text></Table.Td>
                  <Table.Td><Text size="sm" className="vs-num">{fmtDate(v.created_at)}</Text></Table.Td>
                  <Table.Td>{v.has_xform ? <StatusBadge status={v.phone_status} /> : <StatusBadge status={null} />}</Table.Td>
                  <Table.Td ta="right">
                    <Menu position="bottom-end">
                      <Menu.Target><Button size="compact-sm" variant="default" leftSection={<IconDownload size={14} />}>Download</Button></Menu.Target>
                      <Menu.Dropdown>
                        <Menu.Item component="a" href={downloadUrl(v.id, 'original')}>Original file (unchanged)</Menu.Item>
                        {v.has_xform && <Menu.Item component="a" href={downloadUrl(v.id, 'xlsx')}>Edited .xlsx</Menu.Item>}
                        {v.has_xform && <Menu.Item component="a" href={downloadUrl(v.id, 'xform')}>XForm XML</Menu.Item>}
                      </Menu.Dropdown>
                    </Menu>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>

        {a && b && a !== b ? <Diff a={a} b={b} /> : (
          <Text c="gray.7" size="sm">Pick two converted versions (From and To) to compare them.</Text>
        )}

        <Panel title="Edit log" meta={log.data ? `${log.data.length} changes` : undefined} p={0}>
          {!log.data?.length ? <Text c="gray.7" size="sm" p="md">No edits yet.</Text> : (
            <Table>
              <Table.Thead>
                <Table.Tr><Table.Th>Time</Table.Th><Table.Th>Who</Table.Th><Table.Th>Version</Table.Th><Table.Th>Question</Table.Th><Table.Th>Field</Table.Th><Table.Th>Old → new</Table.Th></Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {log.data.map((e) => (
                  <Table.Tr key={e.id}>
                    <Table.Td className="vs-num" style={{ whiteSpace: 'nowrap' }}>{fmtDate(e.time)}</Table.Td>
                    <Table.Td>{e.user || '—'}</Table.Td>
                    <Table.Td>v{f.versions.find((v) => v.id === e.version_id)?.version_no}</Table.Td>
                    <Table.Td className="vs-mono">{e.question_name}</Table.Td>
                    <Table.Td>{e.field}</Table.Td>
                    <Table.Td><OldNew old={e.old_value} next={e.new_value} /></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Panel>
      </PageBody>
    </>
  )
}

function OldNew({ old, next }: { old: string | null; next: string | null }) {
  return (
    <Group gap={6} wrap="nowrap" align="flex-start">
      <Text size="sm" c="red.6" td="line-through" style={{ wordBreak: 'break-word' }}>{old || '—'}</Text>
      <IconArrowRight size={13} color="#5c636d" style={{ marginTop: 3, flexShrink: 0 }} />
      <Text size="sm" c="green.6" style={{ wordBreak: 'break-word' }}>{next || '—'}</Text>
    </Group>
  )
}

function Diff({ a, b }: { a: number; b: number }) {
  const diff = useQuery({ queryKey: ['diff', a, b], queryFn: () => api.diff(a, b) })
  if (diff.isLoading) return <SkeletonRows rows={4} />
  if (!diff.data) return <ErrorNotice title="Couldn't compare these versions" detail={(diff.error as Error | null)?.message} />
  const d = diff.data
  return (
    <Panel title={`Changes from v${d.a.version_no} to v${d.b.version_no}`} meta={`${d.changes.length} changed fields`} p={0}>
      {!d.changes.length ? <Text c="gray.7" size="sm" p="md">No differences in questions or options.</Text> : (
        <Table>
          <Table.Thead><Table.Tr><Table.Th w={100}>Section</Table.Th><Table.Th>Question / choice</Table.Th><Table.Th>Field</Table.Th><Table.Th w={100}>Change</Table.Th><Table.Th>Old → new</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {d.changes.map((c, i) => (
              <Table.Tr key={i}>
                <Table.Td>{c.section === 'questions' ? 'Question' : 'Choice'}</Table.Td>
                <Table.Td className="vs-mono">{c.subject}</Table.Td>
                <Table.Td>{c.field}</Table.Td>
                <Table.Td><ToneBadge tone={CHANGE[changeKind(c.change)][1]} icon={CHANGE[changeKind(c.change)][0]} size="sm">{changeKind(c.change)}</ToneBadge></Table.Td>
                <Table.Td><OldNew old={c.old} next={c.new} /></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Accordion chevronPosition="left" styles={{ item: { borderBottom: 0, borderTop: '1px solid var(--vs-line)' } }}>
        <Accordion.Item value="xml">
          <Accordion.Control><Text size="sm" fw={600}>XForm XML, side by side</Text></Accordion.Control>
          <Accordion.Panel>
            <ReactDiffViewer oldValue={d.xform_a} newValue={d.xform_b} splitView compareMethod={DiffMethod.LINES}
              leftTitle={`v${d.a.version_no}`} rightTitle={`v${d.b.version_no}`} showDiffOnly extraLinesSurroundingDiff={2}
              styles={{ contentText: { fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 } }} />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Panel>
  )
}
