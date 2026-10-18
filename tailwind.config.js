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
    // Màu ghép động trong JS (vd `border-${colorClass}-500/50`, `bg-${p.color}-500/10`, `text-${color}-400`).
    // Pattern CÓ mốc ^...$ : bản cũ không có mốc nên khớp cả MỌI mức trong suốt (/5../100) x 4 trạng thái -> 70.000
    // quy tắc, file CSS 8,5 MB mọi trang phải tải. Bổ sung rose/amber/fuchsia... (đang được ghép động nhưng thiếu).
    {
      pattern: /^(bg|text|border|shadow|from|to|via)-(cyan|purple|pink|emerald|violet|blue|slate|zinc|gray|red|yellow|indigo|rose|amber|fuchsia|orange|green|teal|sky|lime)-(100|200|300|400|500|600|700|800|900)$/,
      variants: ['hover', 'focus', 'group-hover'],
    },
    {
      pattern: /^(bg|text|border)-(cyan|purple|pink|emerald|violet|blue|slate|zinc|gray|red|yellow|indigo|rose|amber|fuchsia|orange|green|teal|sky|lime)-(300|400|500|600)\/(10|20|30|40|50)$/,
    },
    { pattern: /^(bg|text|border)-dark-(deep|panel)$/ },
    { pattern: /^(bg|text|border|shadow)-neon-(cyan|purple|pink|emerald)$/ },
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
