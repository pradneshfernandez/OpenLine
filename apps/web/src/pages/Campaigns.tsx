import { Anchor, Box, Button, Group, Paper, Stack, Table, Text, Title, Tooltip } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { IconPlus } from '@tabler/icons-react'
import { Link } from 'react-router-dom'

import { campaignApi, type CampaignRow } from '../api'
import { CampaignStatusBadge, InterviewStatusBadge } from '../components/badges'
import { ErrorNotice, fmtDate, PageBody, PageHeader, SkeletonRows } from '../components/layout'
import { useProjectId } from '../hooks'

export const OUTCOMES = ['completed', 'partial', 'no-answer', 'busy', 'callback', 'refused', 'opted-out', 'failed']

/** Completed (green) · partial (amber) · other finished (grey) of the total. */
export function CampaignProgress({ c, width = 160 }: { c: Pick<CampaignRow, 'total' | 'done' | 'outcomes'>; width?: number | string }) {
  const pct = (n: number) => `${c.total ? (n / c.total) * 100 : 0}%`
  const completed = c.outcomes.completed ?? 0
  const partial = c.outcomes.partial ?? 0
  const other = Math.max(0, c.done - completed - partial)
  return (
    <Tooltip label={`${completed} completed · ${partial} partial · ${other} other finished · ${c.total - c.done} still to call`}>
      <Box w={width} h={8} bg="#e6e8eb" style={{ borderRadius: 4, overflow: 'hidden', display: 'flex' }}
        role="progressbar" aria-valuenow={completed} aria-valuemax={c.total} aria-label="Completed interviews">
        <Box w={pct(completed)} bg="#2a8a4d" />
        <Box w={pct(partial)} bg="#b06f00" />
        <Box w={pct(other)} bg="#8a919a" />
      </Box>
    </Tooltip>
  )
}

export default function Campaigns() {
  const projectId = useProjectId()
  const list = useQuery({
    queryKey: ['campaigns', projectId], queryFn: () => campaignApi.list(projectId!), enabled: projectId != null,
    refetchInterval: (q) => (q.state.data?.some((c) => c.status === 'running') ? 5000 : false),
  })
  const rows = list.data ?? []
  return (
    <>
      <PageHeader title="Campaigns" subtitle="Call a list of respondents with one form version. Retries and callbacks are scheduled for you."
        actions={<Button component={Link} to="/campaigns/new" leftSection={<IconPlus size={16} />}>New campaign</Button>} />
      <PageBody maw={1400}>
        {list.isError && <ErrorNotice title="Couldn't load campaigns" detail={(list.error as Error).message} />}
        {list.isLoading && <SkeletonRows />}
        {list.isSuccess && !rows.length && (
          <Paper bg="white" p={48} maw={720} mx="auto" w="100%">
            <Title order={2} fz={20}>No campaigns yet</Title>
            <Text size="sm" c="gray.8" mt={6}>
              Upload a CSV with <span className="vs-mono">respondent_id, phone, language</span>, pick a form version and calling
              hours. The agent calls each person, retries no-answers and busy lines, and calls back when asked.
            </Text>
            <Button mt="lg" component={Link} to="/campaigns/new" leftSection={<IconPlus size={16} />}>New campaign</Button>
          </Paper>
        )}
        {!!rows.length && (
          <Paper bg="white" style={{ overflow: 'hidden' }}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Name</Table.Th><Table.Th>Form</Table.Th><Table.Th>Status</Table.Th><Table.Th>Progress</Table.Th>
                  <Table.Th>Outcomes</Table.Th><Table.Th>Created</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((c) => (
                  <Table.Tr key={c.id}>
                    <Table.Td><Anchor component={Link} to={`/campaigns/${c.id}`} fw={500} size="sm">{c.name}</Anchor></Table.Td>
                    <Table.Td><Text size="sm">{c.form.title} · v{c.form.version_no}</Text></Table.Td>
                    <Table.Td><CampaignStatusBadge status={c.status} /></Table.Td>
                    <Table.Td>
                      <Stack gap={4}>
                        <CampaignProgress c={c} />
                        <Text size="xs" c="gray.7" className="vs-num">{c.completed} of {c.total} completed</Text>
                      </Stack>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        {OUTCOMES.filter((o) => c.outcomes[o]).map((o) => (
                          <Group key={o} gap={2} wrap="nowrap"><InterviewStatusBadge status={o} /><Text size="xs" className="vs-num">{c.outcomes[o]}</Text></Group>
                        ))}
                        {!OUTCOMES.some((o) => c.outcomes[o]) && <Text size="xs" c="gray.7">No calls yet</Text>}
                      </Group>
                    </Table.Td>
                    <Table.Td><Text size="sm" className="vs-num">{fmtDate(c.created_at)}</Text><Text size="xs" c="gray.7">{c.created_by}</Text></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Paper>
        )}
      </PageBody>
    </>
  )
}
