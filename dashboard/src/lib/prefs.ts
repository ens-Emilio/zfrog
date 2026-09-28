"use client"

import { useCallback, useEffect, useState } from "react"

export type Theme = "dark" | "light"
export type Motion = "full" | "reduced"

const THEME_KEY = "zfrog-theme"
const MOTION_KEY = "zfrog-motion"

/**
 * Theme and motion preference, stored the way the design system stores them.
 *
 * `data-theme` and `data-motion` on `<html>` are the source of truth — the
 * stylesheet reads both — and localStorage only carries the choice across
 * reloads. The blocking script in `layout.tsx` applies them before first paint,
 * so these writers are the only client-side mutation.
 */
export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme)
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    /* storage disabled: the attribute still applies for this session */
  }
}

export function applyMotion(motion: Motion) {
  document.documentElement.setAttribute("data-motion", motion)
  try {
    localStorage.setItem(MOTION_KEY, motion)
  } catch {
    /* storage disabled: the attribute still applies for this session */
  }
}

/** Theme state for the controls that toggle it. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>("dark")

  useEffect(() => {
    let stored: string | null = null
    try {
      stored = localStorage.getItem(THEME_KEY)
    } catch {
      /* storage disabled: keep the dark default */
    }
    setTheme(stored === "light" ? "light" : "dark")
  }, [])

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark"
      applyTheme(next)
      return next
    })
  }, [])

  return [theme, toggle]
}

/** Motion state for the "Reduzir animações" switch. */
export function useMotion(): [Motion, (value: Motion) => void] {
  const [motion, setMotion] = useState<Motion>("full")

  useEffect(() => {
    let stored: string | null = null
    try {
      stored = localStorage.getItem(MOTION_KEY)
    } catch {
      /* storage disabled: keep the full-motion default */
    }
    setMotion(stored === "reduced" ? "reduced" : "full")
  }, [])

  const update = useCallback((value: Motion) => {
    applyMotion(value)
    setMotion(value)
  }, [])

  return [motion, update]
}
