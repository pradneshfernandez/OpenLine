import { Anchor, Box, Button, Group, Paper, PasswordInput, Select, Stack, Table, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { IconPlugConnected, IconPlugConnectedX, IconSend, IconUnlink } from '@tabler/icons-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, type KoboAsset, koboApi } from '../api'
import { KoboStateBadge, ReviewStateBadge, ToneBadge } from '../components/badges'
import { ErrorNotice, fmtDate, PageBody, PageHeader, SkeletonRows } from '../components/layout'
import { useProjectId } from '../hooks'
import { langName } from '../languages'

export default function KoboExport() {
  const projectId = useProjectId()
  const qc = useQueryClient()
  const conn = useQuery({ queryKey: ['kobo', projectId], queryFn: () => koboApi.get(projectId!), enabled: projectId != null })
  const rows = useQuery({ queryKey: ['kobo-rows', projectId], queryFn: () => koboApi.interviews(projectId!), enabled: projectId != null })
  const [assets, setAssets] = useState<KoboAsset[] | null>(null)
  const [server, setServer] = useState<string | null>(null)
  const [token, setToken] = useState('')
  const [changingToken, setChangingToken] = useState(false)
  const c = conn.data
  const serverValue = server ?? (c?.server_url || 'https://kf.kobotoolbox.org')

  const refresh = () => { qc.invalidateQueries({ queryKey: ['kobo'] }); qc.invalidateQueries({ queryKey: ['kobo-rows'] }) }
  const connect = useMutation({
    mutationFn: () => koboApi.connect(projectId!, serverValue, token || undefined),
    onSuccess: (r) => { setAssets(r.assets); setToken(''); setChangingToken(false); refresh() },
  })
  const listAssets = useQuery({ queryKey: ['kobo-assets', projectId], queryFn: () => koboApi.assets(projectId!), enabled: !!c?.connected && !assets })
  const pick = useMutation({ mutationFn: (uid: string) => koboApi.pick(projectId!, uid), onSuccess: refresh })
  const disconnect = useMutation({ mutationFn: () => koboApi.disconnect(projectId!), onSuccess: () => { setAssets(null); refresh() } })
  const sendAll = useMutation({
    mutationFn: () => koboApi.sendAll(projectId!),
    onSuccess: (r) => { refresh(); notifications.show({ color: r.failed ? 'yellow' : 'green', title: 'Export finished', message: `${r.sent} sent · ${r.failed} failed` }) },
  })
  const sendOne = useMutation({ mutationFn: (id: number) => koboApi.send(id), onSuccess: refresh })

  const list = rows.data ?? []
  const toSend = list.filter((r) => r.kobo_state !== 'sent').length
  const ready = !!(c?.connected && c.asset_uid)
  const assetOptions = (assets ?? listAssets.data ?? []).map((a) => ({ value: a.uid, label: `${a.name}${a.deployed ? '' : ' (not deployed)'}`, disabled: !a.deployed }))
  if (c?.asset_uid && !assetOptions.some((o) => o.value === c.asset_uid)) assetOptions.unshift({ value: c.asset_uid, label: c.asset_name, disabled: false })

  return (
    <>
      <PageHeader title="KoboToolbox export" subtitle="Send approved interviews to your Kobo project as submissions. Reviewed values are sent; originals stay here."
        actions={<Button leftSection={<IconSend size={16} />} disabled={!ready || !toSend} loading={sendAll.isPending} onClick={() => sendAll.mutate()}>
          Send all approved ({toSend})</Button>} />
      <PageBody maw={1400}>
        <Paper bg="white" p="md">
          {conn.isLoading ? <SkeletonRows rows={2} /> : (
            <Group align="flex-end" gap="md" wrap="nowrap">
              <TextInput label="Server URL" w={320} value={serverValue} onChange={(e) => setServer(e.currentTarget.value)}
                styles={{ input: { fontFamily: "'IBM Plex Mono', monospace", fontSize: 13 } }} description="KPI address, e.g. kf.kobotoolbox.org or eu.kobotoolbox.org" />
              {c?.connected && !changingToken ? (
                <Box w={260}>
                  <Text size="xs" fw={600} mb={4}>API token</Text>
                  <Group h={36} px="sm" justify="space-between" bg="#f8f9fa" style={{ border: '1px solid #8a919a', borderRadius: 4 }}>
                    <Text size="sm" className="vs-mono">{c.token_masked}</Text>
                    <Anchor size="xs" component="button" underline="always" onClick={() => setChangingToken(true)}>Change</Anchor>
                  </Group>
                  <Text size="xs" c="gray.7" mt={4}>Stored on the server, never shown again.</Text>
                </Box>
              ) : (
                <PasswordInput label="API token" w={260} value={token} onChange={(e) => setToken(e.currentTarget.value)}
                  description="Kobo › Account settings › Security" autoComplete="off" />
              )}
              {(!c?.connected || changingToken || (server != null && server !== c.server_url)) && (
                <Button leftSection={<IconPlugConnected size={16} />} loading={connect.isPending}
                  disabled={!c?.connected && !token.trim()} onClick={() => connect.mutate()}>Connect</Button>
              )}
              {c?.connected && (
                <>
                  <Select label="Project" w={300} placeholder={listAssets.isLoading ? 'Loading projects…' : 'Pick the Kobo project'} searchable
                    data={assetOptions} value={c.asset_uid || null} onChange={(v) => v && pick.mutate(v)} allowDeselect={false} />
                  <Stack gap={4} mb={6}>
                    <ToneBadge tone="success" icon={IconPlugConnected}>Connected</ToneBadge>
                    <Anchor size="xs" component="button" c="gray.7" onClick={() => disconnect.mutate()}>
                      <Group gap={2}><IconUnlink size={12} />Disconnect</Group></Anchor>
                  </Stack>
                </>
              )}
            </Group>
          )}
          {!c?.connected && conn.isSuccess && (
            <Group gap={6} mt="sm"><IconPlugConnectedX size={14} color="#5c636d" /><Text size="xs" c="gray.7">Not connected. Pick the Kobo project whose form matches this survey; answers are matched by variable name.</Text></Group>
          )}
          {[connect, pick, disconnect, listAssets].map((m, n) => m.error && (
            <Box key={n} mt="sm"><ErrorNotice title="KoboToolbox said no" message={(m.error as ApiError).message} /></Box>
          ))}
        </Paper>

        {sendAll.error && <ErrorNotice title="Couldn't send" message={(sendAll.error as ApiError).message} />}
        <Paper bg="white" style={{ overflow: 'hidden' }}>
          <Table>
            <Table.Thead><Table.Tr><Table.Th>Interview</Table.Th><Table.Th>Participant</Table.Th><Table.Th>Form</Table.Th><Table.Th>Review</Table.Th>
              <Table.Th ta="right">Answers</Table.Th><Table.Th>Send state</Table.Th><Table.Th w={110} /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {list.map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td><Anchor component={Link} to={`/interviews/${r.id}`} className="vs-mono" size="sm" fw={600}>#{String(r.id).padStart(4, '0')}</Anchor>
                    <Text size="xs" c="gray.7">{fmtDate(r.started_at)}</Text></Table.Td>
                  <Table.Td><Text size="sm">{r.participant_label || '—'}</Text><Text size="xs" c="gray.7">{langName(r.language)}</Text></Table.Td>
                  <Table.Td><Text size="sm">{r.form_title} · v{r.version_no}</Text></Table.Td>
                  <Table.Td><ReviewStateBadge state={r.review_state} /></Table.Td>
                  <Table.Td ta="right" className="vs-num">{r.answers}</Table.Td>
                  <Table.Td><KoboStateBadge state={r.kobo_state} />
                    {r.kobo_sent_at && <Text size="xs" c="gray.7">{fmtDate(r.kobo_sent_at)}</Text>}
                    {r.kobo_error && <Text size="xs" c="red.6" lineClamp={2} maw={320}>{r.kobo_error}</Text>}</Table.Td>
                  <Table.Td ta="right">
                    <Button size="compact-sm" variant="default" disabled={!ready} loading={sendOne.isPending && sendOne.variables === r.id}
                      onClick={() => sendOne.mutate(r.id)}>{r.kobo_state === 'not_sent' ? 'Send' : 'Resend'}</Button>
                  </Table.Td>
                </Table.Tr>
              ))}
              {rows.isSuccess && !list.length && (
                <Table.Tr><Table.Td colSpan={7}><Text size="sm" c="gray.7" ta="center" py="lg">
                  No approved interviews yet. Approve interviews on the <Anchor component={Link} to="/review" size="sm">Review</Anchor> page first.
                </Text></Table.Td></Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Paper>
      </PageBody>
    </>
  )
}
