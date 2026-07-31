/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}'
  ],
  theme: {
    extend: {
      colors: {
        panel:  'var(--panel)',
        panel2: 'var(--panel2)',
        line:   'var(--line)',
        line2:  'var(--line2)',
        teal:   'var(--teal)',
        orange: 'var(--orange)',
        pink:   'var(--pink)',
        muted:  'var(--muted)',
      },
      borderRadius: {
        card:  '7px',
        sm:    '4px',
        badge: '3px',
      },
      fontFamily: {
        sans: ['Manrope', 'system-ui'],
        mono: ['DM Mono', 'monospace'],
      },
    }
  },
  plugins: []
}
