import { Button, Group, Select, Slider, Stack, Table, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { IconAlertTriangle, IconCircleCheck } from '@tabler/icons-react'

import { ApiError, type VoiceChoice, voiceApi, voiceSettingsApi, type VoiceStatus } from '../api'
import ListenButton from '../components/Listen'
import { ToneBadge } from '../components/badges'
import { ErrorNotice, PageBody, PageHeader, Panel, SkeletonRows } from '../components/layout'
import { useProjectId } from '../hooks'
import { ThresholdsEditor } from './Report'
import { LANG_CODES, type LangCode, langAttr, langLabel } from '../languages'

type Service = { name: string; what: string; ok: (s: VoiceStatus) => boolean; keys: string[]; detail?: (s: VoiceStatus) => string }

const SERVICES: Service[] = [
  { name: 'Speech', what: 'Gnani Prisma (speech-to-text) and Timbre (text-to-speech)', ok: (s) => s.gnani, keys: ['gnani_api_key'] },
  { name: 'LLM', what: 'Turns spoken answers into values', ok: (s) => s.llm, keys: ['llm_api_key'],
    detail: (s) => `${s.llm_provider}${s.llm_fallback ? ` · fallback ${s.llm_fallback}` : ''}` },
  { name: 'Telephony', what: 'Twilio — places the phone calls', ok: (s) => s.twilio, keys: ['twilio_account_sid', 'twilio_auth_token', 'twilio_from_number'],
    detail: (s) => (s.exotel ? 'Exotel also configured' : '') },
  { name: 'Public URL', what: 'Tunnel the telephony provider calls back on (ngrok)', ok: (s) => !isMissing(s, 'public_base_url'), keys: ['public_base_url'],
    detail: (s) => s.public_base_url },
]

const isMissing = (s: VoiceStatus, key: string) => s.missing.some((m) => m.toLowerCase() === key)

export default function Settings() {
  const projectId = useProjectId()
  const status = useQuery({ queryKey: ['voice-status'], queryFn: voiceApi.status })
  const s = status.data

  return (
    <>
      <PageHeader title="Settings" subtitle="Connections, phone-check thresholds and agent voices for this project." />
      <PageBody maw={1200}>
        <Panel title="Connections" meta="Keys live in apps/api/.env; restart the API after changing them." p={0}>
          {status.isLoading && <SkeletonRows rows={4} />}
          {status.isError && <ErrorNotice title="Couldn't reach the API" detail={(status.error as Error).message} />}
          {s && (
            <Table>
              <Table.Thead><Table.Tr><Table.Th w={140}>Service</Table.Th><Table.Th>Used for</Table.Th><Table.Th w={110}>Status</Table.Th><Table.Th>Details</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>
                {SERVICES.map((svc) => {
                  const ok = svc.ok(s)
                  const missing = svc.keys.filter((k) => isMissing(s, k))
                  return (
                    <Table.Tr key={svc.name}>
                      <Table.Td><Text size="sm" fw={600}>{svc.name}</Text></Table.Td>
                      <Table.Td><Text size="sm" c="gray.8">{svc.what}</Text></Table.Td>
                      <Table.Td>{ok ? <ToneBadge tone="success" icon={IconCircleCheck}>OK</ToneBadge> : <ToneBadge tone="warning" icon={IconAlertTriangle}>missing</ToneBadge>}</Table.Td>
                      <Table.Td>
                        {ok ? <Text size="sm" c="gray.7" className={svc.name === 'Public URL' ? 'vs-mono' : undefined}>{svc.detail?.(s) || '—'}</Text> : (
                          <Group gap={6}>{(missing.length ? missing : svc.keys).map((k) => <span key={k} className="vs-type">{k.toUpperCase()}</span>)}</Group>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  )
                })}
              </Table.Tbody>
            </Table>
          )}
        </Panel>

        <Stack gap="xs">
          <Text fw={600}>Phone-check thresholds</Text>
          <Text size="sm" c="gray.7">Same values as the report's Thresholds editor. Saving here applies to the next check of each form.</Text>
          {projectId != null && <ThresholdsEditor projectId={projectId} saveLabel="Save thresholds" />}
        </Stack>

        {projectId != null && <Voices projectId={projectId} />}
      </PageBody>
    </>
  )
}

// "How many people live in your household, including you?" in each call language.
const SAMPLE: Record<LangCode, string> = {
  en: 'Hello! How many people live in your household, including you?',
  hi: 'नमस्ते! आपके घर में आपको मिलाकर कितने लोग रहते हैं?',
  bn: 'নমস্কার! আপনাকে নিয়ে আপনার বাড়িতে কতজন থাকেন?',
  gu: 'નમસ્તે! તમારા સહિત તમારા ઘરમાં કેટલા લોકો રહે છે?',
  kn: 'ನಮಸ್ಕಾರ! ನಿಮ್ಮನ್ನೂ ಸೇರಿ ನಿಮ್ಮ ಮನೆಯಲ್ಲಿ ಎಷ್ಟು ಜನ ವಾಸಿಸುತ್ತಾರೆ?',
  ml: 'നമസ്കാരം! നിങ്ങൾ ഉൾപ്പെടെ നിങ്ങളുടെ വീട്ടിൽ എത്ര പേർ താമസിക്കുന്നു?',
  mr: 'नमस्कार! तुमच्यासह तुमच्या घरात किती लोक राहतात?',
  pa: 'ਸਤ ਸ੍ਰੀ ਅਕਾਲ! ਤੁਹਾਡੇ ਸਮੇਤ ਤੁਹਾਡੇ ਘਰ ਵਿੱਚ ਕਿੰਨੇ ਲੋਕ ਰਹਿੰਦੇ ਹਨ?',
  ta: 'வணக்கம்! உங்களையும் சேர்த்து உங்கள் வீட்டில் எத்தனை பேர் வசிக்கிறார்கள்?',
  te: 'నమస్కారం! మీతో కలిపి మీ ఇంట్లో ఎంత మంది ఉంటారు?',
}

function Voices({ projectId }: { projectId: number }) {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['voice-list'], queryFn: voiceSettingsApi.voices, staleTime: Infinity })
  const saved = useQuery({ queryKey: ['voices', projectId], queryFn: () => voiceSettingsApi.get(projectId) })
  const [edits, setEdits] = useState<Partial<Record<LangCode, VoiceChoice>>>({})
  const save = useMutation({
    mutationFn: () => voiceSettingsApi.save(projectId, { ...saved.data, ...edits }),
    onSuccess: () => { setEdits({}); qc.invalidateQueries({ queryKey: ['voices', projectId] }); notifications.show({ color: 'green', message: 'Voices saved; new calls use them.' }) },
  })
  const value = (l: LangCode) => edits[l] ?? saved.data?.[l]
  return (
    <Panel title="Agent voices" meta={list.data ? `Gnani Timbre ${list.data.model} · ${list.data.voices.length} voices` : undefined} p={0}>
      {saved.isLoading ? <SkeletonRows rows={2} /> : (
        <Table>
          <Table.Tbody>
            {LANG_CODES.map((l) => {
              const v = value(l)
              return (
                <Table.Tr key={l}>
                  <Table.Td w={170}><Text fw={600} size="sm" lang={langAttr(l)}>{langLabel(l)}</Text></Table.Td>
                  <Table.Td w={280}>
                    <Select searchable data={list.data?.voices ?? []} value={v?.voice ?? null} aria-label={`Voice for ${l}`}
                      onChange={(voice) => voice && setEdits((e) => ({ ...e, [l]: { speed: v?.speed ?? 1, voice } }))} />
                  </Table.Td>
                  <Table.Td w={120}>{v && <ListenButton text={SAMPLE[l]} lang={l} voice={v.voice} speed={v.speed} size="xs" />}</Table.Td>
                  <Table.Td>
                    <Group gap="sm" wrap="nowrap">
                      <Text size="sm" c="gray.7">Speed</Text>
                      <Slider w={220} min={0.8} max={1.2} step={0.05} value={v?.speed ?? 1} label={(x) => `${x.toFixed(2)}×`} aria-label={`Speed for ${l}`}
                        onChange={(speed) => v && setEdits((e) => ({ ...e, [l]: { ...v, speed } }))} />
                      <Text size="sm" className="vs-mono">{(v?.speed ?? 1).toFixed(2)}×</Text>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              )
            })}
          </Table.Tbody>
        </Table>
      )}
      <Group justify="space-between" p="md" style={{ borderTop: '1px solid var(--vs-line)' }}>
        <Text size="xs" c="gray.7">The same voice reads questions in the editor's Listen button. "Slow down" on a call drops to 0.85×.</Text>
        <Group gap="sm">
          {save.error && <Text size="xs" c="red.6">{(save.error as ApiError).message}</Text>}
          <Button disabled={!Object.keys(edits).length} loading={save.isPending} onClick={() => save.mutate()}>Save voices</Button>
        </Group>
      </Group>
    </Panel>
  )
}
