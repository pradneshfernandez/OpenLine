import { ActionIcon, Anchor, Box, Button, Group, Menu, Modal, Paper, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { IconClock, IconDots, IconHistory, IconListCheck, IconPhoneCall, IconSearch, IconTrash, IconUpload } from '@tabler/icons-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, type FormRow, versionPath } from '../api'
import { StatusBadge } from '../components/badges'
import { ErrorNotice, fmtDate, PageBody, PageHeader, SkeletonRows } from '../components/layout'
import { useProjectId } from '../hooks'
import { UploadDropzone } from './Upload'

const STATUS_FILTER = [
  { value: 'ready', label: 'Ready' },
  { value: 'ready_with_warnings', label: 'Ready with warnings' },
  { value: 'not_ready', label: 'Not ready' },
  { value: 'none', label: 'Not converted' },
]

export default function FormsList() {
  const projectId = useProjectId()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<FormRow | null>(null)
  const forms = useQuery({
    queryKey: ['forms', projectId],
    queryFn: () => api.forms(projectId!),
    enabled: projectId != null,
  })
  const del = useMutation({
    mutationFn: (id: number) => api.deleteForm(id),
    onSuccess: () => { setDeleting(null); qc.invalidateQueries({ queryKey: ['forms'] }) },
  })

  const all = forms.data ?? []
  const s = search.trim().toLowerCase()
  const rows = all.filter((f) =>
    (!s || f.title.toLowerCase().includes(s) || f.form_id.toLowerCase().includes(s)) &&
    (!status || (status === 'none' ? !f.phone_status : f.phone_status === status)))
  const empty = forms.isSuccess && !all.length

  return (
    <>
      <PageHeader title="Forms"
        subtitle={empty ? undefined : 'Questionnaires your team has uploaded. Every save creates a new version; old versions never change.'}
        actions={!empty && <Button component={Link} to="/upload" leftSection={<IconUpload size={16} />}>Upload form</Button>} />
      <PageBody>
        {forms.isError && <ErrorNotice title="Couldn't load forms" message="Is the API running on :8000?" detail={(forms.error as Error).message} />}
        {(forms.isLoading || projectId == null) && !forms.isError && <SkeletonRows />}
        {empty && <FirstRun />}
        {!!all.length && (
          <>
            <Group justify="space-between">
              <Group gap="sm">
                <TextInput w={300} placeholder="Search title or form ID" leftSection={<IconSearch size={14} />}
                  value={search} onChange={(e) => setSearch(e.currentTarget.value)} aria-label="Search forms" />
                <Select w={190} placeholder="Any status" clearable data={STATUS_FILTER} value={status} onChange={setStatus} aria-label="Filter by status" />
              </Group>
              <Text size="xs" c="gray.7">{rows.length} of {all.length} forms</Text>
            </Group>
            <Paper bg="white" style={{ overflow: 'hidden' }}>
              <Table>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Title</Table.Th>
                    <Table.Th>Form ID</Table.Th>
                    <Table.Th>Latest version</Table.Th>
                    <Table.Th>Phone check</Table.Th>
                    <Table.Th ta="right">Est. call</Table.Th>
                    <Table.Th w={48} />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((f) => <FormTableRow key={f.id} f={f} onDelete={() => setDeleting(f)} />)}
                  {!rows.length && (
                    <Table.Tr><Table.Td colSpan={6}><Text c="gray.7" ta="center" py="lg" size="sm">No forms match these filters.</Text></Table.Td></Table.Tr>
                  )}
                </Table.Tbody>
              </Table>
            </Paper>
          </>
        )}
      </PageBody>

      <Modal opened={!!deleting} onClose={() => setDeleting(null)} title={<Text fw={600}>Delete form?</Text>}>
        <Text size="sm">
          <b>{deleting?.title}</b> and all its versions, phone-check reports and interviews will be deleted. This can't be undone.
        </Text>
        <Group justify="flex-end" mt="lg">
          <Button variant="default" onClick={() => setDeleting(null)}>Cancel</Button>
          <Button color="red" loading={del.isPending} onClick={() => deleting && del.mutate(deleting.id)}>Delete form</Button>
        </Group>
      </Modal>
    </>
  )
}

function FormTableRow({ f, onDelete }: { f: FormRow; onDelete: () => void }) {
  const v = f.latest_version
  return (
    <Table.Tr>
      <Table.Td>
        {v ? <Anchor component={Link} to={versionPath(v)} fw={500} size="sm">{f.title}</Anchor> : <Text fw={500} size="sm">{f.title}</Text>}
      </Table.Td>
      <Table.Td><Text size="xs" className="vs-mono">{f.form_id || '—'}</Text></Table.Td>
      <Table.Td>
        {v ? <Text size="sm" className="vs-num">v{v.version_no} · {fmtDate(v.created_at)}</Text>
          : <Anchor component={Link} to={`/forms/${f.id}/history`} size="sm">Conversion failed — see history</Anchor>}
      </Table.Td>
      <Table.Td>
        {v ? <Anchor component={Link} to={versionPath(v, '/report')} aria-label="Open phone-check report"><StatusBadge status={f.phone_status} /></Anchor>
          : <StatusBadge status={null} />}
      </Table.Td>
      <Table.Td ta="right">
        {f.estimated_minutes != null
          ? <Group gap={4} justify="flex-end" wrap="nowrap"><IconClock size={14} color="#5c636d" /><Text size="sm" className="vs-num">~{f.estimated_minutes} min</Text></Group>
          : <Text size="sm" c="gray.7">—</Text>}
      </Table.Td>
      <Table.Td>
        <Menu position="bottom-end" width={210}>
          <Menu.Target>
            <ActionIcon variant="default" aria-label={`Actions for ${f.title}`}><IconDots size={16} /></ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            {v && <Menu.Item component={Link} to={versionPath(v, '/report')} leftSection={<IconListCheck size={14} />}>Phone-check report</Menu.Item>}
            {v && <Menu.Item component={Link} to={`/forms/${f.id}/interviews`} leftSection={<IconPhoneCall size={14} />}>Phone interviews</Menu.Item>}
            <Menu.Item component={Link} to={`/forms/${f.id}/history`} leftSection={<IconHistory size={14} />}>Version history</Menu.Item>
            <Menu.Item component={Link} to={`/forms/${f.id}/upload`} leftSection={<IconUpload size={14} />}>Upload new version</Menu.Item>
            <Menu.Divider />
            <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={onDelete}>Delete form…</Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Table.Td>
    </Table.Tr>
  )
}

const STEPS = [
  ['Upload your form', '.xlsx or .xls, up to 10 MB. We convert it and count questions.'],
  ['Fix phone issues', "We flag questions that won't work by voice — pictures, long lists, missing Hindi."],
  ['Call respondents', 'Test on your own phone, then run a campaign and review answers.'],
]

/** Empty state: first-time explanation + upload. */
function FirstRun() {
  return (
    <Paper bg="white" p={48} maw={760} mx="auto" w="100%">
      <Title order={2} fz={20}>Run your existing survey as a phone interview</Title>
      <Text size="sm" c="gray.8" mt={6}>
        Your existing survey, run by a Gnani-powered AI enumerator. Upload the XLSForm you already use with ODK,
        KoboToolbox or SurveyCTO — nothing to rebuild.
      </Text>
      <SimpleGrid cols={3} mt="xl" spacing="md">
        {STEPS.map(([t, d], i) => (
          <Box key={t} pt="sm" style={{ borderTop: '2px solid var(--vs-ink)' }}>
            <Text size="xs" fw={600}>{i + 1}</Text>
            <Text size="sm" fw={600} mt={4}>{t}</Text>
            <Text size="xs" c="gray.7" mt={2}>{d}</Text>
          </Box>
        ))}
      </SimpleGrid>
      <Stack mt="xl"><UploadDropzone /></Stack>
    </Paper>
  )
}
