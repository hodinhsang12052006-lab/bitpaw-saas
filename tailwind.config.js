/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          deep: "#08061a",
          panel: "rgba(255, 255, 255, 0.03)",
        },
        neon: {
          cyan: "#00f0ff",
          purple: "#d946ef",
          pink: "#ec4899",
          emerald: "#10b981",
        }
      },
      boxShadow: {
        'neon-cyan': '0 0 10px rgba(0, 240, 255, 0.5), 0 0 20px rgba(0, 240, 255, 0.3)',
        'neon-purple': '0 0 10px rgba(217, 70, 239, 0.5), 0 0 20px rgba(217, 70, 239, 0.3)',
        'neon-pink': '0 0 10px rgba(236, 72, 153, 0.5), 0 0 20px rgba(236, 72, 153, 0.3)',
      },
      backdropBlur: {
        xs: '2px',
      }
    },
  },
  plugins: [],
  safelist: [
    // Colors & Borders (covers dynamically built themes and badges)
    {
      pattern: /(bg|text|border|shadow|from|to|via)-(cyan|purple|pink|emerald|violet|blue|dark|slate|zinc|gray|red|yellow|indigo)-(100|200|300|400|500|600|700|800|900|deep|panel|cyan|purple|pink|emerald)/,
      variants: ['hover', 'focus', 'group-hover'],
    },
    // Backdrop blur, opacities
    {
      pattern: /backdrop-blur-(none|xs|sm|md|lg|xl|2xl)/,
    },
    // Grid systems
    {
      pattern: /grid-cols-(1|2|3|4|5|6|7|8|9|10|11|12)/,
      variants: ['sm', 'md', 'lg', 'xl'],
    },
    // Flex direction and alignments
    'flex-row', 'flex-col', 'items-center', 'justify-between', 'justify-center',
    // Custom neon shadows
    'shadow-neon-cyan', 'shadow-neon-purple', 'shadow-neon-pink',
    // Opacities & borders
    {
      pattern: /border-white\/(5|10|20|30|40|50)/,
    },
    {
      pattern: /bg-white\/(5|10|20|30|40|50)/,
    }
  ]
}
