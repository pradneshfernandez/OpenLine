import { Accordion, Alert, Anchor, Box, Breadcrumbs, Group, Paper, Skeleton, Stack, Text, Title } from '@mantine/core'
import { IconAlertCircle } from '@tabler/icons-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

export type Crumb = { label: ReactNode; to?: string }

/** White page header bar: breadcrumbs, title (+ inline extras), subtitle, actions on the right. */
export function PageHeader({ crumbs, title, extra, subtitle, actions, children }: {
  crumbs?: Crumb[]; title: ReactNode; extra?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children?: ReactNode
}) {
  return (
    <Box bg="white" px="xl" pt={crumbs ? 12 : 18} pb={children ? 0 : 14} style={{ borderBottom: '1px solid var(--vs-line)' }}>
      {crumbs && (
        <Breadcrumbs separator="›" separatorMargin={6} mb={4}>
          {crumbs.map((c, i) => c.to
            ? <Anchor key={i} component={Link} to={c.to} size="xs" underline="always">{c.label}</Anchor>
            : <Text key={i} size="xs" c="gray.7">{c.label}</Text>)}
        </Breadcrumbs>
      )}
      <Group justify="space-between" wrap="nowrap" align="center" gap="md">
        <Box style={{ minWidth: 0 }}>
          <Group gap="sm" wrap="nowrap">
            <Title order={1} lineClamp={1}>{title}</Title>
            {extra}
          </Group>
          {subtitle && <Text size="sm" c="gray.7" mt={2}>{subtitle}</Text>}
        </Box>
        {actions && <Group gap="sm" wrap="nowrap" style={{ flexShrink: 0 }}>{actions}</Group>}
      </Group>
      {children}
    </Box>
  )
}

/** Page body with the standard 24px gutters. */
export function PageBody({ children, maw }: { children: ReactNode; maw?: number }) {
  return <Stack gap="lg" p="xl" maw={maw} w="100%">{children}</Stack>
}

/** Bordered panel with an optional header strip. */
export function Panel({ title, meta, actions, children, p = 'md' }: {
  title?: ReactNode; meta?: ReactNode; actions?: ReactNode; children: ReactNode; p?: string | number
}) {
  return (
    <Paper bg="white">
      {title && (
        <Group justify="space-between" px="md" py={10} style={{ borderBottom: '1px solid var(--vs-line)' }} wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Text fw={600} size="md">{title}</Text>
            {meta && <Text size="xs" c="gray.7">{meta}</Text>}
          </Group>
          {actions}
        </Group>
      )}
      <Box p={p}>{children}</Box>
    </Paper>
  )
}

/** Tile: caption label, 24/600 value, optional note. */
export function Tile({ label, value, note, icon, children }: {
  label: ReactNode; value?: ReactNode; note?: ReactNode; icon?: ReactNode; children?: ReactNode
}) {
  return (
    <Paper bg="white" p="md" style={{ minWidth: 0 }}>
      <Group gap={4} wrap="nowrap">
        {icon}
        <Text size="xs" fw={500} c="gray.7">{label}</Text>
      </Group>
      {value != null && <Text fz={24} lh="32px" fw={600} className="vs-num">{value}</Text>}
      {children}
      {note && <Text size="xs" c="gray.7" mt={2}>{note}</Text>}
    </Paper>
  )
}

/** Loading state: skeleton rows in table shape (not spinners). */
export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <Paper bg="white" p="md">
      <Stack gap={8}>
        {Array.from({ length: rows }, (_, i) => <Skeleton key={i} height={26} radius="xs" />)}
      </Stack>
    </Paper>
  )
}

/** Error: plain language + technical detail collapsed. */
export function ErrorNotice({ title, message, detail }: { title: string; message?: ReactNode; detail?: string }) {
  return (
    <Alert color="red" icon={<IconAlertCircle />} title={title}>
      {message}
      {detail && (
        <Accordion variant="unstyled" mt={4} chevronPosition="left">
          <Accordion.Item value="t">
            <Accordion.Control px={0} py={0} fz="xs">Technical detail</Accordion.Control>
            <Accordion.Panel><Text size="xs" className="vs-mono">{detail}</Text></Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      )}
    </Alert>
  )
}

/** Masked phone number for display: +91 98••• ••210. */
export function maskPhone(n: string) {
  const d = n.replace(/[^\d+]/g, '')
  if (d.length < 8) return '•••'
  const cc = d.startsWith('+91') ? '+91 ' : d.startsWith('+') ? d.slice(0, 3) + ' ' : ''
  const rest = d.slice(cc.trim().length)
  return `${cc}${rest.slice(0, 2)}••• ••${rest.slice(-3)}`
}

export const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'
