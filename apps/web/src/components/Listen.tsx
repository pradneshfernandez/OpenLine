import { Button, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconPlayerStopFilled, IconVolume } from '@tabler/icons-react'
import { useEffect, useRef, useState } from 'react'

import { speak } from '../api'
import { useProjectId } from '../hooks'

// One player for the whole app: starting a new sample stops the previous one.
let current: { audio: HTMLAudioElement; stop: () => void } | null = null

/** Plays `text` in the agent's voice (Gnani Timbre) — what the respondent will hear. */
export default function ListenButton({ text, lang, voice, speed, size = 'compact-xs', label = 'Listen' }: {
  text: string; lang: string; voice?: string; speed?: number; size?: string; label?: string
}) {
  const projectId = useProjectId()
  const [state, setState] = useState<'idle' | 'loading' | 'playing'>('idle')
  const mine = useRef<HTMLAudioElement | null>(null)
  // Leaving the page (or switching question) stops this button's sample.
  useEffect(() => () => { if (current && current.audio === mine.current) current.stop() }, [])

  const play = async () => {
    if (state === 'playing') { current?.stop(); return }
    current?.stop()
    setState('loading')
    try {
      const blob = await speak({ text, lang, voice, speed, project_id: projectId })
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      const stop = () => { audio.pause(); URL.revokeObjectURL(url); setState('idle'); if (current?.audio === audio) current = null }
      audio.onended = stop
      current = { audio, stop }
      mine.current = audio
      setState('playing')
      await audio.play()
    } catch (e) {
      setState('idle')
      notifications.show({ color: 'red', title: "Couldn't play the voice", message: (e as Error).message })
    }
  }
  const empty = !text.trim()
  return (
    <Tooltip label={empty ? 'Nothing to read yet' : state === 'playing' ? 'Stop' : "Play it in the agent's voice"}>
      <Button size={size} variant="subtle" disabled={empty} loading={state === 'loading'} onClick={play}
        leftSection={state === 'playing' ? <IconPlayerStopFilled size={12} /> : <IconVolume size={14} />}
        aria-label={`${label}: ${text.slice(0, 40)}`}>
        {state === 'playing' ? 'Stop' : label}
      </Button>
    </Tooltip>
  )
}
