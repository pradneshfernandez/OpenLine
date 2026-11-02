// Voice Survey — Mantine 9 theme. Values match "Design System.dc.html".
import { createTheme, type MantineColorsTuple } from '@mantine/core';

const brand: MantineColorsTuple = ['#eaf0fa','#d3e0f5','#b9cbea','#8eaadb','#5f84c7','#3a67b4','#1f4fa3','#183f84','#123068','#0c214a'];
const gray: MantineColorsTuple  = ['#f8f9fa','#eef0f2','#e6e8eb','#dcdfe3','#c3c8ce','#a5acb4','#8a919a','#5c636d','#424851','#121417'];
const green: MantineColorsTuple = ['#e7f3ec','#cfe8d8','#a9d3b8','#7dbc95','#52a573','#2a8a4d','#1d6b3a','#16542d','#0f3d20','#082713'];
const yellow: MantineColorsTuple= ['#fdf3dc','#fae6b5','#ecc979','#e0ad47','#cf931c','#b06f00','#7a4b00','#5a3a00','#3d2a00','#221700'];
const red: MantineColorsTuple   = ['#fbe9e7','#f6d0cc','#efb2ab','#e2867c','#d55a4e','#c8302a','#a3221b','#7a2a24','#5a120e','#3a0906'];
const teal: MantineColorsTuple  = ['#e4f3f4','#c6e6e8','#a6d3d7','#74bac0','#43a0a8','#138591','#0b5e66','#084a51','#063a40','#03252a'];

export const theme = createTheme({
  primaryColor: 'brand',
  primaryShade: 6,
  colors: { brand, gray, green, yellow, red, teal },
  black: '#121417',
  white: '#ffffff',
  fontFamily: "'IBM Plex Sans', 'IBM Plex Sans Devanagari', system-ui, sans-serif",
  fontFamilyMonospace: "'IBM Plex Mono', ui-monospace, monospace",
  headings: { fontFamily: "'IBM Plex Sans', 'IBM Plex Sans Devanagari', sans-serif", fontWeight: '600',
    sizes: { h1: { fontSize: '24px', lineHeight: '32px' }, h2: { fontSize: '18px', lineHeight: '26px' }, h3: { fontSize: '15px', lineHeight: '22px' } } },
  fontSizes: { xs: '12px', sm: '13px', md: '14px', lg: '16px', xl: '18px' },
  lineHeights: { xs: '1.35', sm: '1.45', md: '1.5', lg: '1.6', xl: '1.6' }, // add [lang=hi] { line-height: 1.7 } globally
  spacing: { xs: '4px', sm: '8px', md: '12px', lg: '16px', xl: '24px' },
  radius: { xs: '3px', sm: '4px', md: '6px', lg: '6px', xl: '8px' },
  defaultRadius: 'sm',
  shadows: { xs: '0 1px 2px rgba(18,20,23,.06)', sm: '0 4px 12px rgba(18,20,23,.12)', md: '0 12px 32px rgba(18,20,23,.20)' },
  focusRing: 'auto', // global CSS: :focus-visible { outline: 3px solid #ffcc00; box-shadow: 0 0 0 5px #121417 }
  components: {
    Button: { defaultProps: { size: 'sm' } },
    Badge: { defaultProps: { variant: 'light', radius: 'xs', size: 'md' }, styles: { root: { textTransform: 'none', fontWeight: 500, height: 22, borderWidth: 1, borderStyle: 'solid' } } },
    Table: { defaultProps: { verticalSpacing: 7, horizontalSpacing: 12, fz: 13, highlightOnHover: true, stickyHeader: true },
      styles: { th: { fontSize: 12, fontWeight: 600, color: '#424851', background: '#f8f9fa', borderBottom: '1px solid #c3c8ce' } } },
    Paper: { defaultProps: { withBorder: true, radius: 'md', shadow: undefined } },
    TextInput: { styles: { input: { borderColor: '#8a919a' }, label: { fontSize: 12, fontWeight: 600, marginBottom: 4 } } },
    Textarea: { defaultProps: { autosize: true, minRows: 2 }, styles: { input: { borderColor: '#8a919a' } } },
    Select: { styles: { input: { borderColor: '#8a919a' } } },
    SegmentedControl: { defaultProps: { size: 'xs', radius: 'sm' } },
    Switch: { defaultProps: { size: 'sm' } },
    Tooltip: { defaultProps: { withArrow: true, openDelay: 300, multiline: true, maw: 320 } },
    Modal: { defaultProps: { centered: true, radius: 'md', size: 'md', overlayProps: { backgroundOpacity: 0.45 } } },
    Alert: {
      defaultProps: { variant: 'light', radius: 'sm' },
      styles: { root: { border: '1px solid' }, title: { fontWeight: 600 }, message: { color: '#121417' } },
      // Map Mantine colours onto the semantic tones so alerts match the badges, not Mantine's saturated light fills.
      vars: (_theme: unknown, props: { color?: string }) => {
        const t = ALERT_TONE[props.color ?? 'brand'] ?? tone.brand;
        return { root: { '--alert-bg': t.bg, '--alert-bd': t.bd, '--alert-color': t.fg } };
      },
    },
  },
});

// Semantic tokens (text / fill / border / icon) for status, severity and flag badges
export const tone = {
  success: { fg: '#1d6b3a', bg: '#e7f3ec', bd: '#a9d3b8', ic: '#2a8a4d' },
  warning: { fg: '#7a4b00', bg: '#fdf3dc', bd: '#ecc979', ic: '#b06f00' },
  danger:  { fg: '#a3221b', bg: '#fbe9e7', bd: '#efb2ab', ic: '#c8302a' },
  info:    { fg: '#0b5e66', bg: '#e4f3f4', bd: '#a6d3d7', ic: '#138591' },
  brand:   { fg: '#1f4fa3', bg: '#eaf0fa', bd: '#b9cbea', ic: '#1f4fa3' },
  neutral: { fg: '#424851', bg: '#f1f2f4', bd: '#d5d8dc', ic: '#5c636d' },
  terminal:{ fg: '#ffffff', bg: '#3a3f46', bd: '#3a3f46', ic: '#ffffff' },
};

const ALERT_TONE: Record<string, (typeof tone)[keyof typeof tone]> = {
  green: tone.success, yellow: tone.warning, red: tone.danger, teal: tone.info, brand: tone.brand, blue: tone.brand, gray: tone.neutral, dark: tone.neutral,
};
