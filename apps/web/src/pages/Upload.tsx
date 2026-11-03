import { Accordion, Alert, Box, Button, Group, Loader, Paper, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core'
import { Dropzone } from '@mantine/dropzone'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  IconAlertTriangle,
  IconClock,
  IconDatabase,
  IconEdit,
  IconFileSpreadsheet,
  IconFileX,
  IconFolder,
  IconList,
  IconListCheck,
  IconMessage2,
  IconNotes,
  IconRepeat,
  IconUpload,
  IconX,
} from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'

import { api, ApiError, type Message, type UploadResult, versionPath } from '../api'
import { StatusBadge, TypeLabel } from '../components/badges'
import { ErrorNotice, PageBody, PageHeader } from '../components/layout'
import { useProjectId } from '../hooks'
import { langAttr, langLabel } from '../languages'

const MAX_MB = 10
const ACCEPT = {
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/vnd.ms-excel': ['.xls'],
}
export { langLabel }

/** Drop zone used on the upload page and the forms-list empty state. Without `onFile` it opens /upload with the file. */
export function UploadDropzone({ onFile, loading, compact }: { onFile?: (f: File) => void; loading?: boolean; compact?: boolean }) {
  const navigate = useNavigate()
  const [rejected, setRejected] = useState<string | null>(null)
  const drop = (f: File) => (onFile ? onFile(f) : navigate('/upload', { state: { file: f } }))
  return (
    <Stack gap="xs">
      <Dropzone onDrop={(files) => { setRejected(null); drop(files[0]) }}
        onReject={(r) => setRejected(r[0]?.errors[0]?.message ?? 'File rejected')}
        maxSize={MAX_MB * 1024 * 1024} accept={ACCEPT} multiple={false} loading={loading}
        styles={{ root: { border: '2px dashed #8a919a', borderRadius: 4, background: 'white', minHeight: compact ? 120 : 160 } }}>
        <Stack align="center" justify="center" gap={8} mih={compact ? 100 : 140} style={{ pointerEvents: 'none' }}>
          <Dropzone.Accept><IconUpload size={28} stroke={1.6} color="#1f4fa3" /></Dropzone.Accept>
          <Dropzone.Reject><IconX size={28} stroke={1.6} color="#c8302a" /></Dropzone.Reject>
          <Dropzone.Idle><IconFileSpreadsheet size={28} stroke={1.6} color="#424851" /></Dropzone.Idle>
          <Text size="sm"><b>Drop your XLSForm here</b> or</Text>
          <Button leftSection={<IconUpload size={16} />} style={{ pointerEvents: 'all' }}>Upload form</Button>
          <Text size="xs" c="gray.7">.xlsx or .xls · max {MAX_MB} MB · the original file is kept unchanged</Text>
        </Stack>
      </Dropzone>
      {rejected && <Alert color="red" icon={<IconX />}>{rejected}</Alert>}
    </Stack>
  )
}

export default function Upload() {
  const { formId } = useParams()
  const { state } = useLocation() as { state: { file?: File } | null }
  const projectId = useProjectId()
  const qc = useQueryClient()
  const form = useQuery({ queryKey: ['form', Number(formId)], queryFn: () => api.form(Number(formId)), enabled: !!formId })
  const [file, setFile] = useState<File | null>(null)

  const upload = useMutation({
    mutationFn: (f: File) => api.upload(projectId!, f, formId ? Number(formId) : undefined),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['forms'] }),
  })
  const convert = useMutation({
    mutationFn: (id: number) => api.convert(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['forms'] }),
  })
  const start = (f: File) => { setFile(f); convert.reset(); upload.mutate(f) }

  // A file dropped on the forms-list empty state arrives through router state.
  const handed = useRef(false)
  useEffect(() => {
    if (state?.file && projectId != null && !handed.current) {
      handed.current = true
      start(state.file)
    }
  })

  const result = convert.data ?? upload.data
  const busy = upload.isPending || convert.isPending

  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Forms', to: '/' }, ...(form.data ? [{ label: form.data.title, to: `/forms/${form.data.id}/history` }] : []), { label: 'Upload' }]}
        title={formId ? 'Upload a new version' : 'Upload form'}
        subtitle={formId ? 'The new file becomes the latest version. Earlier versions stay as they are.' : undefined} />
      <PageBody maw={1100}>
        {!result && !busy && <UploadDropzone onFile={start} />}
        {busy && (
          <Paper bg="white" p="md">
            <Group gap="sm"><Loader size="sm" /><Text size="sm">Reading <b>{file?.name}</b> and converting it with pyxform…</Text></Group>
          </Paper>
        )}
        {upload.error && <ErrorNotice title="Upload failed" message="The file couldn't be stored or read." detail={(upload.error as ApiError).message} />}
        {convert.error && <ErrorNotice title="Conversion failed" detail={(convert.error as ApiError).message} />}
        {result && !busy && (
          <>
            <FileStrip file={file} result={result} onReplace={start} />
            <UploadOutcome result={result} onExclude={() => convert.mutate(result.form.id)} />
          </>
        )}
      </PageBody>
    </>
  )
}

function FileStrip({ file, result, onReplace }: { file: File | null; result: UploadResult; onReplace: (f: File) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const ok = result.ok
  const name = file?.name ?? result.version?.original_filename ?? 'workbook'
  return (
    <Paper bg="white" p="sm" px="md" style={{ borderColor: ok ? '#a9d3b8' : '#efb2ab' }}>
      <Group justify="space-between" wrap="nowrap">
        <Group gap="sm" wrap="nowrap">
          {ok ? <IconFileSpreadsheet size={22} color="#2a8a4d" /> : <IconFileX size={22} color="#c8302a" />}
          <div>
            <Text size="sm" className="vs-mono">{name}</Text>
            <Text size="xs" c="gray.7">
              {file && `${Math.max(1, Math.round(file.size / 1024))} KB · `}
              {ok ? <>converted · saved as <b>v{result.version!.version_no}</b>{result.version!.version_no === 0 && ' (original upload)'}</> : 'not converted'}
            </Text>
          </div>
        </Group>
        <input ref={input} type="file" hidden accept=".xlsx,.xls" onChange={(e) => e.currentTarget.files?.[0] && onReplace(e.currentTarget.files[0])} />
        <Button variant={ok ? 'default' : 'filled'} onClick={() => input.current?.click()}>
          {ok ? 'Upload a different file' : 'Upload fixed file'}
        </Button>
      </Group>
    </Paper>
  )
}

function UploadOutcome({ result, onExclude }: { result: UploadResult; onExclude: () => void }) {
  if (!result.ok) {
    const platforms = [...new Set(result.platform_rows.map((r) => r.platform))].join(', ')
    return (
      <Stack>
        {result.platform_rows.length > 0 && (
          <Alert color="yellow" icon={<IconAlertTriangle />}
            title={`${result.platform_rows.length} row${result.platform_rows.length > 1 ? 's' : ''} use ${platforms}-only features`}>
            <Text size="sm">
              Standard XLSForm tools reject these question types. Mark them "not used by phone": they stay in the form and still
              work in {platforms}; the phone agent skips them.
            </Text>
            <Table mt="sm" bg="white" withTableBorder>
              <Table.Thead><Table.Tr><Table.Th w={70}>Row</Table.Th><Table.Th>Name</Table.Th><Table.Th>Type</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {result.platform_rows.map((r) => (
                  <Table.Tr key={r.row}>
                    <Table.Td className="vs-num">{r.row}</Table.Td>
                    <Table.Td className="vs-mono">{r.name}</Table.Td>
                    <Table.Td><TypeLabel>{r.type}</TypeLabel></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            <Button mt="sm" onClick={onExclude}>Mark not used by phone and continue</Button>
          </Alert>
        )}
        {result.errors.length > 0 && (
          <>
            <Alert color="red" icon={<IconFileX />} title="The form couldn't be converted">
              Fix the rows below in your spreadsheet and upload it again. The original file has been stored.
            </Alert>
            <MessagesTable messages={result.errors} />
          </>
        )}
      </Stack>
    )
  }

  const v = result.version!
  const s = v.summary
  const r = result.report
  const blockers = r?.issues.filter((i) => i.state === 'open' && i.severity === 'blocker').length ?? 0
  const tiles: [string, number | string, typeof IconMessage2][] = [
    ['Questions', s.question_count, IconMessage2], ['Notes', s.note_count, IconNotes], ['Background', s.background_count, IconDatabase],
    ['Groups', s.group_count, IconFolder], ['Repeats', s.repeat_count, IconRepeat], ['Choice lists', s.choice_list_count, IconList],
    ['Est. call', r ? `~${r.estimated_minutes} min` : '—', IconClock],
  ]
  return (
    <Paper bg="white" p="lg">
      <Group justify="space-between" mb="md">
        <Group gap="sm">
          <Title order={2}>{s.title}</Title>
          <Text size="xs" className="vs-mono" c="gray.7">{s.form_id}</Text>
          <StatusBadge status={r?.status} suffix={blockers ? ` · ${blockers} blocker${blockers > 1 ? 's' : ''}` : undefined} />
        </Group>
        <Group gap="sm">
          <Button variant="default" component={Link} to={versionPath(v, '/report')} leftSection={<IconListCheck size={16} />}>Phone-check report</Button>
          <Button component={Link} to={versionPath(v)} leftSection={<IconEdit size={16} />}>Open editor</Button>
        </Group>
      </Group>
      <SimpleGrid cols={{ base: 3, md: 7 }} spacing={0} style={{ border: '1px solid var(--vs-line)', borderRadius: 6 }}>
        {tiles.map(([label, value, I], i) => (
          <Box key={label} p="sm" style={{ borderLeft: i ? '1px solid var(--vs-line)' : undefined }}>
            <Group gap={4}><I size={13} color="#5c636d" /><Text size="xs" c="gray.7" fw={500}>{label}</Text></Group>
            <Text fz={20} fw={600} className="vs-num">{value}</Text>
          </Box>
        ))}
      </SimpleGrid>
      <Group gap="xs" mt="md">
        <Text size="xs" c="gray.7" fw={500}>Languages</Text>
        {s.languages.map((l) => <LanguageChip key={l} lang={l} isDefault={l === s.default_language} />)}
      </Group>
      {(result.warnings.length > 0 || result.platform_warnings.length > 0) && (
        <Accordion variant="contained" multiple defaultValue={['pyxform']} mt="md" chevronPosition="left">
          {result.warnings.length > 0 && (
            <Accordion.Item value="pyxform">
              <Accordion.Control><Text size="sm" fw={600} span>Converter warnings</Text> <Text span size="sm" c="gray.7">{result.warnings.length}</Text></Accordion.Control>
              <Accordion.Panel><MessagesTable messages={result.warnings} /></Accordion.Panel>
            </Accordion.Item>
          )}
          {result.platform_warnings.length > 0 && (
            <Accordion.Item value="platform">
              <Accordion.Control>
                <Text size="sm" fw={600} span>Platform warnings</Text> <Text span size="sm" c="gray.7">{result.platform_warnings.length} — features that work in ODK but behave differently on calls</Text>
              </Accordion.Control>
              <Accordion.Panel>
                <MessagesTable messages={result.platform_warnings.map((w) => ({ ...w, level: 'warning', original: '', message: `[${w.platform}] ${w.message}` }))} />
              </Accordion.Panel>
            </Accordion.Item>
          )}
        </Accordion>
      )}
    </Paper>
  )
}

export function LanguageChip({ lang, isDefault }: { lang: string; isDefault?: boolean }) {
  return (
    <Box component="span" px={6} h={22} fz={12} fw={500} lang={langAttr(lang)}
      style={{ display: 'inline-flex', alignItems: 'center', border: `1px solid ${isDefault ? '#121417' : '#c3c8ce'}`, borderRadius: 3, background: 'white' }}>
      {langLabel(lang)}{isDefault && ' · default'}
    </Box>
  )
}

/** Converter errors/warnings: sheet, row, plain message; the original pyxform text collapsed. */
export function MessagesTable({ messages }: { messages: Message[] }) {
  return (
    <Table withTableBorder bg="white">
      <Table.Thead>
        <Table.Tr>
          <Table.Th w={100}>Sheet</Table.Th>
          <Table.Th w={70} ta="right">Row</Table.Th>
          <Table.Th>Problem</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {messages.map((m, i) => (
          <Table.Tr key={i}>
            <Table.Td className="vs-mono" fz={12}>{m.sheet ?? '—'}</Table.Td>
            <Table.Td ta="right" className="vs-num">{m.row ?? '—'}</Table.Td>
            <Table.Td>
              <Text size="sm">{m.message}</Text>
              {m.original && m.original !== m.message && (
                <Box component="details" mt={2}>
                  <Text component="summary" size="xs" c="gray.7" style={{ cursor: 'pointer' }}>Technical message</Text>
                  <Text size="xs" className="vs-mono" c="gray.8" mt={2}>{m.original}</Text>
                </Box>
              )}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}
