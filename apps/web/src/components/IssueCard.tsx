import { Anchor, Box, Button, Group, Paper, Stack, Text, Textarea } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { IconArrowBackUp, IconMessageCheck } from '@tabler/icons-react'
import { useState } from 'react'

import { api, ApiError, type Issue } from '../api'
import { tone } from '../theme'
import { IssueStateBadge, SEVERITY_LABEL, SEVERITY_TONE, SeverityIcon } from './badges'

/** One phone issue: tone header strip, message, suggested fix, "Accept with reason…" / "Reopen". */
export default function IssueCard({ issue, readOnly }: { issue: Issue; readOnly?: boolean }) {
  const qc = useQueryClient()
  const [accepting, setAccepting] = useState(false)
  const [reason, setReason] = useState('')
  const refresh = () => { qc.invalidateQueries({ queryKey: ['version'] }); qc.invalidateQueries({ queryKey: ['forms'] }) }
  const accept = useMutation({
    mutationFn: () => api.acceptIssue(issue.id, reason),
    onSuccess: () => { setAccepting(false); setReason(''); refresh() },
  })
  const reopen = useMutation({ mutationFn: () => api.reopenIssue(issue.id), onSuccess: refresh })
  const open = issue.state === 'open'
  const t = tone[open ? SEVERITY_TONE[issue.severity] : 'neutral']

  return (
    <Paper bg="white" style={{ borderColor: open ? t.bd : 'var(--vs-line)', overflow: 'hidden' }}>
      <Group justify="space-between" px="sm" py={6} bg={open ? t.bg : '#f8f9fa'} wrap="nowrap"
        style={{ borderBottom: `1px solid ${open ? t.bd : 'var(--vs-line)'}` }}>
        <Group gap={6} wrap="nowrap">
          <SeverityIcon severity={issue.severity} size={15} />
          <Text size="xs" fw={600} c={open ? t.fg : 'gray.8'}>{SEVERITY_LABEL[issue.severity]}</Text>
          <Text size="xs" c={open ? t.fg : 'gray.8'}>·</Text>
          <Text size="xs" fw={500} c={open ? t.fg : 'gray.8'}>{issue.check_title}</Text>
        </Group>
        <IssueStateBadge state={issue.state} />
      </Group>
      <Stack gap={8} p="sm">
        <Text size="sm">{issue.message}</Text>
        {issue.state !== 'fixed' && issue.suggestion && <Text size="sm"><b>Suggested fix:</b> {issue.suggestion}</Text>}
        {issue.state === 'accepted' && (
          <Box p="xs" bg="#eaf0fa" style={{ border: '1px solid #b9cbea', borderRadius: 4 }}>
            <Group gap={6} wrap="nowrap" align="flex-start">
              <IconMessageCheck size={15} color="#1f4fa3" style={{ marginTop: 2, flexShrink: 0 }} />
              <Text size="sm"><b>Accepted:</b> {issue.accepted_reason}</Text>
            </Group>
          </Box>
        )}
        {!readOnly && open && !accepting && (
          <Group><Button size="xs" variant="default" leftSection={<IconMessageCheck size={14} />} onClick={() => setAccepting(true)}>Accept with reason…</Button></Group>
        )}
        {!readOnly && issue.state === 'accepted' && (
          <Anchor size="sm" component="button" onClick={() => reopen.mutate()} style={{ alignSelf: 'flex-start' }}>
            <Group gap={4}><IconArrowBackUp size={14} />Reopen</Group>
          </Anchor>
        )}
        {accepting && (
          <Stack gap={6}>
            <Textarea label="Why is this acceptable?" description="Kept with the issue and shown wherever it appears." minRows={2} autoFocus
              value={reason} onChange={(e) => setReason(e.currentTarget.value)} error={(accept.error as ApiError | null)?.message} />
            <Group gap="xs">
              <Button size="xs" disabled={!reason.trim()} loading={accept.isPending} onClick={() => accept.mutate()}>Accept issue</Button>
              <Button size="xs" variant="default" onClick={() => setAccepting(false)}>Cancel</Button>
            </Group>
          </Stack>
        )}
      </Stack>
    </Paper>
  )
}
