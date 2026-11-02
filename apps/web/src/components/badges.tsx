import { Box, Group, Text, Tooltip } from '@mantine/core'
import {
  IconAlertCircle,
  IconAlertOctagon,
  IconAlertTriangle,
  IconArrowBackUp,
  IconArrowsDiff,
  IconBan,
  IconCalendarTime,
  IconCheck,
  IconCircleCheck,
  IconCircleDot,
  IconCircleHalf2,
  IconCircleOff,
  IconCircleX,
  IconCloudCheck,
  IconCloudX,
  IconClock,
  IconDatabase,
  IconFileX,
  IconFolder,
  IconGauge,
  IconHandStop,
  IconInfoCircle,
  IconMessage2,
  IconMessageCheck,
  IconNotes,
  IconPhone,
  IconPhoneCalling,
  IconPhoneOff,
  IconPencil,
  IconPhoneX,
  IconPlayerPauseFilled,
  IconPlayerPlayFilled,
  IconPointFilled,
  IconQuestionMark,
  IconRepeat,
  IconRobot,
  IconWorld,
  type Icon,
} from '@tabler/icons-react'
import type { ReactNode } from 'react'

import type { Issue, PhoneStatus, Question, Severity } from '../api'
import { tone } from '../theme'

export type Tone = keyof typeof tone | 'live'

const TONES: Record<Tone, { fg: string; bg: string; bd: string; ic: string }> = {
  ...tone,
  live: { fg: '#ffffff', bg: '#1f4fa3', bd: '#1f4fa3', ic: '#ffffff' },
}

/** Square-cornered status badge: icon + word + tone (never colour alone). */
export function ToneBadge({ tone: t, icon: I, children, title, size = 'md' }: {
  tone: Tone; icon?: Icon; children: ReactNode; title?: string; size?: 'sm' | 'md'
}) {
  const c = TONES[t]
  const badge = (
    <Box component="span" style={{
      display: 'inline-flex', alignItems: 'center', gap: 4, height: size === 'sm' ? 20 : 22, padding: '0 6px',
      border: `1px solid ${c.bd}`, background: c.bg, color: c.fg, borderRadius: 3, whiteSpace: 'nowrap',
      fontSize: size === 'sm' ? 11 : 12, fontWeight: 500, lineHeight: 1, verticalAlign: 'middle',
    }}>
      {I && <I size={size === 'sm' ? 12 : 14} stroke={2} color={c.ic} className={t === 'live' ? 'vs-pulse' : undefined} />}
      {children}
    </Box>
  )
  return title ? <Tooltip label={title}>{badge}</Tooltip> : badge
}

// ---------------------------------------------------------------------------
// Phone-check status

const STATUS: Record<PhoneStatus | 'not_converted', [string, Icon, Tone]> = {
  ready: ['Ready', IconCircleCheck, 'success'],
  ready_with_warnings: ['Ready with warnings', IconAlertTriangle, 'warning'],
  not_ready: ['Not ready', IconAlertOctagon, 'danger'],
  not_converted: ['Not converted', IconFileX, 'terminal'],
}

export function StatusBadge({ status, suffix }: { status: PhoneStatus | null | undefined; suffix?: string }) {
  const [label, icon, t] = STATUS[status ?? 'not_converted']
  return <ToneBadge tone={t} icon={icon}>{label}{suffix}</ToneBadge>
}

// ---------------------------------------------------------------------------
// Issue severity + state

export const SEVERITIES: Severity[] = ['blocker', 'warning', 'info']
export const SEVERITY_RANK: Record<Severity, number> = { blocker: 3, warning: 2, info: 1 }
export const SEVERITY_TONE: Record<Severity, 'danger' | 'warning' | 'info'> = { blocker: 'danger', warning: 'warning', info: 'info' }
export const SEVERITY_ICON: Record<Severity, Icon> = { blocker: IconAlertOctagon, warning: IconAlertTriangle, info: IconInfoCircle }
export const SEVERITY_LABEL: Record<Severity, string> = { blocker: 'Blocker', warning: 'Warning', info: 'Info' }
export const SEVERITY_HELP: Record<Severity, string> = {
  blocker: "can't be asked as written",
  warning: 'likely trouble',
  info: 'worth a look',
}

export function SeverityIcon({ severity, size = 16 }: { severity: Severity; size?: number }) {
  const I = SEVERITY_ICON[severity]
  return <I size={size} stroke={1.9} color={tone[SEVERITY_TONE[severity]].ic} style={{ flexShrink: 0 }} aria-label={SEVERITY_LABEL[severity]} />
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <ToneBadge tone={SEVERITY_TONE[severity]} icon={SEVERITY_ICON[severity]}>{SEVERITY_LABEL[severity]}</ToneBadge>
}

export function IssueStateBadge({ state }: { state: Issue['state'] }) {
  if (state === 'accepted') return <ToneBadge tone="brand" icon={IconMessageCheck}>Accepted</ToneBadge>
  if (state === 'fixed') return <ToneBadge tone="success" icon={IconCheck}>Fixed</ToneBadge>
  return <ToneBadge tone="neutral" icon={IconCircleDot}>Open</ToneBadge>
}

/** "⊘2 △3 ⓘ1" — open issue counts per severity, each its own tone chip. */
export function IssueCounts({ counts }: { counts: Record<Severity, number> }) {
  return (
    <Group gap={4} wrap="nowrap">
      {SEVERITIES.filter((s) => counts[s]).map((s) => (
        <ToneBadge key={s} tone={SEVERITY_TONE[s]} icon={SEVERITY_ICON[s]} title={`${counts[s]} open ${SEVERITY_LABEL[s].toLowerCase()}${counts[s] > 1 ? 's' : ''}`}>
          <span className="vs-num">{counts[s]}</span>
        </ToneBadge>
      ))}
    </Group>
  )
}

export function SeverityLegend() {
  return (
    <Group gap="md" wrap="wrap">
      {SEVERITIES.map((s) => (
        <Group key={s} gap={4} wrap="nowrap">
          <SeverityIcon severity={s} size={14} />
          <Text size="xs" c="gray.8">{SEVERITY_LABEL[s]} — {SEVERITY_HELP[s]}</Text>
        </Group>
      ))}
    </Group>
  )
}

// ---------------------------------------------------------------------------
// Interview / call status (API uses hyphens: in-progress, no-answer, opted-out)

const CALL: Record<string, [Icon, Tone, string?]> = {
  queued: [IconClock, 'neutral'],
  ringing: [IconPhoneCalling, 'brand'],
  'in-progress': [IconPointFilled, 'live'],
  completed: [IconCircleCheck, 'success'],
  partial: [IconCircleHalf2, 'warning', 'Ended early or crashed'],
  refused: [IconHandStop, 'danger', 'Never called again'],
  callback: [IconCalendarTime, 'info'],
  'no-answer': [IconPhoneOff, 'neutral'],
  busy: [IconPhoneX, 'neutral'],
  failed: [IconAlertCircle, 'danger', 'Technical failure'],
  'opted-out': [IconBan, 'terminal', 'Never called again'],
}

export const LIVE_STATUSES = ['queued', 'ringing', 'in-progress']

export function InterviewStatusBadge({ status }: { status: string }) {
  const [icon, t, title] = CALL[status] ?? [IconCircleDot, 'neutral' as Tone]
  return <ToneBadge tone={t} icon={icon} title={title}>{status.replace(/-/g, ' ')}</ToneBadge>
}

const CHANNEL: Record<string, Icon> = { phone: IconPhone, browser: IconWorld, simulated: IconRobot }

export function ChannelBadge({ channel }: { channel: string }) {
  return <ToneBadge tone="neutral" icon={CHANNEL[channel] ?? IconPhone} size="sm">{channel}</ToneBadge>
}

// ---------------------------------------------------------------------------
// Answer flags

export const FLAGS = {
  confirmed: ['confirmed', IconCheck, 'success'],
  corrected: ['corrected by respondent', IconArrowBackUp, 'info'],
  low_confidence: ['low confidence', IconGauge, 'warning'],
  mismatch: ['second-pass mismatch', IconArrowsDiff, 'warning'],
  unclear: ['unclear after 3 tries', IconAlertTriangle, 'warning'],
  attempts: ['more than 2 attempts', IconRepeat, 'warning'],
  not_used: ['not used', IconCircleOff, 'neutral'],
  dk: ['dk', IconQuestionMark, 'neutral'],
  refused: ['refused', IconHandStop, 'neutral'],
} as const satisfies Record<string, [string, Icon, Tone]>

export type FlagKey = keyof typeof FLAGS

export function FlagBadge({ flag, title }: { flag: FlagKey; title?: string }) {
  const [label, icon, t] = FLAGS[flag]
  return <ToneBadge tone={t} icon={icon} size="sm" title={title}>{label}</ToneBadge>
}

// ---------------------------------------------------------------------------
// Question kinds

const KIND: Record<Question['kind'], [Icon, string]> = {
  question: [IconMessage2, 'Question — asked aloud, expects an answer'],
  note: [IconNotes, 'Note — read out, no answer'],
  background: [IconDatabase, 'Background field — recorded automatically, not spoken'],
  group: [IconFolder, 'Group'],
  repeat: [IconRepeat, 'Repeat — asked once per item'],
  unknown: [IconMessage2, 'Row'],
}

export function KindIcon({ kind, size = 15 }: { kind: Question['kind']; size?: number }) {
  const [I, label] = KIND[kind] ?? KIND.unknown
  return (
    <Tooltip label={label}>
      <I size={size} stroke={1.7} color="#424851" style={{ flexShrink: 0 }} aria-label={label} />
    </Tooltip>
  )
}

export function TypeLabel({ children }: { children: ReactNode }) {
  return <span className="vs-type">{children}</span>
}

// ---------------------------------------------------------------------------
// Review, campaign and export states

const REVIEW: Record<string, [Icon, Tone]> = {
  pending: [IconClock, 'neutral'], approved: [IconCircleCheck, 'success'],
  rejected: [IconCircleX, 'danger'], edited: [IconPencil, 'info'],
}

export function ReviewStateBadge({ state, title }: { state: string; title?: string }) {
  const [icon, t] = REVIEW[state] ?? REVIEW.pending
  return <ToneBadge tone={t} icon={icon} title={title}>{state}</ToneBadge>
}

const CAMPAIGN: Record<string, [Icon, Tone]> = {
  draft: [IconPencil, 'neutral'], running: [IconPlayerPlayFilled, 'live'], paused: [IconPlayerPauseFilled, 'warning'],
  finished: [IconCircleCheck, 'success'],
}

export function CampaignStatusBadge({ status }: { status: string }) {
  const [icon, t] = CAMPAIGN[status] ?? CAMPAIGN.draft
  return <ToneBadge tone={t} icon={icon}>{status}</ToneBadge>
}

const KOBO: Record<string, [Icon, Tone, string]> = {
  not_sent: [IconCircleDot, 'neutral', 'not sent'], sent: [IconCloudCheck, 'success', 'sent'], failed: [IconCloudX, 'danger', 'failed'],
}

export function KoboStateBadge({ state, title }: { state: string; title?: string }) {
  const [icon, t, label] = KOBO[state] ?? KOBO.not_sent
  return <ToneBadge tone={t} icon={icon} title={title}>{label}</ToneBadge>
}

const SIM: Record<string, [Icon, Tone]> = {
  queued: [IconClock, 'neutral'], running: [IconPointFilled, 'live'], finished: [IconCircleCheck, 'success'], failed: [IconAlertCircle, 'danger'],
}

export function RunStatusBadge({ status }: { status: string }) {
  const [icon, t] = SIM[status] ?? SIM.queued
  return <ToneBadge tone={t} icon={icon}>{status}</ToneBadge>
}

export function PersonaBadge({ persona }: { persona: string }) {
  return <ToneBadge tone="neutral" icon={IconRobot} size="sm">{persona}</ToneBadge>
}
