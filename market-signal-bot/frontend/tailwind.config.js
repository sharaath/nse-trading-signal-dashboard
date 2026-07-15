/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        themeDark: "#0f172a",
        themeBlue: "#0284c7"
      }
    },
  },
  plugins: [],
}
