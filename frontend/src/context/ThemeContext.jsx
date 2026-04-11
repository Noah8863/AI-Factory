import { createContext, useContext, useState, useEffect } from 'react'

const ThemeContext = createContext()

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => {
    return localStorage.getItem('aif_theme') || 'dark'
  })

  // Apply data-theme attribute to <html> and persist whenever theme changes
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('aif_theme', theme)
  }, [theme])

  // Apply once on mount so the initial render is already themed
  useEffect(() => {
    const saved = localStorage.getItem('aif_theme') || 'dark'
    document.documentElement.setAttribute('data-theme', saved)
  }, [])

  const setTheme = (t) => setThemeState(t)

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  return useContext(ThemeContext)
}
