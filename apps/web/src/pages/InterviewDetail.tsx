import { ActionIcon, Alert, Anchor, Box, Button, Checkbox, Group, Paper, SegmentedControl, SimpleGrid, Table, Text, Tooltip } from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  IconCalendarTime,
  IconChecklist,
  IconCircleHalf2,
  IconDownload,
  IconFileText,
  IconHistory,
  IconPlayerPauseFilled,
  IconPlayerPlay,
  IconPlayerPlayFilled,
  IconRewindBackward5,
  IconRobot,
  IconSettings,
  IconUser,
} from '@tabler/icons-react'
import { useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { type AnswerRow, type InterviewDetail as Detail, recordingUrl, type TranscriptSegment, type TurnRow, voiceApi } from '../api'
import { ChannelBadge, FlagBadge, type FlagKey, InterviewStatusBadge, LIVE_STATUSES, PersonaBadge, ReviewStateBadge } from '../components/badges'
import { ErrorNotice, fmtDate, PageBody, PageHeader, SkeletonRows, Tile } from '../components/layout'
import { labelIn, langAttr, langName } from '../languages'

const LOW_CONFIDENCE = 0.7
const fmt = (t: number | null | undefined) => (t == null ? '—' : `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(Math.floor(t % 60)).padStart(2, '0')}`)
const indexed = (a: AnswerRow) => `${a.question_name}${a.repeat_index.length ? `[${a.repeat_index.map((x) => x + 1).join('][')}]` : ''}`

function flagsOf(a: AnswerRow): FlagKey[] {
  const f: FlagKey[] = []
  if (!a.still_relevant) f.push('not_used')
  if (a.code === 'dk') f.push('dk')
  if (a.code === 'refused') f.push('refused')
  if (a.code === 'unclear') f.push('unclear')
  if (a.confirmed) f.push('confirmed')
  if (a.corrected) f.push('corrected')
  if (a.confidence != null && a.confidence < LOW_CONFIDENCE) f.push('low_confidence')
  if (a.flagged && a.code !== 'unclear') f.push('mismatch')
  if (a.attempts > 2) f.push('attempts')
  return f
}
/** Question text in the interview language; form languages look like "Hindi (hi)" or "English". */
const labelFor = labelIn
// Same rule as the review queue (app/review.py: answer_flags).
const needsReview = (a: AnswerRow) => a.still_relevant && flagsOf(a).some((f) => f === 'low_confidence' || f === 'mismatch' || f === 'unclear' || f === 'attempts' || f === 'corrected')

export default function InterviewDetail() {
  const id = Number(useParams().interviewId)
  const q = useQuery({
    queryKey: ['interview', id],
    queryFn: () => voiceApi.interview(id),
    refetchInterval: (query) => (LIVE_STATUSES.includes(query.state.data?.status ?? '') ? 2000 : false),
  })
  const [flaggedOnly, setFlaggedOnly] = useState(false)
  const [speaker, setSpeaker] = useState('all')
  const player = useRef<PlayerHandle | null>(null)

  if (q.isLoading) return <><PageHeader title={`Interview #${String(id).padStart(4, '0')}`} /><PageBody><SkeletonRows /></PageBody></>
  const i = q.data
  if (!i) return <PageBody><ErrorNotice title="Interview not found" detail={(q.error as Error | null)?.message} /></PageBody>

  const live = LIVE_STATUSES.includes(i.status)
  const seek = (t: number | null, until?: number | null) => player.current?.seek(t, until)
  const lat = i.turns.filter((t) => t.latency_ms != null).map((t) => t.latency_ms!)
  const relevant = i.answers.filter((a) => a.still_relevant)
  const flagged = i.answers.filter(needsReview)
  const pendingReview = flagged.filter((a) => a.review_state === 'pending').length
  const reasks = relevant.reduce((n, a) => n + Math.max(0, a.attempts - 1), 0)
  const reaskedQs = relevant.filter((a) => a.attempts > 1).length
  const answers = flaggedOnly ? flagged : i.answers
  const turns = speaker === 'all' ? i.turns : i.turns.filter((t) => t.speaker === speaker)
  const callSecs = i.started_at && i.ended_at ? (new Date(i.ended_at).getTime() - new Date(i.started_at).getTime()) / 1000 : null
  const asking = live ? [...i.turns].reverse().find((t) => t.speaker === 'agent')?.node_name : undefined
  const isHi = langAttr(i.language)

  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Forms', to: '/' }, { label: i.form.title, to: `/forms/${i.form.id}/interviews` }, { label: 'Phone interviews', to: `/forms/${i.form.id}/interviews` }, { label: `#${String(i.id).padStart(4, '0')}` }]}
        title={`Interview #${String(i.id).padStart(4, '0')}`}
        extra={<Group gap={6} wrap="nowrap"><InterviewStatusBadge status={i.status} />
          {!live && i.review_state && i.review_state !== 'pending' && <ReviewStateBadge state={i.review_state} title={i.review_reason || undefined} />}
          {i.persona && <PersonaBadge persona={i.persona} />}</Group>}
        subtitle={<>{i.form.title} · v{i.form.version_no}{i.participant_label && ` · ${i.participant_label}`}
          {i.campaign_id && <> · <Anchor component={Link} to={`/campaigns/${i.campaign_id}`} size="sm">campaign</Anchor></>}
          {i.simulation_run_id && <> · <Anchor component={Link} to={`/simulations/${i.simulation_run_id}`} size="sm">simulation run #{i.simulation_run_id}</Anchor></>}</>}
        actions={<>
          {i.has_recording && !live && (
            <Button variant="default" component="a" href={recordingUrl(i.id)} download={`interview-${i.id}.wav`} leftSection={<IconDownload size={16} />}>Audio</Button>
          )}
          {!live && (
            <Button component={Link} to={`/review?interview=${i.id}`} leftSection={<IconChecklist size={16} />}
              variant={pendingReview ? 'filled' : 'default'}>{pendingReview ? `Review ${pendingReview} flagged` : 'Review'}</Button>
          )}
        </>} />
      <PageBody>
        <SimpleGrid cols={{ base: 3, lg: 6 }} spacing="sm">
          <Tile label="Language" value={langName(i.language)} />
          <Tile label="Channel"><Box mt={6}><ChannelBadge channel={i.channel} /></Box></Tile>
          <Tile label="Answers" value={relevant.length} note={i.answers.length > relevant.length ? `${i.answers.length - relevant.length} not used` : 'all used'} />
          <Tile label="Re-asks" value={reasks} note={reasks ? `across ${reaskedQs} question${reaskedQs > 1 ? 's' : ''}` : 'none'} />
          <Tile label="Avg reply delay" value={lat.length ? `${(lat.reduce((a, b) => a + b, 0) / lat.length / 1000).toFixed(2)} s` : '—'} note="agent response time" />
          <Tile label="Call length" value={callSecs != null ? fmt(callSecs) : live ? 'live' : '—'} note={`started ${fmtDate(i.started_at ?? i.created_at)}`} />
        </SimpleGrid>

        {i.status === 'callback' && (
          <Alert color="teal" icon={<IconCalendarTime />} title={`Call back: ${i.callback_when || 'time not given'}`}>
            The respondent asked to be called later. Answers so far are kept.
          </Alert>
        )}
        {i.status === 'partial' && (
          <Alert color="yellow" icon={<IconCircleHalf2 />} title="Partial interview">
            The call ended before the last question. {relevant.length} answers were saved and are kept.
          </Alert>
        )}
        {i.resumed_from_id && (
          <Alert color="blue" icon={<IconHistory />} title="Continued from an earlier call">
            This call picked up where <Anchor component={Link} to={`/interviews/${i.resumed_from_id}`} size="sm">interview #{String(i.resumed_from_id).padStart(4, '0')}</Anchor> left
            off. Answers from that call were carried over (consent was asked again); their timings point to the earlier recording.
          </Alert>
        )}
        {i.error && <ErrorNotice title="Something went wrong on this call" detail={i.error} />}

        {live ? (
          <Paper bg="white" p="md">
            <Group gap={8}>
              <Box w={10} h={10} bg="brand.6" style={{ borderRadius: '50%' }} className="vs-pulse" />
              <Text size="sm" fw={600}>Call in progress</Text>
              <Text size="sm" c="gray.7">Answers fill in below as they're given. The recording player appears when the call ends.</Text>
            </Group>
          </Paper>
        ) : i.has_recording ? (
          <Player ref={player} i={i} />
        ) : (
          <Paper bg="white" p="md"><Text size="sm" c="gray.7">No recording for this interview.</Text></Paper>
        )}

        <Paper bg="white" style={{ overflow: 'hidden' }}>
          <Group justify="space-between" px="md" py={10} style={{ borderBottom: '1px solid var(--vs-line)' }}>
            <Group gap={8} align="baseline">
              <Text fw={600}>Answers</Text>
              <Text size="xs" c="gray.7">{relevant.length} answers · {flagged.length} flagged</Text>
            </Group>
            <Checkbox size="xs" label="Flagged only" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.currentTarget.checked)} />
          </Group>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Question</Table.Th>
                <Table.Th>Value</Table.Th>
                <Table.Th>Heard</Table.Th>
                <Table.Th>Second pass</Table.Th>
                <Table.Th ta="right">Conf.</Table.Th>
                <Table.Th ta="right">Tries</Table.Th>
                <Table.Th>Flags</Table.Th>
                <Table.Th w={120}>Asked at</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {answers.map((a) => <AnswerTableRow key={a.id} a={a} lang={i.language} seek={seek} canPlay={i.has_recording && !live} />)}
              {asking && (
                <Table.Tr bg="var(--vs-brand-tint)" style={{ boxShadow: 'inset 3px 0 0 #1f4fa3' }}>
                  <Table.Td><Text size="sm" className="vs-mono">{asking}</Text></Table.Td>
                  <Table.Td colSpan={7}><Group gap={6}><Box w={8} h={8} bg="brand.6" style={{ borderRadius: '50%' }} className="vs-pulse" /><Text size="sm" fw={600} c="brand.6">Asking now…</Text></Group></Table.Td>
                </Table.Tr>
              )}
              {!answers.length && !asking && (
                <Table.Tr><Table.Td colSpan={8}><Text c="gray.7" ta="center" py="md" size="sm">{flaggedOnly ? 'No flagged answers.' : 'No answers yet.'}</Text></Table.Td></Table.Tr>
              )}
            </Table.Tbody>
          </Table>
          <Text size="xs" c="gray.7" px="md" py={8} style={{ borderTop: '1px solid var(--vs-line)' }}>
            Second pass = an independent re-transcription of the same audio. Low confidence = below {LOW_CONFIDENCE.toFixed(2)}.
            Struck-through rows were answered, then made irrelevant by a later correction; they're kept but not used.
          </Text>
        </Paper>

        <Paper bg="white" style={{ overflow: 'hidden' }}>
          <Group justify="space-between" px="md" py={10} style={{ borderBottom: '1px solid var(--vs-line)' }}>
            <Group gap={8} align="baseline"><Text fw={600}>Turn log</Text><Text size="xs" c="gray.7">{i.turns.length} turns</Text></Group>
            <SegmentedControl value={speaker} onChange={setSpeaker} data={[
              { value: 'all', label: 'All' }, { value: 'agent', label: 'Agent' }, { value: 'respondent', label: 'Respondent' }, { value: 'system', label: 'System' },
            ]} />
          </Group>
          <Table>
            <Table.Thead>
              <Table.Tr><Table.Th w={80}>Time</Table.Th><Table.Th w={130}>Speaker</Table.Th><Table.Th w={180}>Node</Table.Th><Table.Th>Text</Table.Th><Table.Th w={110} ta="right">Reply delay</Table.Th></Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {turns.map((t) => <TurnTableRow key={t.id} t={t} hi={isHi} seek={i.has_recording && !live ? seek : undefined} />)}
              {!turns.length && <Table.Tr><Table.Td colSpan={5}><Text c="gray.7" ta="center" py="md" size="sm">No turns yet.</Text></Table.Td></Table.Tr>}
            </Table.Tbody>
          </Table>
        </Paper>

        {!live && i.has_recording && <FullTranscript i={i} hi={isHi} seek={seek} />}
      </PageBody>
    </>
  )
}

function AnswerTableRow({ a, lang, seek, canPlay }: { a: AnswerRow; lang: string; seek: (t: number | null, until?: number | null) => void; canPlay: boolean }) {
  const flags = flagsOf(a)
  const notUsed = !a.still_relevant
  const label = labelFor(a.labels, lang)
  const low = a.confidence != null && a.confidence < LOW_CONFIDENCE
  return (
    <Table.Tr className={notUsed ? 'vs-not-used' : undefined}>
      <Table.Td>
        <Text size="sm" className={`vs-mono${notUsed ? ' vs-strike' : ''}`}>{indexed(a)}</Text>
        {label && <Text size="xs" c="gray.7" lineClamp={1} maw={260} lang={langAttr(lang)}>{label.replace(/<[^>]+>/g, '')}</Text>}
      </Table.Td>
      <Table.Td>
        {a.code === 'dk' || a.code === 'refused' || a.code === 'unclear' ? <FlagBadge flag={a.code} /> : (
          <Text size="sm" fw={600} className={notUsed || a.review_state === 'edited' || a.review_state === 'rejected' ? 'vs-strike' : undefined}
            c={a.review_state === 'edited' ? 'gray.7' : undefined}>{a.value ?? '—'}</Text>
        )}
        {a.review_state === 'edited' && (
          <Tooltip label={a.review_reason || 'Edited in review'}><Text size="sm" fw={600}>→ {a.reviewed_value}</Text></Tooltip>
        )}
        {(a.review_state === 'rejected' || a.review_state === 'approved') && (
          <ReviewStateBadge state={a.review_state} title={a.review_reason || undefined} />
        )}
        {a.flagged && a.second_pass_value && <Text size="xs" fw={600} c="yellow.6">value {a.second_pass_value}</Text>}
      </Table.Td>
      <Table.Td maw={260}><Text size="sm" c="gray.8" lang={langAttr(lang)}>{a.heard_text ? `“${a.heard_text}”` : '—'}</Text></Table.Td>
      <Table.Td maw={260}>
        <Text size="sm" c={a.flagged ? 'yellow.6' : 'gray.8'} lang={langAttr(lang)}>{a.second_pass_text ? `“${a.second_pass_text}”` : '—'}</Text>
      </Table.Td>
      <Table.Td ta="right"><Text size="sm" className="vs-num" fw={low ? 600 : undefined} c={low ? 'yellow.6' : undefined}>{a.confidence != null ? a.confidence.toFixed(2) : '—'}</Text></Table.Td>
      <Table.Td ta="right" className="vs-num">{a.attempts}</Table.Td>
      <Table.Td>
        <Group gap={4}>
          {flags.filter((f) => f !== 'dk' && f !== 'refused' && f !== 'unclear').map((f) => (
            <FlagBadge key={f} flag={f} title={f === 'not_used' ? 'Skipped after a later correction' : f === 'low_confidence' ? `Below threshold (${LOW_CONFIDENCE.toFixed(2)})` : undefined} />
          ))}
        </Group>
      </Table.Td>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          {canPlay ? <Anchor size="sm" className="vs-num" component="button" onClick={() => seek(a.t_question)}>{fmt(a.t_question)}</Anchor>
            : <Text size="sm" className="vs-num">{fmt(a.t_question)}</Text>}
          {canPlay && a.t_answer_start != null && (
            <Tooltip label="Play just this answer">
              <ActionIcon variant="default" size="sm" onClick={() => seek(a.t_answer_start, a.t_answer_end)} aria-label={`Play answer to ${indexed(a)}`}>
                <IconPlayerPlay size={12} />
              </ActionIcon>
            </Tooltip>
          )}
        </Group>
      </Table.Td>
    </Table.Tr>
  )
}

const SPEAKER = {
  agent: [IconRobot, 'Agent', '#1f4fa3'],
  respondent: [IconUser, 'Respondent', '#424851'],
  system: [IconSettings, 'System', '#5c636d'],
} as const

function TurnTableRow({ t, hi, seek }: { t: TurnRow; hi?: string; seek?: (t: number | null) => void }) {
  const [I, label, color] = SPEAKER[t.speaker] ?? SPEAKER.system
  const sys = t.speaker === 'system'
  return (
    <Table.Tr bg={sys ? '#f8f9fa' : undefined}>
      <Table.Td>{seek ? <Anchor size="sm" className="vs-num" component="button" onClick={() => seek(t.t)}>{fmt(t.t)}</Anchor> : <Text size="sm" className="vs-num">{fmt(t.t)}</Text>}</Table.Td>
      <Table.Td><Group gap={6} wrap="nowrap"><I size={14} color={color} /><Text size="sm" c={color} fw={t.speaker === 'agent' ? 500 : undefined}>{label}</Text></Group></Table.Td>
      <Table.Td><Text size="xs" className="vs-mono" c="gray.8">{t.node_name || '—'}</Text></Table.Td>
      <Table.Td><Text size="sm" c={sys ? 'gray.7' : undefined} fs={sys ? 'italic' : undefined} lang={hi && !sys ? hi : undefined}>{t.text}</Text></Table.Td>
      <Table.Td ta="right" className="vs-num">{t.latency_ms != null ? `${(t.latency_ms / 1000).toFixed(2)} s` : ''}</Table.Td>
    </Table.Tr>
  )
}

// ---------------------------------------------------------------------------
// Full-call transcript (Gnani Prisma Batch on the recording, one file per channel)

function FullTranscript({ i, hi, seek }: { i: Detail; hi?: string; seek: (t: number | null) => void }) {
  const qc = useQueryClient()
  const run = useMutation({
    mutationFn: () => voiceApi.transcribe(i.id),
    onSettled: () => qc.invalidateQueries({ queryKey: ['interview', i.id] }),
  })
  const state = run.isPending ? 'running' : i.transcript_state ?? 'none'
  const segs: TranscriptSegment[] = i.transcript ?? []
  return (
    <Paper bg="white" style={{ overflow: 'hidden' }}>
      <Group justify="space-between" px="md" py={10} style={{ borderBottom: '1px solid var(--vs-line)' }}>
        <Group gap={8} align="baseline">
          <Text fw={600}>Full call transcript</Text>
          <Text size="xs" c="gray.7">{state === 'done' ? `${segs.length} segments · Gnani Prisma Batch` : 'Gnani Prisma Batch, from the recording'}</Text>
        </Group>
        <Button size="xs" variant="default" leftSection={<IconFileText size={14} />} loading={state === 'running'} onClick={() => run.mutate()}>
          {state === 'done' || state === 'failed' ? 'Transcribe again' : 'Transcribe'}
        </Button>
      </Group>
      {state === 'failed' && <Box p="md"><ErrorNotice title="Transcription failed" detail={i.transcript_error || (run.error as Error | null)?.message} /></Box>}
      {run.isError && state !== 'failed' && <Box p="md"><ErrorNotice title="Transcription failed" detail={(run.error as Error).message} /></Box>}
      {state === 'done' ? (
        <Table>
          <Table.Thead>
            <Table.Tr><Table.Th w={80}>Time</Table.Th><Table.Th w={130}>Speaker</Table.Th><Table.Th>Text</Table.Th></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {segs.map((s, k) => {
              const [I, label, color] = s.speaker === 'call' ? [IconSettings, 'Call', '#5c636d'] as const : SPEAKER[s.speaker]
              return (
                <Table.Tr key={k}>
                  <Table.Td><Anchor size="sm" className="vs-num" component="button" onClick={() => seek(s.start)}>{fmt(s.start)}</Anchor></Table.Td>
                  <Table.Td><Group gap={6} wrap="nowrap"><I size={14} color={color} /><Text size="sm" c={color}>{label}</Text></Group></Table.Td>
                  <Table.Td><Text size="sm" lang={hi}>{s.text}</Text></Table.Td>
                </Table.Tr>
              )
            })}
            {!segs.length && <Table.Tr><Table.Td colSpan={3}><Text c="gray.7" ta="center" py="md" size="sm">No speech found in the recording.</Text></Table.Td></Table.Tr>}
          </Table.Tbody>
        </Table>
      ) : state !== 'failed' && (
        <Text size="sm" c="gray.7" px="md" py="md">
          {state === 'running' ? 'Transcribing the whole call… this usually takes under a minute.'
            : 'Runs automatically after each call. Unlike the turn log (live speech recognition), this re-transcribes the full recording, so it also catches speech the live pass missed.'}
        </Text>
      )}
    </Paper>
  )
}

// ---------------------------------------------------------------------------
// Recording player: native <audio> with custom controls and a three-lane timeline.

type PlayerHandle = { seek: (t: number | null, until?: number | null) => void }

const SPEEDS = [1, 1.5, 2]

function Player({ i, ref }: { i: Detail; ref: React.Ref<PlayerHandle> }) {
  const audio = useRef<HTMLAudioElement>(null)
  const stopAt = useRef<number | null>(null)
  const [t, setT] = useState(0)
  const [dur, setDur] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const lastTurn = i.turns.length ? i.turns[i.turns.length - 1].t : 0
  const total = dur || Math.max(lastTurn + 2, 1)

  const seek = useCallback((to: number | null, until?: number | null) => {
    const el = audio.current
    if (to == null || !el) return
    el.currentTime = Math.max(0, to - 0.3)
    stopAt.current = until ?? null
    void el.play()
  }, [])
  useImperativeHandle(ref, () => ({ seek }), [seek])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = audio.current
      if (!el || /INPUT|TEXTAREA|SELECT|BUTTON/.test((e.target as HTMLElement).tagName)) return
      if (e.code === 'Space') { e.preventDefault(); if (el.paused) void el.play(); else el.pause() }
      if (e.key === 'ArrowLeft') el.currentTime = Math.max(0, el.currentTime - 5)
      if (e.key === 'ArrowRight') el.currentTime = Math.min(el.duration || 0, el.currentTime + 5)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Turn segments: each turn lasts until the next one (capped), drawn in its speaker's lane.
  const segs = i.turns.map((turn, k) => ({ ...turn, end: Math.min(i.turns[k + 1]?.t ?? turn.t + 2, turn.t + 12) }))
  const pct = (x: number) => `${Math.min(100, (x / total) * 100)}%`
  const now = [...i.answers].reverse().find((a) => a.t_question != null && a.t_question <= t)
  const ticks = Array.from({ length: Math.floor(total / 60) + 1 }, (_, k) => k * 60).filter((x) => x <= total)
  const click = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    seek(((e.clientX - r.left) / r.width) * total + 0.3)
  }

  return (
    <Paper bg="white" p="md">
      <audio ref={audio} src={recordingUrl(i.id)} preload="metadata"
        onLoadedMetadata={(e) => setDur(e.currentTarget.duration)} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => {
          const el = e.currentTarget
          setT(el.currentTime)
          if (stopAt.current != null && el.currentTime >= stopAt.current) { el.pause(); stopAt.current = null }
        }} />
      <Group justify="space-between" mb="sm">
        <Group gap="sm">
          <ActionIcon size={36} variant="filled" onClick={() => (audio.current?.paused ? audio.current.play() : audio.current?.pause())} aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? <IconPlayerPauseFilled size={18} /> : <IconPlayerPlayFilled size={18} />}
          </ActionIcon>
          <Tooltip label="Back 5 s">
            <ActionIcon size={30} variant="default" onClick={() => audio.current && (audio.current.currentTime = Math.max(0, audio.current.currentTime - 5))} aria-label="Back 5 seconds">
              <IconRewindBackward5 size={16} />
            </ActionIcon>
          </Tooltip>
          <Text size="md" className="vs-num vs-mono">{fmt(t)} <Text span c="gray.7">/ {fmt(total)}</Text></Text>
          <SegmentedControl value={String(speed)} aria-label="Playback speed"
            onChange={(v) => { setSpeed(Number(v)); if (audio.current) audio.current.playbackRate = Number(v) }}
            data={SPEEDS.map((s) => ({ value: String(s), label: `${s}×` }))} />
          {now && <Text size="xs" c="gray.7">Now: <span className="vs-mono">{indexed(now)}</span></Text>}
        </Group>
        <Group gap="md">
          <Legend color="#5c636d" label="Respondent · left channel" />
          <Legend color="#1f4fa3" label="Agent · right channel" />
          <Legend color="#b06f00" label="Flagged answer" thin />
        </Group>
      </Group>

      <Box style={{ display: 'grid', gridTemplateColumns: '90px 1fr', rowGap: 6, alignItems: 'center' }}>
        <span />
        <Box pos="relative" h={14}>
          {ticks.map((x) => <Text key={x} pos="absolute" fz={10} c="gray.7" className="vs-mono" style={{ left: pct(x), transform: 'translateX(-50%)' }}>{fmt(x)}</Text>)}
        </Box>
        {(['respondent', 'agent'] as const).map((sp) => (
          <Lane key={sp} label={sp === 'agent' ? 'Agent' : 'Respondent'} onClick={click} playhead={pct(t)}>
            {segs.filter((s) => s.speaker === sp).map((s) => (
              <span key={s.id} style={{ left: pct(s.t), width: `calc(${pct(s.end - s.t)} - 1px)`, background: sp === 'agent' ? '#1f4fa3' : '#5c636d' }} />
            ))}
          </Lane>
        ))}
        <Lane label="Answers" onClick={click} playhead={pct(t)}>
          {i.answers.filter((a) => a.t_question != null).map((a) => (
            <span key={a.id} title={indexed(a)} style={{ left: pct(a.t_question!), width: 2, background: needsReview(a) ? '#b06f00' : '#8a919a' }} />
          ))}
        </Lane>
      </Box>
      <Text size="xs" c="gray.7" mt="sm">
        Stereo recording: respondent left, agent right. Click any lane or an "asked at" time to jump. Space play/pause · ←/→ 5 s.
      </Text>
    </Paper>
  )
}

function Lane({ label, children, onClick, playhead }: { label: string; children: React.ReactNode; onClick: (e: React.MouseEvent<HTMLDivElement>) => void; playhead: string }) {
  return (
    <>
      <Text size="xs" fw={500} c="gray.8">{label}</Text>
      <div className="vs-lane" onClick={onClick} role="presentation">
        {children}
        <Box pos="absolute" top={-4} bottom={-4} w={2} bg="#121417" style={{ left: playhead, pointerEvents: 'none' }} />
      </div>
    </>
  )
}

function Legend({ color, label, thin }: { color: string; label: string; thin?: boolean }) {
  return (
    <Group gap={6} wrap="nowrap">
      <Box w={thin ? 2 : 12} h={10} bg={color} style={{ borderRadius: 1 }} />
      <Text size="xs" c="gray.8">{label}</Text>
    </Group>
  )
}
