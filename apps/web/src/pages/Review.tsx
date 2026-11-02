import { ActionIcon, Anchor, Box, Button, Group, Modal, Paper, Select, Stack, Tabs, Text, Textarea, TextInput, Tooltip } from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  IconArrowBackUp,
  IconArrowRight,
  IconCheck,
  IconCircleCheck,
  IconCircleX,
  IconFileExport,
  IconPencil,
  IconPlayerPlay,
  IconPlayerStopFilled,
  IconX,
} from '@tabler/icons-react'
import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { ApiError, recordingUrl, reviewApi, type ReviewAnswer, type ReviewGroup, type ReviewLogEntry, type ReviewState } from '../api'
import { FlagBadge, type FlagKey, ReviewStateBadge } from '../components/badges'
import { ErrorNotice, fmtDate, PageBody, PageHeader, SkeletonRows } from '../components/layout'
import { useProjectId } from '../hooks'

const TABS: ReviewState[] = ['pending', 'approved', 'rejected', 'edited']
const FLAG_KEY: Record<ReviewAnswer['flags'][number], FlagKey> = {
  low_confidence: 'low_confidence', mismatch: 'mismatch', unclear: 'unclear', attempts: 'attempts', corrected: 'corrected',
}
const FLAG_FILTER = [
  { value: 'low_confidence', label: 'low confidence' }, { value: 'mismatch', label: 'second-pass mismatch' },
  { value: 'unclear', label: 'unclear after 3 tries' },
  { value: 'attempts', label: 'more than 2 attempts' }, { value: 'corrected', label: 'corrected by respondent' },
]
const fmt = (t: number | null) => (t == null ? '—' : `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(Math.floor(t % 60)).padStart(2, '0')}`)
const pid = (id: number) => `#${String(id).padStart(4, '0')}`

type Pending = { kind: 'reject' | 'edit'; answer: ReviewAnswer } | { kind: 'reject-interview'; interviewId: number } | null

export default function Review() {
  const projectId = useProjectId()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const state = (params.get('state') as ReviewState) || 'pending'
  const filters = { flag: params.get('flag') ?? '', question: params.get('question') ?? '', language: params.get('language') ?? '',
    interview_id: params.get('interview') ?? '', form_id: params.get('form') ?? '' }
  const set = (k: string, v: string | null) => setParams((p) => { if (v) p.set(k, v); else p.delete(k); return p }, { replace: true })

  const queue = useQuery({
    queryKey: ['review', projectId, state, filters], enabled: projectId != null,
    queryFn: () => reviewApi.queue(projectId!, { state, ...filters }),
  })
  const [pending, setPending] = useState<Pending>(null)
  const log = useQuery({ queryKey: ['review-log', projectId], queryFn: () => reviewApi.log(projectId!), enabled: projectId != null })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['review'] })
    qc.invalidateQueries({ queryKey: ['review-log'] })
    qc.invalidateQueries({ queryKey: ['review-count'] })
    qc.invalidateQueries({ queryKey: ['interview'] })
  }
  const answerAct = useMutation({
    mutationFn: (v: { id: number; action: 'approve' | 'reject' | 'edit' | 'reset'; value?: string; reason?: string }) =>
      reviewApi.answer(v.id, v), onSuccess: () => { setPending(null); refresh() },
  })
  const interviewAct = useMutation({
    mutationFn: (v: { id: number; action: 'approve' | 'reject'; reason?: string }) => reviewApi.interview(v.id, v),
    onSuccess: () => { setPending(null); refresh() },
  })
  const clip = useClipPlayer()

  const data = queue.data
  const groups = data?.groups ?? []
  const shown = groups.reduce((n, g) => n + g.answers.length, 0)

  return (
    <>
      <PageHeader title="Review" subtitle="Flagged answers across all interviews. Listen, then approve, reject or correct. Raw answers are never overwritten."
        actions={<Button variant="default" component={Link} to="/export" leftSection={<IconFileExport size={16} />}>Export approved</Button>}>
        <Tabs value={state} onChange={(v) => set('state', v === 'pending' ? null : v)} mt="sm">
          <Tabs.List style={{ borderBottom: 0 }}>
            {TABS.map((t) => (
              <Tabs.Tab key={t} value={t} rightSection={<Text span size="xs" fw={600} px={6} bg="#eef0f2" style={{ borderRadius: 9 }} className="vs-num">{data?.counts[t] ?? 0}</Text>}>
                <Text span size="sm" fw={state === t ? 600 : 400} tt="capitalize">{t}</Text>
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>
      </PageHeader>
      <Box bg="white" px="xl" py="sm" style={{ borderBottom: '1px solid var(--vs-line)' }}>
        <Group justify="space-between">
          <Group gap="sm">
            <Select size="xs" w={190} placeholder="Flag: any" clearable data={FLAG_FILTER} value={filters.flag || null} onChange={(v) => set('flag', v)} aria-label="Flag" />
            <Select size="xs" w={170} placeholder="Question: any" clearable searchable data={data?.questions ?? []} value={filters.question || null} onChange={(v) => set('question', v)} aria-label="Question" />
            <Select size="xs" w={140} placeholder="Language: any" clearable data={[{ value: 'en', label: 'English' }, { value: 'hi', label: 'Hindi' }]}
              value={filters.language || null} onChange={(v) => set('language', v)} aria-label="Language" />
            <TextInput size="xs" w={130} placeholder="Interview #" value={filters.interview_id} aria-label="Interview number"
              onChange={(e) => set('interview', e.currentTarget.value.replace(/\D/g, '') || null)} />
            <Select size="xs" w={220} placeholder="Form: any" clearable data={(data?.forms ?? []).map((f) => ({ value: String(f.id), label: f.title }))}
              value={filters.form_id || null} onChange={(v) => set('form', v)} aria-label="Form" />
          </Group>
          <Text size="xs" c="gray.7" className="vs-num">Showing {shown} in {groups.length} interview{groups.length === 1 ? '' : 's'}</Text>
        </Group>
      </Box>
      <PageBody maw={1500}>
        <Group align="flex-start" gap="lg" wrap="nowrap">
          <Stack gap="md" style={{ flex: 1, minWidth: 0 }}>
            {queue.isError && <ErrorNotice title="Couldn't load the review queue" detail={(queue.error as Error).message} />}
            {queue.isLoading && <SkeletonRows />}
            {answerAct.error && <ErrorNotice title="Couldn't save the review" message={(answerAct.error as ApiError).message} />}
            {queue.isSuccess && !groups.length && (
              <Paper bg="white" p={48} ta="center">
                <Text fw={600}>{state === 'pending' ? 'Nothing waiting for review' : `No ${state} answers`}</Text>
                <Text size="sm" c="gray.7" mt={4}>
                  {state === 'pending' ? 'Answers with low confidence, a second-pass mismatch, no clear answer after 3 tries, more than 2 attempts or a correction show up here.' : 'Try another tab or clear the filters.'}
                </Text>
              </Paper>
            )}
            {groups.map((g) => (
              <InterviewGroup key={g.interview.id} g={g} state={state} clip={clip}
                onApprove={(a) => answerAct.mutate({ id: a.id, action: 'approve' })}
                onReset={(a) => answerAct.mutate({ id: a.id, action: 'reset' })}
                onReject={(a) => setPending({ kind: 'reject', answer: a })}
                onEdit={(a) => setPending({ kind: 'edit', answer: a })}
                onApproveInterview={() => interviewAct.mutate({ id: g.interview.id, action: 'approve' })}
                busy={answerAct.isPending || interviewAct.isPending} />
            ))}
          </Stack>
          <ReviewLog entries={log.data ?? []} />
        </Group>
      </PageBody>

      <ReasonModal pending={pending} onClose={() => setPending(null)} loading={answerAct.isPending || interviewAct.isPending}
        error={((answerAct.error ?? interviewAct.error) as ApiError | null)?.message}
        onSubmit={(reason, value) => {
          if (!pending) return
          if (pending.kind === 'reject-interview') interviewAct.mutate({ id: pending.interviewId, action: 'reject', reason })
          else answerAct.mutate({ id: pending.answer.id, action: pending.kind, reason, value })
        }} />
    </>
  )
}

function InterviewGroup({ g, state, clip, onApprove, onReject, onEdit, onReset, onApproveInterview, busy }: {
  g: ReviewGroup; state: ReviewState; clip: ClipPlayer; busy: boolean
  onApprove: (a: ReviewAnswer) => void; onReject: (a: ReviewAnswer) => void; onEdit: (a: ReviewAnswer) => void
  onReset: (a: ReviewAnswer) => void; onApproveInterview: () => void
}) {
  const i = g.interview
  const hi = i.language === 'hi'
  return (
    <Paper bg="white" style={{ overflow: 'hidden' }}>
      <Group justify="space-between" px="md" py={8} bg="#f8f9fa" style={{ borderBottom: '1px solid var(--vs-line)' }}>
        <Group gap="sm">
          <Anchor component={Link} to={`/interviews/${i.id}`} fw={600} className="vs-mono" underline="always">{pid(i.id)}</Anchor>
          <Text size="sm">{i.participant_label || '—'} · {hi ? 'Hindi' : 'English'} · v{i.version_no} · {fmtDate(i.started_at)}</Text>
          <Text size="xs" c="gray.7">{i.pending} still pending</Text>
          {i.review_state !== 'pending' && <ReviewStateBadge state={i.review_state} />}
        </Group>
        {state === 'pending' && i.review_state !== 'approved' && (
          <Button size="xs" variant="default" leftSection={<IconCheck size={14} color="#2a8a4d" />} disabled={busy} onClick={onApproveInterview}>
            Approve interview
          </Button>
        )}
      </Group>
      {g.answers.map((a) => {
        const label = Object.entries(a.labels).find(([k]) => (hi ? /hindi|\(hi\)/i : /english|\(en\)|default/i).test(k))?.[1] ?? Object.values(a.labels)[0]
        return (
          <Group key={a.id} align="flex-start" gap="md" px="md" py="sm" wrap="nowrap" style={{ borderBottom: '1px solid #eef0f2' }}>
            <Box w={220} style={{ flexShrink: 0 }}>
              <Text size="sm" className="vs-mono" fw={600}>{a.key}</Text>
              {label && <Text size="xs" c="gray.7" lineClamp={2} lang={hi ? 'hi' : undefined}>{label.replace(/<[^>]+>/g, '')}</Text>}
            </Box>
            <Box w={170} style={{ flexShrink: 0 }}>
              {a.review_state === 'edited' ? (
                <Group gap={4} wrap="nowrap">
                  <Text size="sm" td="line-through" c="gray.7">{a.code ?? a.value}</Text>
                  <IconArrowRight size={12} color="#5c636d" />
                  <Text size="sm" fw={600}>{a.reviewed_value}</Text>
                </Group>
              ) : <Text size="sm" fw={600} td={a.review_state === 'rejected' ? 'line-through' : undefined}>{a.code ?? a.value ?? '—'}</Text>}
              {a.flagged && a.second_pass_value && <Text size="xs" fw={600} c="yellow.7">2nd pass: {a.second_pass_value}</Text>}
              {a.confidence != null && <Text size="xs" c={a.confidence < 0.7 ? 'yellow.7' : 'gray.7'} className="vs-num">conf. {a.confidence.toFixed(2)} · {a.attempts} {a.attempts === 1 ? 'try' : 'tries'}</Text>}
            </Box>
            <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
              <Group gap={6} wrap="nowrap" align="flex-start">
                <Text size="xs" c="gray.7" w={56} style={{ flexShrink: 0 }}>Heard</Text>
                <Text size="sm" lang={hi ? 'hi' : undefined}>“{a.heard_text || '—'}”</Text>
              </Group>
              {a.second_pass_text != null && (
                <Group gap={6} wrap="nowrap" align="flex-start">
                  <Text size="xs" c="gray.7" w={56} style={{ flexShrink: 0 }}>2nd pass</Text>
                  <Text size="sm" c={a.flagged ? 'yellow.7' : undefined} lang={hi ? 'hi' : undefined}>“{a.second_pass_text}”</Text>
                </Group>
              )}
              <Group gap={4}>{a.flags.map((f) => <FlagBadge key={f} flag={FLAG_KEY[f]} />)}</Group>
              {a.review_reason && <Text size="xs" c="gray.8"><b>Reason:</b> {a.review_reason}</Text>}
            </Stack>
            <Group gap={6} wrap="nowrap" style={{ flexShrink: 0 }}>
              {i.has_recording && a.t_answer_start != null && (
                <Button size="compact-sm" variant="default" leftSection={clip.playing === a.id ? <IconPlayerStopFilled size={12} /> : <IconPlayerPlay size={12} />}
                  onClick={() => clip.toggle(a.id, i.id, a.t_answer_start!, a.t_answer_end)} aria-label={`Play the answer to ${a.key}`}>
                  <span className="vs-mono">{fmt(a.t_answer_start)}</span>
                </Button>
              )}
              {state === 'pending' ? (
                <>
                  <Button size="compact-sm" variant="default" leftSection={<IconCheck size={13} color="#2a8a4d" />} disabled={busy} onClick={() => onApprove(a)}>Approve</Button>
                  <Tooltip label="Reject (needs a reason)"><ActionIcon variant="default" size={26} disabled={busy} onClick={() => onReject(a)} aria-label="Reject"><IconX size={14} color="#c8302a" /></ActionIcon></Tooltip>
                  <Tooltip label="Edit value (needs a reason)"><ActionIcon variant="default" size={26} disabled={busy} onClick={() => onEdit(a)} aria-label="Edit value"><IconPencil size={14} /></ActionIcon></Tooltip>
                </>
              ) : (
                <>
                  <ReviewStateBadge state={a.review_state} />
                  <Button size="compact-sm" variant="subtle" leftSection={<IconArrowBackUp size={13} />} disabled={busy} onClick={() => onReset(a)}>Reopen</Button>
                </>
              )}
            </Group>
          </Group>
        )
      })}
    </Paper>
  )
}

function ReasonModal({ pending, onClose, onSubmit, loading, error }: {
  pending: Pending; onClose: () => void; onSubmit: (reason: string, value?: string) => void; loading: boolean; error?: string
}) {
  const [reason, setReason] = useState('')
  const [value, setValue] = useState('')
  const edit = pending?.kind === 'edit'
  const a = pending && pending.kind !== 'reject-interview' ? pending.answer : null
  const title = edit ? 'Edit value' : pending?.kind === 'reject-interview' ? 'Reject interview' : 'Reject answer'
  return (
    <Modal opened={!!pending} onClose={onClose} title={<Text fw={600}>{title}</Text>}
      onExitTransitionEnd={() => { setReason(''); setValue('') }}>
      <Stack>
        {a && (
          <Paper p="sm" bg="#f8f9fa">
            <Text size="sm" className="vs-mono" fw={600}>{a.key}</Text>
            <Text size="sm">Value: <b>{a.code ?? a.value}</b> · heard “{a.heard_text}”</Text>
          </Paper>
        )}
        {edit && <TextInput label="Reviewed value" required description="Stored next to the original; the original is kept." data-autofocus
          value={value} onChange={(e) => setValue(e.currentTarget.value)} />}
        <Textarea label="Reason" required minRows={3} data-autofocus={!edit} value={reason} onChange={(e) => setReason(e.currentTarget.value)}
          placeholder={edit ? 'e.g. Listened twice: respondent says 47' : 'e.g. Respondent was answering for someone else'} error={error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button color={edit ? undefined : 'red'} disabled={!reason.trim() || (edit && !value.trim())} loading={loading}
            leftSection={edit ? <IconPencil size={14} /> : <IconCircleX size={14} />} onClick={() => onSubmit(reason.trim(), value.trim())}>
            {edit ? 'Save reviewed value' : 'Reject'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}

const ACTION: Record<string, [typeof IconCheck, string, string]> = {
  approved: [IconCircleCheck, '#2a8a4d', 'Approved'], rejected: [IconCircleX, '#c8302a', 'Rejected'], edited: [IconPencil, '#138591', 'Edited'],
  reopened: [IconArrowBackUp, '#5c636d', 'Reopened'], interview_approved: [IconCircleCheck, '#2a8a4d', 'Approved interview'],
  interview_rejected: [IconCircleX, '#c8302a', 'Rejected interview'], interview_pending: [IconArrowBackUp, '#5c636d', 'Reopened interview'],
}

function ReviewLog({ entries }: { entries: ReviewLogEntry[] }) {
  return (
    <Paper bg="white" w={300} style={{ flexShrink: 0, position: 'sticky', top: 24, overflow: 'hidden' }}>
      <Text fw={600} px="md" py={10} style={{ borderBottom: '1px solid var(--vs-line)' }}>Review log</Text>
      <Box mah="70vh" style={{ overflowY: 'auto' }}>
        {!entries.length && <Text size="sm" c="gray.7" p="md">No review actions yet.</Text>}
        {entries.map((e) => {
          const [I, color, label] = ACTION[e.action] ?? [IconPencil, '#5c636d', e.action]
          return (
            <Box key={e.id} px="md" py="sm" style={{ borderBottom: '1px solid #eef0f2' }}>
              <Group gap={6} wrap="nowrap"><I size={14} color={color} /><Text size="sm" fw={600}>{label}</Text>
                {e.subject !== 'interview' && <Text size="sm" className="vs-mono">{e.subject}</Text>}</Group>
              <Text size="xs" c="gray.8" mt={2}>
                <Anchor component={Link} to={`/interviews/${e.interview_id}`} size="xs">{pid(e.interview_id)}</Anchor>
                {e.action === 'edited' && <> · {e.old_value} → {e.new_value}</>}
                {e.action === 'interview_approved' && e.new_value && <> · {e.new_value}</>}
                {e.reason && <> · {e.reason}</>}
              </Text>
              <Text size="xs" c="gray.7">{e.user} · {fmtDate(e.time)}</Text>
            </Box>
          )
        })}
      </Box>
    </Paper>
  )
}

// One shared <audio> per page: plays just an answer's clip from the interview recording.
type ClipPlayer = { playing: number | null; toggle: (answerId: number, interviewId: number, from: number, to: number | null) => void }

function useClipPlayer(): ClipPlayer {
  const audio = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState<number | null>(null)
  const toggle: ClipPlayer['toggle'] = (answerId, interviewId, from, to) => {
    audio.current?.pause()
    if (playing === answerId) { setPlaying(null); return }
    const el = new Audio(recordingUrl(interviewId))
    audio.current = el
    el.currentTime = Math.max(0, from - 0.3)
    el.ontimeupdate = () => { if (to != null && el.currentTime >= to + 0.3) { el.pause(); setPlaying(null) } }
    el.onended = () => setPlaying(null)
    el.onloadedmetadata = () => { el.currentTime = Math.max(0, from - 0.3) }
    setPlaying(answerId)
    void el.play().catch(() => setPlaying(null))
  }
  return { playing, toggle }
}
