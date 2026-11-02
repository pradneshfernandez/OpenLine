import {
  ActionIcon,
  Alert,
  Anchor,
  Box,
  Breadcrumbs,
  Button,
  Checkbox,
  Collapse,
  Drawer,
  Group,
  MultiSelect,
  Paper,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  IconAlertTriangle,
  IconArrowsMaximize,
  IconArrowsMinimize,
  IconChevronDown,
  IconChevronRight,
  IconClock,
  IconCornerDownRight,
  IconDeviceFloppy,
  IconEye,
  IconHistory,
  IconLayoutSidebarRight,
  IconLink,
  IconListCheck,
  IconSearch,
} from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import {
  api,
  ApiError,
  type Change,
  type Choice,
  type Issue,
  type Message,
  type Question,
  type Severity,
  type VersionDetail,
  versionPath,
} from '../api'
import {
  IssueCounts,
  KindIcon,
  SEVERITIES,
  SEVERITY_LABEL,
  SEVERITY_RANK,
  SeverityIcon,
  SeverityLegend,
  StatusBadge,
  TypeLabel,
} from '../components/badges'
import IssueCard from '../components/IssueCard'
import ListenButton from '../components/Listen'
import { ErrorNotice } from '../components/layout'
import { useRouteVersion } from '../hooks'
import { LanguageChip, langLabel, MessagesTable } from './Upload'

type Pending = Record<string, { change: Change; original: string | boolean }>
type ValueOf = (c: Omit<Change, 'value'>, original: string | boolean) => string | boolean
type SetChange = (c: Change, original: string | boolean) => void

function changeKey(c: Omit<Change, 'value'>) {
  const subject = c.target === 'choice' ? `${c.list_name}/${c.choice_name}` : c.question_name
  return [c.target, subject, c.field, c.lang ?? ''].join('|')
}

const isContainer = (q: Question) => q.kind === 'group' || q.kind === 'repeat'
const openIssues = (issues: Issue[]) => issues.filter((i) => i.state === 'open')
const worstOf = (issues: Issue[]) =>
  issues.reduce<Severity | null>((w, i) => (!w || SEVERITY_RANK[i.severity] > SEVERITY_RANK[w] ? i.severity : w), null)
const countBySeverity = (issues: Issue[]) =>
  Object.fromEntries(SEVERITIES.map((s) => [s, issues.filter((i) => i.severity === s).length])) as Record<Severity, number>
const isHindi = (l: string) => /hindi|^hi\b/i.test(l)
const firstLabel = (q: Question, lang: string) => stripHtml(q.labels[lang] ?? Object.values(q.labels).find(Boolean) ?? '')

const TREE_W = 400
const SUMMARY_W = 300

export default function Inspector() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const wide = useMediaQuery('(min-width: 1280px)', true)
  const [summaryOpen, setSummaryOpen] = useState(false)

  const version = useRouteVersion()
  const v = version.data
  const form = useQuery({ queryKey: ['form', v?.form.id], queryFn: () => api.form(v!.form.id), enabled: !!v })

  const [lang, setLang] = useState<string | null>(null)
  const [groupFilter, setGroupFilter] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState<string[]>([])
  const [onlyIssues, setOnlyIssues] = useState(false)
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const [pending, setPending] = useState<Pending>({})
  const [message, setMessage] = useState('')
  const [saveErrors, setSaveErrors] = useState<Message[] | null>(null)
  const pendingCount = Object.keys(pending).length

  useEffect(() => {
    if (!pendingCount) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [pendingCount])

  const save = useMutation({
    mutationFn: () => api.saveEdits(v!.id, message, Object.values(pending).map((p) => p.change)),
    onSuccess: (res) => {
      notifications.show({ color: 'green', title: `Saved as v${res.version.version_no}`, message: 'Converted with pyxform; phone check re-run.' })
      setPending({})
      setMessage('')
      setSaveErrors(null)
      qc.invalidateQueries({ queryKey: ['forms'] })
      qc.invalidateQueries({ queryKey: ['form'] })
      navigate(`${versionPath(res.version)}?${params.toString()}`)
    },
    onError: (e: ApiError) => {
      setSaveErrors(e.errors.length ? e.errors : [{ level: 'error', sheet: null, row: null, message: e.message, original: '' }])
    },
  })

  const languages = useMemo(() => (v?.languages.length ? v.languages : ['default']), [v])
  const defaultLang = v?.form.default_language && languages.includes(v.form.default_language) ? v.form.default_language : languages[0]
  const activeLang = lang && languages.includes(lang) ? lang : defaultLang

  const issuesByQuestion = useMemo(() => {
    const map: Record<string, Issue[]> = {}
    for (const i of v?.report?.issues ?? []) if (i.question_name) (map[i.question_name] ??= []).push(i)
    return map
  }, [v])
  const byRow = useMemo(() => new Map((v?.questions ?? []).map((q) => [q.row, q])), [v])
  const groups = useMemo(() => (v?.questions ?? []).filter(isContainer), [v])
  const types = useMemo(() => [...new Set((v?.questions ?? []).map((q) => q.type))].sort(), [v])
  const filtering = !!(search.trim() || groupFilter || typeFilter.length || onlyIssues)

  const visible = useMemo(() => {
    const s = search.trim().toLowerCase()
    return (v?.questions ?? []).filter((q) => {
      if (!filtering && q.group_path.some((g) => collapsed.has(g.row))) return false
      if (groupFilter && q.name !== groupFilter && !q.group_path.some((g) => g.name === groupFilter)) return false
      if (typeFilter.length && !typeFilter.includes(q.type)) return false
      if (onlyIssues && !openIssues(issuesByQuestion[q.name] ?? []).length) return false
      if (s && !q.name.toLowerCase().includes(s) && !Object.values(q.labels).some((l) => l.toLowerCase().includes(s))) return false
      return true
    })
  }, [v, search, groupFilter, typeFilter, onlyIssues, issuesByQuestion, collapsed, filtering])

  const selectedQ = params.get('q')
  useEffect(() => {
    document.querySelector('.vs-tree-row[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [selectedQ, v?.id])

  if (version.isLoading) return <EditorSkeleton />
  if (!v) return <Box p="xl"><ErrorNotice title="Version not found" message="It may have been deleted, or the link is wrong." detail={(version.error as Error | null)?.message} /></Box>

  const selectedName = params.get('q') ?? v.questions[0]?.name
  const selected = v.questions.find((q) => q.name === selectedName) ?? v.questions[0]
  const editable = v.is_latest
  const latest = form.data?.versions.find((x) => x.id === form.data?.latest_version_id)
  const select = (name: string) => setParams((p) => { p.set('q', name); return p }, { replace: true })
  const toggle = (row: number) => setCollapsed((c) => {
    const next = new Set(c)
    if (next.has(row)) next.delete(row)
    else next.add(row)
    return next
  })

  const setChange: SetChange = (change, original) => {
    const key = changeKey(change)
    setPending((p) => {
      const next = { ...p }
      if (change.value === original) delete next[key]
      else next[key] = { change, original }
      return next
    })
  }
  const valueOf: ValueOf = (change, original) => {
    const p = pending[changeKey(change)]
    return p ? p.change.value : original
  }
  const changedIn = [...new Set(Object.values(pending).map((p) => p.change.question_name ?? p.change.list_name ?? ''))]
  const openAll = openIssues(v.report?.issues ?? [])

  const summary = <FormSummary v={v} languages={languages} defaultLang={defaultLang} onSelect={(n) => { select(n); setSummaryOpen(false) }} />

  return (
    <Box h="100vh" style={{ display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <Box bg="white" px="lg" py={10} style={{ borderBottom: '1px solid var(--vs-line)', flexShrink: 0 }}>
        <Breadcrumbs separator="›" separatorMargin={6}>
          <Anchor component={Link} to="/" size="xs" underline="always">Forms</Anchor>
          <Text size="xs" c="gray.7">{v.form.title}</Text>
          <Text size="xs" c="gray.7" className="vs-mono">{v.form.form_id}</Text>
        </Breadcrumbs>
        <Group justify="space-between" wrap="nowrap" mt={2} gap="md">
          <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
            <Title order={1} fz={20} lineClamp={1}>{v.form.title}</Title>
            <Box px={6} h={22} fz={12} fw={600} className="vs-mono" style={{ border: '1.5px solid #121417', borderRadius: 3, display: 'flex', alignItems: 'center' }}>v{v.version_no}</Box>
            <Text size="xs" c="gray.7">{editable ? 'latest' : 'older version'}</Text>
            <Tooltip label="Open the phone-check report">
              <Anchor component={Link} to={versionPath(v, '/report')} underline="never">
                <Group gap={4} wrap="nowrap"><StatusBadge status={v.report?.status} /><IssueCounts counts={countBySeverity(openAll)} /></Group>
              </Anchor>
            </Tooltip>
            {v.report && <Group gap={4} wrap="nowrap"><IconClock size={14} color="#5c636d" /><Text size="sm" c="gray.8" className="vs-num" style={{ whiteSpace: 'nowrap' }}>~{v.report.estimated_minutes} min call</Text></Group>}
            {pendingCount > 0 && <Text size="sm" fw={600} c="brand.6" style={{ whiteSpace: 'nowrap' }}>● {pendingCount} unsaved change{pendingCount > 1 ? 's' : ''}</Text>}
          </Group>
          <Group gap="sm" wrap="nowrap">
            {languages.length > 1 && (
              <Group gap={6} wrap="nowrap">
                <Text size="xs" c="gray.7">Tree language</Text>
                <SegmentedControl value={activeLang} onChange={setLang} aria-label="Tree language"
                  data={languages.map((l) => ({ value: l, label: <span lang={isHindi(l) ? 'hi' : undefined}>{isHindi(l) ? 'हिन्दी' : langLabel(l)}</span> }))} />
              </Group>
            )}
            {!wide && <Button variant="default" leftSection={<IconLayoutSidebarRight size={16} />} onClick={() => setSummaryOpen(true)}>Summary</Button>}
            <Button variant="default" component={Link} to={versionPath(v, '/report')} leftSection={<IconListCheck size={16} />}>Report</Button>
            <Button variant="default" component={Link} to={`/forms/${v.form.id}/history`} leftSection={<IconHistory size={16} />}>History</Button>
            {editable && (
              <Button leftSection={<IconDeviceFloppy size={16} />} disabled={!pendingCount} loading={save.isPending} onClick={() => save.mutate()}>
                Save as new version (v{v.version_no + 1})
              </Button>
            )}
          </Group>
        </Group>
      </Box>

      {!editable && latest && (
        <Box px="lg" py={8} bg="#eaf0fa" style={{ borderBottom: '1px solid #b9cbea', flexShrink: 0 }}>
          <Group gap={6}>
            <IconEye size={16} color="#1f4fa3" />
            <Text size="sm">
              You're viewing <b>v{v.version_no}</b>, read-only. Saved versions never change;{' '}
              <Anchor component={Link} to={versionPath(latest)} fw={600}>open the latest (v{latest.version_no})</Anchor> to edit.
            </Text>
          </Group>
        </Box>
      )}

      {/* Three panels, each scrolling on its own */}
      <Box style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        <Box w={TREE_W} bg="white" style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--vs-line)' }}>
          <Stack gap={8} p="sm" style={{ borderBottom: '1px solid var(--vs-line)' }}>
            <TextInput placeholder="Search name or text" leftSection={<IconSearch size={14} />} value={search}
              onChange={(e) => setSearch(e.currentTarget.value)} aria-label="Search questions" />
            <Group gap={8} grow wrap="nowrap">
              <Select size="xs" placeholder="All groups" clearable searchable value={groupFilter} onChange={setGroupFilter} aria-label="Filter by group"
                data={groups.map((g) => ({ value: g.name, label: `${g.kind === 'repeat' ? '↻ ' : ''}${g.name}` }))} />
              <MultiSelect size="xs" placeholder={typeFilter.length ? undefined : 'All types'} clearable searchable value={typeFilter}
                onChange={setTypeFilter} data={types} aria-label="Filter by type" />
            </Group>
            <Group justify="space-between" wrap="nowrap">
              <Checkbox size="xs" label="Only questions with phone issues" checked={onlyIssues} onChange={(e) => setOnlyIssues(e.currentTarget.checked)} />
              <Group gap={6} wrap="nowrap">
                <Text size="xs" c="gray.7" className="vs-num">{visible.length} of {v.questions.length} rows</Text>
                <Tooltip label="Collapse all groups">
                  <ActionIcon variant="default" size="sm" disabled={filtering || !groups.length} onClick={() => setCollapsed(new Set(groups.map((g) => g.row)))} aria-label="Collapse all">
                    <IconArrowsMinimize size={13} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Expand all groups">
                  <ActionIcon variant="default" size="sm" disabled={filtering || !groups.length} onClick={() => setCollapsed(new Set())} aria-label="Expand all">
                    <IconArrowsMaximize size={13} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            </Group>
          </Stack>
          <ScrollArea style={{ flex: 1 }} type="auto">
            {visible.map((q) => (
              <TreeItem key={q.position} q={q} lang={activeLang} active={q.name === selected?.name}
                issues={isContainer(q) ? [] : issuesByQuestion[q.name] ?? []}
                collapsed={isContainer(q) ? collapsed.has(q.row) : undefined}
                onToggle={() => toggle(q.row)} onClick={() => select(q.name)} />
            ))}
            {!visible.length && <Text size="sm" c="gray.7" ta="center" p="lg">No rows match these filters.</Text>}
          </ScrollArea>
          <Box px="sm" py={8} style={{ borderTop: '1px solid var(--vs-line)' }}><SeverityLegend /></Box>
        </Box>

        <ScrollArea style={{ flex: 1, minWidth: 0 }} type="auto">
          <Box p="lg" maw={880}>
            {!selected && <Text c="gray.7">This form has no questions.</Text>}
            {selected && isContainer(selected) && (
              <GroupSummary key={selected.position} g={selected} v={v} lang={activeLang} languages={languages} defaultLang={defaultLang}
                issuesByQuestion={issuesByQuestion} byRow={byRow} editable={editable} valueOf={valueOf} setChange={setChange} onSelect={select} />
            )}
            {selected && !isContainer(selected) && (
              <QuestionDetail key={selected.position} q={selected} v={v} languages={languages} defaultLang={defaultLang}
                issues={issuesByQuestion[selected.name] ?? []} byRow={byRow}
                choices={selected.choice_list ? v.choice_lists[selected.choice_list] ?? [] : []}
                editable={editable} valueOf={valueOf} setChange={setChange} onSelect={select} />
            )}
          </Box>
        </ScrollArea>

        {wide && (
          <Box w={SUMMARY_W} bg="white" style={{ flexShrink: 0, borderLeft: '1px solid var(--vs-line)' }}>
            <ScrollArea h="100%" type="auto">{summary}</ScrollArea>
          </Box>
        )}
      </Box>
      <Drawer opened={!wide && summaryOpen} onClose={() => setSummaryOpen(false)} position="right" size={SUMMARY_W + 40} title={<Text fw={600}>Form summary</Text>}>
        {summary}
      </Drawer>

      {/* Save bar */}
      {pendingCount > 0 && (
        <Box style={{ flexShrink: 0 }}>
          {saveErrors && (
            <Paper radius={0} p="md" bg="white" shadow="md" style={{ borderTop: '2px solid #c8302a', maxHeight: '40vh', overflow: 'auto' }}>
              <Group justify="space-between" mb="xs">
                <Text fw={600} c="red.6">Not saved — the converter rejected the edited form</Text>
                <Button size="xs" variant="subtle" color="gray" onClick={() => setSaveErrors(null)}>Hide</Button>
              </Group>
              <MessagesTable messages={saveErrors} />
            </Paper>
          )}
          <Group h={56} px="lg" bg="#121417" c="white" wrap="nowrap" gap="md">
            <Text fw={600} size="sm" style={{ whiteSpace: 'nowrap' }}>● {pendingCount} unsaved change{pendingCount > 1 ? 's' : ''}</Text>
            <Text size="xs" c="#9aa1a9" lineClamp={1} maw={260}>in <span className="vs-mono">{changedIn.join(', ')}</span></Text>
            <TextInput style={{ flex: 1 }} placeholder="What changed? (optional, shown in history)" value={message} aria-label="Change message"
              onChange={(e) => setMessage(e.currentTarget.value)}
              styles={{ input: { background: '#23282e', borderColor: '#3a4048', color: 'white' } }} />
            <Button variant="default" onClick={() => { setPending({}); setSaveErrors(null) }}>Discard</Button>
            <Button color="#ffcc00" c="#121417" leftSection={<IconDeviceFloppy size={16} />} loading={save.isPending} onClick={() => save.mutate()}>
              Save as new version (v{v.version_no + 1})
            </Button>
          </Group>
        </Box>
      )}
    </Box>
  )
}

function EditorSkeleton() {
  return (
    <Box h="100vh" style={{ display: 'flex', flexDirection: 'column' }}>
      <Box bg="white" p="lg" style={{ borderBottom: '1px solid var(--vs-line)' }}><Skeleton h={28} w={420} /></Box>
      <Box style={{ flex: 1, display: 'flex' }}>
        <Stack w={TREE_W} p="sm" gap={8} bg="white">{Array.from({ length: 12 }, (_, i) => <Skeleton key={i} h={34} />)}</Stack>
        <Stack p="lg" style={{ flex: 1 }}><Skeleton h={32} w={300} /><Skeleton h={120} /><Skeleton h={160} /></Stack>
      </Box>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Tree

function TreeItem({ q, lang, active, issues, collapsed, onToggle, onClick }: {
  q: Question; lang: string; active: boolean; issues: Issue[]; collapsed?: boolean; onToggle: () => void; onClick: () => void
}) {
  const open = openIssues(issues)
  const worst = worstOf(open)
  const label = firstLabel(q, lang)
  const container = isContainer(q)
  return (
    // A div with button semantics: the row holds its own collapse button, and buttons can't nest.
    <UnstyledButton component="div" role="button" tabIndex={0} className="vs-tree-row" data-active={active} onClick={onClick}
      onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onClick() } }}
      aria-current={active || undefined} style={{ paddingLeft: 4 + q.group_path.length * 16 }}>
      <Box w={22} style={{ flexShrink: 0, display: 'flex', justifyContent: 'flex-end' }}>
        {container ? (
          <ActionIcon size="xs" variant="subtle" color="gray" aria-label={collapsed ? `Expand ${q.name}` : `Collapse ${q.name}`}
            onClick={(e) => { e.stopPropagation(); onToggle() }}>
            {collapsed ? <IconChevronRight size={13} /> : <IconChevronDown size={13} />}
          </ActionIcon>
        ) : <Text size="xs" c="gray.7" mt={1} className="vs-num">{q.number ?? ''}</Text>}
      </Box>
      <Box mt={1}><KindIcon kind={q.kind} size={15} /></Box>
      <Box style={{ flex: 1, minWidth: 0 }}>
        <Group gap={6} wrap="nowrap">
          <Text size="sm" className={`vs-mono${q.not_used_by_phone ? ' vs-strike' : ''}`} fw={600} truncate c={q.not_used_by_phone ? 'gray.7' : undefined}>
            {q.name || `(row ${q.row})`}
          </Text>
          <TypeLabel>{q.raw_type.split(/\s+/)[0]}</TypeLabel>
          {q.not_used_by_phone && <Box component="span" className="vs-type" style={{ fontFamily: 'inherit' }}>not used by phone</Box>}
        </Group>
        {label && <Text size="sm" c={q.not_used_by_phone ? 'gray.7' : 'gray.8'} lineClamp={2} lang={isHindi(lang) ? 'hi' : undefined} lh={isHindi(lang) ? 1.6 : 1.4}>{label}</Text>}
      </Box>
      {worst && (
        <Tooltip label={<Stack gap={2}>{open.map((i) => <Text key={i.id} size="xs">{SEVERITY_LABEL[i.severity]}: {i.check_title}</Text>)}</Stack>}>
          <Box mt={2}><SeverityIcon severity={worst} /></Box>
        </Tooltip>
      )}
    </UnstyledButton>
  )
}

/** What the agent would say: no markup, and ${var} references read as their name. */
function spokenPreview(s: string) {
  return stripHtml(s).replace(/\$\{([^}]+)\}/g, (_, n: string) => n.replace(/_/g, ' '))
}

function stripHtml(s: string) {
  return s.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
}

// ---------------------------------------------------------------------------
// Shared editor pieces

function Section({ title, meta, children, actions }: { title: React.ReactNode; meta?: React.ReactNode; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <Paper bg="white" p="md">
      <Group justify="space-between" mb="sm" wrap="nowrap">
        <Group gap={8} wrap="nowrap" align="baseline">
          <Title order={3}>{title}</Title>
          {meta && <Text size="xs" c="gray.7">{meta}</Text>}
        </Group>
        {actions}
      </Group>
      {children}
    </Paper>
  )
}

type TextField = 'label' | 'hint' | 'constraint_message'

/** One editable box per language, side by side; a missing language is highlighted. */
function PerLanguageText({ q, field, texts, languages, defaultLang, editable, valueOf, setChange, minRows = 2, placeholder }: {
  q: Question; field: TextField; texts: Record<string, string>; languages: string[]; defaultLang: string
  editable: boolean; valueOf: ValueOf; setChange: SetChange; minRows?: number; placeholder?: string
}) {
  const anyText = languages.some((l) => texts[l])
  return (
    <SimpleGrid cols={Math.min(languages.length, 2)} spacing="sm">
      {languages.map((l) => {
        const base = { target: 'question' as const, question_name: q.name, field, lang: l }
        const original = texts[l] ?? ''
        const value = valueOf(base, original) as string
        const missing = anyText && !value
        const hi = isHindi(l)
        return (
          <Box key={l} style={{ border: `1px solid ${missing ? '#c8302a' : '#8a919a'}`, borderRadius: 4, overflow: 'hidden', background: 'white' }}>
            <Group justify="space-between" px={8} h={28} bg={missing ? '#fbe9e7' : '#f8f9fa'}
              style={{ borderBottom: `1px solid ${missing ? '#efb2ab' : 'var(--vs-line)'}` }}>
              <Group gap={4}>
                {missing && <SeverityIcon severity="blocker" size={13} />}
                <Text size="xs" fw={600} c={missing ? 'red.6' : 'gray.8'}>
                  {langLabel(l)}{l === defaultLang && languages.length > 1 ? ' · default' : ''}{missing ? ' · missing' : ''}
                </Text>
              </Group>
              {field !== 'constraint_message' && <ListenButton text={spokenPreview(value)} lang={hi ? 'hi' : 'en'} />}
            </Group>
            <Textarea variant="unstyled" px={10} minRows={minRows} readOnly={!editable} lang={hi ? 'hi' : undefined}
              aria-label={`${field.replace('_', ' ')} in ${langLabel(l)}`}
              placeholder={editable ? (placeholder ?? (hi ? 'हिन्दी में लिखें…' : `Add text in ${langLabel(l)}`)) : '—'}
              value={value} onChange={(e) => setChange({ ...base, value: e.currentTarget.value }, original)}
              styles={{ input: { lineHeight: hi ? 1.7 : 1.5, fontSize: 14, border: 0, padding: '8px 0', minHeight: 0 } }} />
          </Box>
        )
      })}
    </SimpleGrid>
  )
}

function Flag({ q, field, label, description, editable, valueOf, setChange }: {
  q: Question; field: 'required' | 'read_aloud' | 'hint_read_aloud' | 'not_used_by_phone'; label: string; description?: string
  editable: boolean; valueOf: ValueOf; setChange: SetChange
}) {
  const base = { target: 'question' as const, question_name: q.name, field }
  return (
    <Switch label={<Text size="sm" fw={500}>{label}</Text>} description={description} checked={valueOf(base, q[field]) as boolean} disabled={!editable}
      onChange={(e) => setChange({ ...base, value: e.currentTarget.checked }, q[field])} styles={{ description: { color: '#5c636d' } }} />
  )
}

function RawExpression({ q, field, label, valueOf, setChange }: { q: Question; field: 'relevant' | 'constraint'; label: string; valueOf: ValueOf; setChange: SetChange }) {
  const base = { target: 'question' as const, question_name: q.name, field }
  const original = q[field] ?? ''
  return (
    <Textarea label={label} minRows={1} styles={{ input: { fontFamily: "'IBM Plex Mono', monospace", fontSize: 13 } }}
      value={valueOf(base, original) as string} onChange={(e) => setChange({ ...base, value: e.currentTarget.value }, original)} />
  )
}

/** Own skip logic plus every enclosing group's (dashed, linked). All must hold for the row to be asked. */
function SkipLogic({ q, byRow, onSelect }: { q: Question; byRow: Map<number, Question>; onSelect: (n: string) => void }) {
  const inherited = q.group_path.map((g) => byRow.get(g.row)).filter((g): g is Question => !!g?.relevant)
  if (!q.relevant && !inherited.length) return <Text size="sm" c="gray.7">Always asked — no skip logic here or on any parent group.</Text>
  const all = [...(q.relevant ? [q] : []), ...inherited]
  return (
    <Stack gap="sm">
      {q.relevant && (
        <Box style={{ border: '1px solid var(--vs-line)', borderRadius: 4, overflow: 'hidden' }}>
          <Box px="sm" py={8}>
            <Text size="xs" c="gray.7" fw={500}>This {isContainer(q) ? q.kind : 'question'}</Text>
            <Text size="sm" fw={500}>{q.relevant_plain || 'Has a condition'}</Text>
          </Box>
          <code className="vs-expr">{q.relevant}</code>
        </Box>
      )}
      {inherited.map((g) => (
        <Box key={g.row} style={{ border: '1px dashed #8a919a', borderRadius: 4, overflow: 'hidden' }}>
          <Box px="sm" py={8}>
            <Group gap={4}>
              <IconCornerDownRight size={13} color="#5c636d" />
              <Text size="xs" c="gray.7" fw={500}>Inherited from {g.kind}</Text>
              <Anchor size="xs" className="vs-mono" component="button" onClick={() => onSelect(g.name)}>{g.name}</Anchor>
            </Group>
            <Text size="sm" fw={500}>{g.relevant_plain || 'Has a condition'}</Text>
          </Box>
          <code className="vs-expr">{g.relevant}</code>
        </Box>
      ))}
      {all.length > 1 && (
        <Text size="xs" c="gray.7">Asked when all of these are true: {all.map((x) => x.relevant_plain || x.relevant).join('; and ')}.</Text>
      )}
    </Stack>
  )
}

function IssuesSection({ issues, readOnly }: { issues: Issue[]; readOnly: boolean }) {
  if (!issues.length) return null
  const open = openIssues(issues).length
  return (
    <Stack gap="xs">
      <Group gap={8} align="baseline">
        <Title order={3}>Phone issues</Title>
        <Text size="xs" c="gray.7">{open} open of {issues.length}</Text>
      </Group>
      {[...issues]
        .sort((a, b) => Number(b.state === 'open') - Number(a.state === 'open') || SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity])
        .map((i) => <IssueCard key={i.id} issue={i} readOnly={readOnly} />)}
    </Stack>
  )
}

function Heading({ q, onSelect }: { q: Question; onSelect: (n: string) => void }) {
  return (
    <div>
      <Breadcrumbs separator="›" separatorMargin={6} mb={6}>
        <Text size="xs" c="gray.7">Form</Text>
        {q.group_path.map((g) => (
          <Anchor key={g.row} size="xs" className="vs-mono" component="button" onClick={() => onSelect(g.name)} underline="always">
            {g.type === 'repeat' ? '↻ ' : ''}{g.name}
          </Anchor>
        ))}
      </Breadcrumbs>
      <Group gap="sm" wrap="nowrap">
        {q.number != null && (
          <Box px={6} h={22} bg="#121417" c="white" fz={12} fw={600} style={{ borderRadius: 3, display: 'flex', alignItems: 'center' }}>Q{q.number}</Box>
        )}
        <KindIcon kind={q.kind} size={18} />
        <Text fz={20} fw={600} className="vs-mono" lh="28px" truncate>{q.name || `(row ${q.row})`}</Text>
        <TypeLabel>{q.raw_type}</TypeLabel>
        <Text size="xs" c="gray.7" style={{ whiteSpace: 'nowrap' }}>{q.kind === 'background' ? 'Background field' : q.kind[0].toUpperCase() + q.kind.slice(1)} · Row {q.row} in survey sheet</Text>
      </Group>
    </div>
  )
}

function Advanced({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <Paper bg="white">
      <UnstyledButton w="100%" px="md" py="sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Group gap={8}>
          {open ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
          <Text fw={600} size="md">Advanced</Text>
          <Text size="xs" c="gray.7">Raw expressions and other spreadsheet columns</Text>
        </Group>
      </UnstyledButton>
      <Collapse expanded={open}><Stack gap="sm" px="md" pb="md">{children}</Stack></Collapse>
    </Paper>
  )
}

// ---------------------------------------------------------------------------
// Question

interface DetailProps {
  q: Question
  v: VersionDetail
  languages: string[]
  defaultLang: string
  issues: Issue[]
  byRow: Map<number, Question>
  choices: Choice[]
  editable: boolean
  valueOf: ValueOf
  setChange: SetChange
  onSelect: (n: string) => void
}

function QuestionDetail({ q, v, languages, defaultLang, issues, byRow, choices, editable, valueOf, setChange, onSelect }: DetailProps) {
  const isSpoken = q.kind !== 'background'
  const isAsked = q.kind !== 'background' && q.kind !== 'note'
  const edit = { languages, defaultLang, editable, valueOf, setChange }
  const flag = { q, editable, valueOf, setChange }
  const sharedBy = q.choice_list ? v.questions.filter((x) => x.choice_list === q.choice_list).length : 0
  const requiredExpr = q.required_raw && !['yes', 'true', 'true()', '1', ''].includes(q.required_raw.toLowerCase())

  return (
    <Stack gap="md">
      <Heading q={q} onSelect={onSelect} />
      {v.excluded_rows?.includes(q.name) && (
        <Alert color="gray" icon={<IconAlertTriangle />}>This row uses a platform-specific type and was marked "not used by phone" at upload. It stays unchanged in the spreadsheet.</Alert>
      )}
      <IssuesSection issues={issues} readOnly={!editable} />

      {isSpoken && (
        <Paper bg="white" p="md">
          <Title order={3} mb="sm">{q.kind === 'note' ? 'Note text' : 'Question text'}</Title>
          <PerLanguageText q={q} field="label" texts={q.labels} {...edit} />
          <Group gap={8} mt="md" mb="sm" align="baseline">
            <Title order={3}>Hint</Title>
            <Text size="xs" c="gray.7">Shown to the agent; read aloud only if switched on below</Text>
          </Group>
          <PerLanguageText q={q} field="hint" texts={q.hints} minRows={1} {...edit} />
        </Paper>
      )}

      <Section title="Phone agent">
        {isSpoken ? (
          <SimpleGrid cols={3} spacing="md">
            <Flag {...flag} field="read_aloud" label="Read question aloud" description="Off = the agent paraphrases from the text" />
            <Flag {...flag} field="hint_read_aloud" label="Read hint aloud" description="Off = hint guides the agent only" />
            <Flag {...flag} field="not_used_by_phone" label="Not used by phone" description="Skipped on calls; stays in the form" />
          </SimpleGrid>
        ) : (
          <Flag {...flag} field="not_used_by_phone" label="Not used by phone" description="Background fields are recorded automatically, never spoken." />
        )}
      </Section>

      {q.choice_list && (
        <Section title="Answer options" meta={<><span className="vs-mono">{q.choice_list}</span> · {choices.length} options</>}>
          {sharedBy > 1 && (
            <Group gap={6} px="sm" py={6} mb="sm" bg="#f8f9fa" style={{ border: '1px solid var(--vs-line)', borderRadius: 4 }} wrap="nowrap">
              <IconLink size={14} color="#5c636d" />
              <Text size="xs" c="gray.8">Labels are shared by every question using this list (<b>{sharedBy} questions</b>). Changes apply to all of them.</Text>
            </Group>
          )}
          <Table withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={110}>Code</Table.Th>
                {languages.map((l) => <Table.Th key={l}>{langLabel(l)}</Table.Th>)}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {choices.map((c) => (
                <Table.Tr key={c.row}>
                  <Table.Td>
                    <Text size="sm" className="vs-mono">{c.name}</Text>
                    {Object.keys(c.media ?? {}).length > 0 && <Text size="xs" c="gray.7">{Object.keys(c.media).join(', ')}</Text>}
                  </Table.Td>
                  {languages.map((l) => {
                    const base = { target: 'choice' as const, list_name: q.choice_list!, choice_name: c.name, field: 'label', lang: l }
                    const original = c.labels[l] ?? ''
                    return (
                      <Table.Td key={l}>
                        <TextInput size="xs" variant={editable ? 'default' : 'unstyled'} readOnly={!editable} lang={isHindi(l) ? 'hi' : undefined}
                          aria-label={`${c.name} label in ${langLabel(l)}`} value={valueOf(base, original) as string}
                          error={!original && Object.values(c.labels).some(Boolean) ? true : undefined}
                          onChange={(e) => setChange({ ...base, value: e.currentTarget.value }, original)} />
                      </Table.Td>
                    )
                  })}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Section>
      )}

      {isAsked && (
        <Section title="Validation">
          <Stack gap="sm">
            <Flag {...flag} field="required" label="Required — the agent won't move on without an answer (or dk / refused)" />
            {requiredExpr && <Text size="xs" c="gray.7">Required is an expression: <span className="vs-mono">{q.required_raw}</span></Text>}
            {q.constraint ? (
              <Box style={{ border: '1px solid var(--vs-line)', borderRadius: 4, overflow: 'hidden' }}>
                <Text size="xs" c="gray.7" fw={500} px="sm" pt={8}>Constraint</Text>
                <Text size="sm" px="sm" pb={8}>The answer must satisfy this expression.</Text>
                <code className="vs-expr">{q.constraint}</code>
              </Box>
            ) : (
              <Text size="sm" c="gray.7">No constraint. Any answer of type <span className="vs-mono">{q.type}</span> is accepted.</Text>
            )}
            {(q.constraint || Object.values(q.constraint_message).some(Boolean)) && (
              <>
                <Text size="sm" fw={600}>Constraint message</Text>
                <PerLanguageText q={q} field="constraint_message" texts={q.constraint_message} minRows={1} {...edit} />
              </>
            )}
          </Stack>
        </Section>
      )}

      <Section title="Skip logic"><SkipLogic q={q} byRow={byRow} onSelect={onSelect} /></Section>

      <Advanced>
        {editable && (
          <>
            <RawExpression q={q} field="relevant" label="relevant (skip logic)" valueOf={valueOf} setChange={setChange} />
            {isAsked && <RawExpression q={q} field="constraint" label="constraint" valueOf={valueOf} setChange={setChange} />}
            <Text size="xs" c="gray.7">Expressions are checked by the converter when you save; an invalid expression blocks the save.</Text>
          </>
        )}
        <OtherColumns q={q} />
      </Advanced>
    </Stack>
  )
}

function OtherColumns({ q }: { q: Question }) {
  const rows = ([
    ['appearance', q.appearance],
    ['default', q.default],
    ['calculation', q.calculation],
    ['repeat_count', q.repeat_count],
    ...Object.entries(q.media).map(([kind, files]) => [`media::${kind}`, Object.entries(files).map(([l, f]) => (l ? `${l}: ${f}` : f)).join(', ')]),
    ...Object.entries(q.extra).map(([k, val]) => [k, val]),
  ] as [string, string][]).filter(([, val]) => val)
  if (!rows.length) return <Text size="sm" c="gray.7">No other spreadsheet columns on this row.</Text>
  return (
    <Box>
      <Text size="sm" fw={600} mb={4}>Other columns</Text>
      <Table withTableBorder>
        <Table.Tbody>
          {rows.map(([k, val]) => (
            <Table.Tr key={k}>
              <Table.Td w={170}><Text size="xs" className="vs-mono" c="gray.8">{k}</Text></Table.Td>
              <Table.Td><Text size="sm" className="vs-mono" style={{ wordBreak: 'break-word' }}>{val}</Text></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Group / repeat

function GroupSummary({ g, v, lang, languages, defaultLang, issuesByQuestion, byRow, editable, valueOf, setChange, onSelect }: {
  g: Question; v: VersionDetail; lang: string; languages: string[]; defaultLang: string; issuesByQuestion: Record<string, Issue[]>
  byRow: Map<number, Question>; editable: boolean; valueOf: ValueOf; setChange: SetChange; onSelect: (name: string) => void
}) {
  const inside = v.questions.filter((q) => q.group_path.some((p) => p.row === g.row))
  const direct = inside.filter((q) => q.group_path[q.group_path.length - 1]?.row === g.row)
  const asked = inside.filter((q) => !isContainer(q) && q.kind !== 'background')
  const open = openIssues(inside.flatMap((q) => issuesByQuestion[q.name] ?? []))
  const withSkip = inside.filter((q) => q.relevant)
  const counts = countBySeverity(open)

  return (
    <Stack gap="md">
      <Heading q={g} onSelect={onSelect} />
      <SimpleGrid cols={3} spacing="sm">
        <Paper bg="white" p="md"><Text size="xs" c="gray.7" fw={500}>Questions inside</Text><Text fz={24} fw={600} className="vs-num">{asked.length}</Text></Paper>
        <Paper bg="white" p="md"><Text size="xs" c="gray.7" fw={500}>With their own skip logic</Text><Text fz={24} fw={600} className="vs-num">{withSkip.length}</Text></Paper>
        <Paper bg="white" p="md">
          <Text size="xs" c="gray.7" fw={500}>Open issues</Text>
          <Box mt={6}>{open.length ? <IssueCounts counts={counts} /> : <Text fz={24} fw={600}>0</Text>}</Box>
        </Paper>
      </SimpleGrid>

      {g.kind === 'repeat' && (
        g.repeat_count ? (
          <Alert color="gray" icon={<KindIcon kind="repeat" />}>
            Asked once per item; the count comes from <span className="vs-mono">{g.repeat_count}</span>.
          </Alert>
        ) : (
          <Alert color="yellow" icon={<IconAlertTriangle />} title="No repeat count">
            The agent will ask "is there another?" after each item.
          </Alert>
        )
      )}

      <Section title="Skip logic">
        <SkipLogic q={g} byRow={byRow} onSelect={onSelect} />
        {g.relevant && <Text size="xs" c="gray.7" mt="xs">Every question inside is skipped when this is false.</Text>}
      </Section>

      <Section title="Contents" meta={`${direct.length} rows directly inside`}>
        <Table withTableBorder highlightOnHover>
          <Table.Tbody>
            {direct.map((q) => {
              const worst = worstOf(openIssues(isContainer(q) ? [] : issuesByQuestion[q.name] ?? []))
              return (
                <Table.Tr key={q.position} style={{ cursor: 'pointer' }} onClick={() => onSelect(q.name)}>
                  <Table.Td w={36}><KindIcon kind={q.kind} /></Table.Td>
                  <Table.Td>
                    <Text size="sm" className="vs-mono" fw={600}>{q.name}</Text>
                    <Text size="xs" c="gray.7" lineClamp={1} lang={isHindi(lang) ? 'hi' : undefined}>{firstLabel(q, lang)}</Text>
                  </Table.Td>
                  <Table.Td w={120}><TypeLabel>{q.raw_type.split(/\s+/)[0]}</TypeLabel></Table.Td>
                  <Table.Td w={130}>{q.relevant && <Tooltip label={q.relevant_plain || q.relevant}><Text size="xs" c="gray.7">has skip logic</Text></Tooltip>}</Table.Td>
                  <Table.Td w={36}>{worst && <SeverityIcon severity={worst} />}</Table.Td>
                </Table.Tr>
              )
            })}
          </Table.Tbody>
        </Table>
      </Section>

      <Section title={`${g.kind === 'repeat' ? 'Repeat' : 'Group'} label`}>
        <PerLanguageText q={g} field="label" texts={g.labels} languages={languages} defaultLang={defaultLang} minRows={1}
          editable={editable} valueOf={valueOf} setChange={setChange} />
      </Section>
      <Section title="Phone agent">
        <Flag q={g} field="not_used_by_phone" label="Not used by phone" description="Skips everything inside on calls" editable={editable} valueOf={valueOf} setChange={setChange} />
      </Section>
      <Advanced>
        {editable && <RawExpression q={g} field="relevant" label="relevant (skip logic)" valueOf={valueOf} setChange={setChange} />}
        <OtherColumns q={g} />
      </Advanced>
    </Stack>
  )
}

// ---------------------------------------------------------------------------
// Form-wide summary (right column)

function FormSummary({ v, languages, defaultLang, onSelect }: {
  v: VersionDetail; languages: string[]; defaultLang: string; onSelect: (name: string) => void
}) {
  const r = v.report
  const open = openIssues(r?.issues ?? [])
  const blockers = open.filter((i) => i.severity === 'blocker').length
  const formLevel = open.filter((i) => !i.question_name)
  const byCheck = Object.entries(
    open.filter((i) => i.question_name).reduce<Record<string, Issue[]>>((m, i) => ((m[i.check_title] ??= []).push(i), m), {}),
  ).sort((a, b) => SEVERITY_RANK[b[1][0].severity] - SEVERITY_RANK[a[1][0].severity] || b[1].length - a[1].length)
  const s = v.summary
  const tiles: [string, string | number][] = [
    ['Questions', s.question_count], ['Notes', s.note_count], ['Background', s.background_count], ['Groups', s.group_count],
    ['Repeats', s.repeat_count], ['Choice lists', s.choice_list_count], ['Est. call', r ? `~${r.estimated_minutes} min` : '—'], ['Rows', v.questions.length],
  ]

  return (
    <Stack gap="md" p="md">
      <Text size="xs" fw={600} c="gray.8" tt="uppercase" style={{ letterSpacing: '0.04em' }}>Form summary</Text>
      <div>
        <StatusBadge status={r?.status} />
        <Text size="xs" c="gray.7" mt={6}>
          {r?.status === 'not_ready' ? `${blockers} open blocker${blockers === 1 ? '' : 's'}. Calls can't start until each is fixed or accepted.`
            : r?.status === 'ready_with_warnings' ? 'Calls can start; some questions may struggle on the phone.'
            : r?.status === 'ready' ? 'All phone checks pass.' : 'No phone check yet.'}
        </Text>
      </div>
      <SimpleGrid cols={2} spacing={0} style={{ border: '1px solid var(--vs-line)', borderRadius: 4 }}>
        {tiles.map(([label, value], i) => (
          <Box key={label} px="sm" py={8} style={{ borderTop: i > 1 ? '1px solid var(--vs-line)' : undefined, borderLeft: i % 2 ? '1px solid var(--vs-line)' : undefined }}>
            <Text size="xs" c="gray.7">{label}</Text>
            <Text fz={16} fw={600} className="vs-num">{value}</Text>
          </Box>
        ))}
      </SimpleGrid>
      <div>
        <Text size="sm" fw={600} mb={6}>Languages</Text>
        <Group gap={6}>{languages.map((l) => <LanguageChip key={l} lang={l} isDefault={l === defaultLang && languages.length > 1} />)}</Group>
      </div>
      {formLevel.length > 0 && (
        <div>
          <Text size="sm" fw={600} mb={6}>Form-wide</Text>
          <Stack gap={6}>
            {formLevel.map((i) => (
              <Group key={i.id} gap={6} p="xs" wrap="nowrap" align="flex-start"
                bg={i.severity === 'blocker' ? '#fbe9e7' : i.severity === 'warning' ? '#fdf3dc' : '#e4f3f4'}
                style={{ border: `1px solid ${i.severity === 'blocker' ? '#efb2ab' : i.severity === 'warning' ? '#ecc979' : '#a6d3d7'}`, borderRadius: 4 }}>
                <Box mt={2}><SeverityIcon severity={i.severity} size={14} /></Box>
                <Text size="xs"><b>{i.check_title}.</b> {i.message}</Text>
              </Group>
            ))}
          </Stack>
        </div>
      )}
      <div>
        <Text size="sm" fw={600} mb={6}>Open issues by check</Text>
        {!byCheck.length && <Text size="xs" c="gray.7">No open issues on questions.</Text>}
        <Stack gap={10}>
          {byCheck.map(([title, list]) => (
            <Box key={title}>
              <Group gap={6} wrap="nowrap" justify="space-between">
                <Group gap={6} wrap="nowrap"><SeverityIcon severity={list[0].severity} size={14} /><Text size="sm">{title}</Text></Group>
                <Text size="xs" c="gray.7" className="vs-num">{list.length}</Text>
              </Group>
              <Group gap={6} mt={2} pl={20}>
                {list.slice(0, 12).map((i) => (
                  <Anchor key={i.id} size="xs" className="vs-mono" component="button" underline="always" onClick={() => onSelect(i.question_name!)}>{i.question_name}</Anchor>
                ))}
                {list.length > 12 && <Text size="xs" c="gray.7">+{list.length - 12} more</Text>}
              </Group>
            </Box>
          ))}
        </Stack>
      </div>
    </Stack>
  )
}
