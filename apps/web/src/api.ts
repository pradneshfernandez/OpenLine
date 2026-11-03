import type { LangCode } from './languages'

export type Lang = string

export interface Message {
  level: 'error' | 'warning'
  sheet: string | null
  row: number | null
  message: string
  original: string
  question?: string
}

export interface PlatformWarning {
  platform: string
  sheet: string | null
  row: number | null
  message: string
}

export interface Summary {
  question_count: number
  note_count: number
  background_count: number
  group_count: number
  repeat_count: number
  choice_list_count: number
  languages: Lang[]
  default_language: Lang
  title: string
  form_id: string
  xform_version?: string | null
}

export interface Version {
  id: number
  form_id: number
  version_no: number
  parent_version: number | null
  created_by: string
  created_at: string
  message: string
  original_filename: string
  has_xform: boolean
  summary: Summary
  languages: Lang[]
  pyxform_warnings?: Message[]
  platform_warnings?: PlatformWarning[]
  excluded_rows?: string[]
  phone_status?: PhoneStatus | null
}

export interface GroupRef {
  name: string
  type: 'group' | 'repeat'
  row: number
}

export interface Question {
  id: number
  position: number
  number: number | null
  row: number
  name: string
  type: string
  raw_type: string
  kind: 'question' | 'note' | 'background' | 'group' | 'repeat' | 'unknown'
  group_path: GroupRef[]
  labels: Record<Lang, string>
  hints: Record<Lang, string>
  choice_list: string | null
  required: boolean
  required_raw: string
  constraint: string
  constraint_message: Record<Lang, string>
  relevant: string
  relevant_plain: string
  calculation: string
  repeat_count: string
  default: string
  appearance: string
  media: Record<string, Record<string, string>>
  extra: Record<string, string>
  read_aloud: boolean
  hint_read_aloud: boolean
  not_used_by_phone: boolean
}

export interface Choice {
  row: number
  name: string
  labels: Record<Lang, string>
  media: Record<string, Record<string, string>>
}

export type PhoneStatus = 'ready' | 'ready_with_warnings' | 'not_ready'
export type Severity = 'blocker' | 'warning' | 'info'

export interface Issue {
  id: number
  report_id: number
  question_name: string | null
  check_code: string
  check_title: string
  severity: Severity
  message: string
  suggestion: string
  state: 'open' | 'fixed' | 'accepted'
  accepted_reason: string
}

export interface Report {
  id: number
  version_id: number
  run_at: string
  status: PhoneStatus
  estimated_minutes: number
  thresholds: Thresholds
  counts: Record<Severity, number>
  issues: Issue[]
}

export interface Thresholds {
  max_words: number
  max_options: number
  max_call_minutes: number
  words_per_minute: number
  seconds_per_answer: number
  dont_know_refuse_codes: string[]
  disabled_checks: string[]
}

export interface VersionDetail extends Version {
  form: { id: number; title: string; form_id: string; default_language: string | null; project_id: number }
  is_latest: boolean
  questions: Question[]
  choice_lists: Record<string, Choice[]>
  report: Report | null
}

export interface FormRow {
  id: number
  title: string
  form_id: string
  created_at: string
  latest_version: Version | null
  phone_status: PhoneStatus | null
  estimated_minutes: number | null
  version_count: number
}

export interface FormDetail {
  id: number
  project_id: number
  title: string
  form_id: string
  default_language: string | null
  latest_version_id: number | null
  versions: Version[]
}

export interface UploadResult {
  ok: boolean
  form: { id: number; title: string; form_id: string }
  original_version_id: number
  version: Version | null
  report: Report | null
  errors: Message[]
  warnings: Message[]
  platform_warnings: PlatformWarning[]
  platform_rows: { row: number; name: string; type: string; platform: string }[]
}

export interface Change {
  target: 'question' | 'choice'
  question_name?: string
  list_name?: string
  choice_name?: string
  field: string
  lang?: string | null
  value: string | boolean
}

export interface DiffRow {
  section: 'questions' | 'choices'
  subject: string
  field: string
  change: string
  old: string | null
  new: string | null
}

export interface EditLogEntry {
  id: number
  version_id: number
  question_name: string | null
  field: string
  old_value: string | null
  new_value: string | null
  user: string
  time: string
}

export class ApiError extends Error {
  status: number
  errors: Message[]
  constructor(status: number, message: string, errors: Message[] = []) {
    super(message)
    this.status = status
    this.errors = errors
  }
}

export function currentUser(): string {
  try {
    return localStorage.getItem('forms.user') || ''
  } catch {
    return ''
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const user = currentUser()
  if (user) headers.set('X-User', user)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const res = await fetch(`/api${path}`, { ...init, headers })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      detail = (await res.json()).detail
    } catch {
      /* not JSON */
    }
    if (detail && typeof detail === 'object' && 'message' in detail) {
      const d = detail as { message: string; errors?: Message[] }
      throw new ApiError(res.status, d.message, d.errors ?? [])
    }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json() as Promise<T>
}

export const api = {
  projects: () => request<{ id: number; name: string }[]>('/projects'),
  forms: (projectId: number) => request<FormRow[]>(`/projects/${projectId}/forms`),
  form: (formId: number) => request<FormDetail>(`/forms/${formId}`),
  deleteForm: (formId: number) => request<{ ok: boolean }>(`/forms/${formId}`, { method: 'DELETE' }),
  upload: (projectId: number, file: File, formId?: number) => {
    const body = new FormData()
    body.append('file', file)
    const path = formId ? `/forms/${formId}/upload` : `/projects/${projectId}/forms/upload`
    return request<UploadResult>(path, { method: 'POST', body })
  },
  convert: (formId: number) =>
    request<UploadResult>(`/forms/${formId}/convert`, {
      method: 'POST',
      body: JSON.stringify({ exclude_platform_rows: true }),
    }),
  version: (versionId: number) => request<VersionDetail>(`/versions/${versionId}`),
  versionByNo: (formId: number, versionNo: number) => request<VersionDetail>(`/forms/${formId}/versions/${versionNo}`),
  saveEdits: (versionId: number, message: string, changes: Change[]) =>
    request<{ version: Version; report: Report }>(`/versions/${versionId}/edits`, {
      method: 'POST',
      body: JSON.stringify({ message, changes }),
    }),
  rerunCheck: (versionId: number) => request<Report>(`/versions/${versionId}/phone-check`, { method: 'POST' }),
  acceptIssue: (issueId: number, reason: string) =>
    request<Issue>(`/issues/${issueId}/accept`, { method: 'POST', body: JSON.stringify({ reason }) }),
  reopenIssue: (issueId: number) => request<Issue>(`/issues/${issueId}/reopen`, { method: 'POST' }),
  diff: (a: number, b: number) =>
    request<{ changes: DiffRow[]; xform_a: string; xform_b: string; a: Version; b: Version }>(
      `/versions/diff?a=${a}&b=${b}`,
    ),
  formEditLog: (formId: number) => request<EditLogEntry[]>(`/forms/${formId}/edit-log`),
  settings: (projectId: number) =>
    request<{ thresholds: Thresholds; checks: { code: string; title: string }[] }>(`/projects/${projectId}/settings`),
  saveSettings: (projectId: number, values: Partial<Thresholds>) =>
    request<{ thresholds: Thresholds }>(`/projects/${projectId}/settings`, {
      method: 'PUT',
      body: JSON.stringify(values),
    }),
}

/** UI path of a version, addressed as the user sees it: form + "v1" (not the database id). */
export const versionPath = (v: { form_id: number; version_no: number }, sub: '' | '/report' = '') =>
  `/forms/${v.form_id}/versions/${v.version_no}${sub}`

export const downloadUrl = (versionId: number, kind: 'original' | 'xlsx' | 'xform') =>
  `/api/versions/${versionId}/download?kind=${kind}`

// ---------------------------------------------------------------------------
// Stage 2: interviews

export interface InterviewRow {
  id: number
  form_version_id: number
  version_no?: number
  language: string
  participant_label: string
  channel: string
  call_sid: string | null
  status: string
  twilio_status: string
  callback_when: string
  created_by: string
  created_at: string
  started_at: string | null
  ended_at: string | null
  has_recording: boolean
  error: string
  review_state?: 'pending' | 'approved' | 'rejected'
  review_reason?: string
  persona?: string
  simulation_run_id?: number | null
  campaign_id?: number | null
  kobo_state?: KoboState
  answer_count?: number
  flagged_count?: number
  avg_latency_ms?: number | null
  /** Set when this call continued an earlier partial call to the same respondent. */
  resumed_from_id?: number | null
  transcript_state?: 'none' | 'running' | 'done' | 'failed'
}

export interface AnswerRow {
  id: number
  question_name: string
  repeat_index: number[]
  value: string | null
  code: string | null
  heard_text: string
  confidence: number | null
  confirmed: boolean
  corrected: boolean
  attempts: number
  still_relevant: boolean
  t_question: number | null
  t_answer_start: number | null
  t_answer_end: number | null
  second_pass_text: string | null
  second_pass_value: string | null
  /** Second pass disagrees with the live value. */
  flagged: boolean
  review_state: ReviewState
  reviewed_value: string | null
  review_reason: string
  labels: Record<string, string>
}

export interface TurnRow {
  id: number
  t: number
  speaker: 'agent' | 'respondent' | 'system'
  text: string
  node_name: string
  latency_ms: number | null
}

export interface InterviewDetail extends InterviewRow {
  form: { id: number; title: string; version_no: number }
  final_answers: Record<string, unknown>
  answers: AnswerRow[]
  turns: TurnRow[]
  /** Full-call transcript from Gnani Prisma Batch, one segment per stretch of speech. */
  transcript: TranscriptSegment[]
  transcript_error: string
}

export interface TranscriptSegment {
  start: number
  end: number
  speaker: 'agent' | 'respondent' | 'call'
  text: string
  language: string | null
}

export interface VoiceStatus {
  gnani: boolean
  llm: boolean
  llm_provider: string
  twilio: boolean
  llm_fallback: string | null
  exotel: boolean
  public_base_url: string
  missing: string[]
}

export const voiceApi = {
  status: () => request<VoiceStatus>('/voice/status'),
  interviews: (formId: number) => request<InterviewRow[]>(`/forms/${formId}/interviews`),
  interview: (id: number) => request<InterviewDetail>(`/interviews/${id}`),
  transcribe: (id: number) =>
    request<{ status: string; segments?: number; error?: string }>(`/interviews/${id}/transcript`, { method: 'POST' }),
  call: (body: { to: string; form_version_id: number; language: LangCode; participant_label: string }) =>
    request<{ interview_id: number; call_sid: string; status: string }>('/calls', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}

export const recordingUrl = (id: number) => `/api/interviews/${id}/recording`
export const csvUrl = (formId: number) => `/api/forms/${formId}/interviews.csv`

// ---------------------------------------------------------------------------
// Review

export type ReviewState = 'pending' | 'approved' | 'rejected' | 'edited'
export type KoboState = 'not_sent' | 'sent' | 'failed'

export interface ReviewAnswer {
  id: number
  question_name: string
  key: string
  value: string | null
  code: string | null
  heard_text: string
  confidence: number | null
  attempts: number
  corrected: boolean
  confirmed: boolean
  flagged: boolean
  second_pass_text: string | null
  second_pass_value: string | null
  t_question: number | null
  t_answer_start: number | null
  t_answer_end: number | null
  flags: ('low_confidence' | 'mismatch' | 'unclear' | 'attempts' | 'corrected')[]
  review_state: ReviewState
  reviewed_value: string | null
  review_reason: string
  labels: Record<string, string>
}

export interface ReviewGroup {
  interview: {
    id: number; participant_label: string; language: string; version_no: number; form_id: number; form_title: string
    has_recording: boolean; started_at: string; status: string; review_state: string; pending: number
  }
  answers: ReviewAnswer[]
}

export interface ReviewLogEntry {
  id: number; interview_id: number; answer_id: number | null; action: string; subject: string
  old_value: string | null; new_value: string | null; reason: string; user: string; time: string
}

export const reviewApi = {
  queue: (projectId: number, params: Record<string, string | number | undefined>) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '').map(([k, v]) => [k, String(v)]))
    return request<{ counts: Record<ReviewState, number>; groups: ReviewGroup[]; questions: string[]; forms: { id: number; title: string }[] }>(
      `/projects/${projectId}/review?${q}`)
  },
  count: (projectId: number) => request<{ pending: number }>(`/projects/${projectId}/review/count`),
  log: (projectId: number) => request<ReviewLogEntry[]>(`/projects/${projectId}/review/log`),
  answer: (answerId: number, body: { action: 'approve' | 'reject' | 'edit' | 'reset'; value?: string; reason?: string }) =>
    request<ReviewAnswer>(`/answers/${answerId}/review`, { method: 'POST', body: JSON.stringify(body) }),
  interview: (interviewId: number, body: { action: 'approve' | 'reject' | 'reset'; reason?: string }) =>
    request<{ id: number; review_state: string; approved_answers: number }>(`/interviews/${interviewId}/review`, {
      method: 'POST', body: JSON.stringify(body),
    }),
}

// ---------------------------------------------------------------------------
// Campaigns

export interface CampaignSettings {
  calling_start: string; calling_end: string; max_attempts: number; min_gap_minutes: number; concurrency: number; timezone: string
}

export interface CampaignRow {
  id: number; name: string; status: 'draft' | 'running' | 'paused' | 'finished'; settings: CampaignSettings
  form: { id: number; title: string; version_id: number; version_no: number }
  total: number; completed: number; done: number; calling: number; outcomes: Record<string, number>
  csv_filename: string; left_out: number; created_by: string; created_at: string; started_at: string | null; finished_at: string | null
}

export interface RespondentRow {
  id: number; respondent_id: string; phone: string; language: string; state: 'waiting' | 'calling' | 'done' | 'stopped'
  attempts: number; last_outcome: string; next_attempt_at: string | null; callback_when: string; interview_ids: number[]
}

export interface CampaignDetail extends CampaignRow {
  in_window: boolean
  in_progress: { interview_id: number; status: string; respondent_id: string; phone: string; language: string; started_at: string }[]
  upcoming: RespondentRow[]
  respondents: RespondentRow[]
  rejected_rows: CsvProblem[]
}

export interface CsvProblem { row: number; respondent_id: string; phone: string; language: string; problem: string | null; kind?: string }

export interface CsvCheck {
  filename: string
  counts: { ok: number; invalid_number: number; duplicate: number; unknown_language: number }
  languages: Partial<Record<LangCode, number>>
  preview: CsvProblem[]
  problems: CsvProblem[]
}

export const campaignApi = {
  list: (projectId: number) => request<CampaignRow[]>(`/projects/${projectId}/campaigns`),
  get: (id: number) => request<CampaignDetail>(`/campaigns/${id}`),
  validate: (projectId: number, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<CsvCheck>(`/projects/${projectId}/campaigns/validate`, { method: 'POST', body })
  },
  create: (projectId: number, v: { name: string; form_version_id: number; settings: CampaignSettings; start: boolean; file: File }) => {
    const body = new FormData()
    body.append('file', v.file)
    body.append('name', v.name)
    body.append('form_version_id', String(v.form_version_id))
    body.append('settings', JSON.stringify(v.settings))
    body.append('start', String(v.start))
    return request<CampaignRow>(`/projects/${projectId}/campaigns`, { method: 'POST', body })
  },
  remove: (id: number) => request<{ ok: boolean }>(`/campaigns/${id}`, { method: 'DELETE' }),
  action: (id: number, action: 'start' | 'pause' | 'resume' | 'finish') =>
    request<CampaignRow>(`/campaigns/${id}/action`, { method: 'POST', body: JSON.stringify({ action }) }),
}
export const problemsCsvUrl = (id: number) => `/api/campaigns/${id}/problems.csv`

// ---------------------------------------------------------------------------
// Simulations

export type Persona = 'cooperative' | 'vague' | 'correcting' | 'mixed' | 'dont_know'
export type Noise = 'clean' | '15db' | '5db'
export interface Ratio { correct: number; total: number; rate?: number | null }

export interface SimulationRow {
  id: number; status: 'queued' | 'running' | 'finished' | 'failed'; error: string
  settings: { runs: number; personas: Persona[]; languages: string[]; parallel: number; noise?: Noise[] }
  form: { id: number; title: string; version_id: number; version_no: number }
  created_by: string; created_at: string; finished_at: string | null
  runs: number; finished: number; accuracy: Ratio; completion_rate: number | null
}

export interface SimulationReport {
  runs: number; finished: number; completed: number; completion_rate: number | null; accuracy: Ratio
  reasks: number; reasks_per_call: number | null; seconds_per_question: number | null
  grid: ({ question: string; all: Ratio } & Partial<Record<LangCode, Ratio>>)[]
  by_noise: { noise: Noise; correct: number; total: number }[]
  by_persona: { persona: Persona; correct: number; total: number }[]
  reply_delay: { avg: number; p90: number; turns: number } | null
  misses: { interview_id: number; key: string; question: string; persona: Persona; language: string; heard: string; expected: string; got: unknown }[]
  interviews: { id: number; persona: Persona; language: string; status: string; correct: number; total: number; error: string }[]
}

export const simulationApi = {
  list: (projectId: number) => request<SimulationRow[]>(`/projects/${projectId}/simulations`),
  get: (id: number) => request<SimulationRow & { report: SimulationReport }>(`/simulations/${id}`),
  start: (projectId: number, body: { form_version_id: number; runs: number; personas: Persona[]; languages: string[]; parallel: number; noise: Noise[] }) =>
    request<SimulationRow>(`/projects/${projectId}/simulations`, { method: 'POST', body: JSON.stringify(body) }),
  preview: (versionId: number, lang: string, persona: Persona) =>
    request<{ answers: Record<string, string>; script: { name: string; key: string | null; value: string; utterance: string }[] }>(
      `/form-versions/${versionId}/answer-key?lang=${lang}&persona=${persona}`),
}

// ---------------------------------------------------------------------------
// KoboToolbox

export interface KoboConn { connected: boolean; server_url: string; token_masked: string; asset_uid: string; asset_name: string; kc_url: string }
export interface KoboAsset { uid: string; name: string; deployed: boolean; submissions: number | null }
export interface KoboRow {
  id: number; participant_label: string; language: string; form_id: number; form_title: string; version_no: number
  status: string; review_state: string; answers: number; started_at: string; kobo_state: KoboState; kobo_error: string; kobo_sent_at: string | null
}

export const koboApi = {
  get: (projectId: number) => request<KoboConn>(`/projects/${projectId}/kobo`),
  connect: (projectId: number, server_url: string, token?: string) =>
    request<KoboConn & { assets: KoboAsset[] }>(`/projects/${projectId}/kobo`, { method: 'PUT', body: JSON.stringify({ server_url, token }) }),
  disconnect: (projectId: number) => request<KoboConn>(`/projects/${projectId}/kobo`, { method: 'DELETE' }),
  assets: (projectId: number) => request<KoboAsset[]>(`/projects/${projectId}/kobo/assets`),
  pick: (projectId: number, asset_uid: string) =>
    request<KoboConn>(`/projects/${projectId}/kobo/asset`, { method: 'PUT', body: JSON.stringify({ asset_uid }) }),
  interviews: (projectId: number) => request<KoboRow[]>(`/projects/${projectId}/kobo/interviews`),
  send: (interviewId: number) => request<KoboRow>(`/interviews/${interviewId}/kobo`, { method: 'POST' }),
  sendAll: (projectId: number, include_sent = false) =>
    request<{ sent: number; failed: number }>(`/projects/${projectId}/kobo/send`, { method: 'POST', body: JSON.stringify({ include_sent }) }),
}

// ---------------------------------------------------------------------------
// Voices + Listen

export type VoiceChoice = { voice: string; speed: number }

export const voiceSettingsApi = {
  voices: () => request<{ model: string; voices: string[] }>('/voices'),
  get: (projectId: number) => request<Record<LangCode, VoiceChoice>>(`/projects/${projectId}/voices`),
  save: (projectId: number, body: Partial<Record<LangCode, VoiceChoice>>) =>
    request<Record<LangCode, VoiceChoice>>(`/projects/${projectId}/voices`, { method: 'PUT', body: JSON.stringify(body) }),
}

/** WAV of `text` in the agent's voice (Gnani Timbre). */
export async function speak(body: { text: string; lang: string; voice?: string; speed?: number; project_id?: number }): Promise<Blob> {
  const res = await fetch('/api/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail } catch { /* not JSON */ }
    throw new ApiError(res.status, detail)
  }
  return res.blob()
}
