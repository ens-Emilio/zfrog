import { useCallback, useEffect, useState } from "react"

export type Lang = "pt" | "en" | "es"

const LANG_KEY = "zfrog-lang"
const LANGS: Lang[] = ["pt", "en", "es"]

function detect(): Lang {
  try {
    const saved = localStorage.getItem(LANG_KEY)
    if (saved === "pt" || saved === "en" || saved === "es") return saved
  } catch {
    /* storage disabled: fall through to navigator */
  }
  const nav = (typeof navigator !== "undefined" ? navigator.language : "en")
    .slice(0, 2)
    .toLowerCase()
  if (nav === "pt" || nav === "es") return nav
  return "en"
}

export function applyLang(lang: Lang) {
  document.documentElement.setAttribute("lang", lang === "pt" ? "pt-BR" : lang === "es" ? "es" : "en")
  try {
    localStorage.setItem(LANG_KEY, lang)
  } catch {
    /* storage disabled: the attribute still applies for this session */
  }
}

/** Language state for the header selector. Defaults to navigator, override in localStorage. */
export function useLang(): [Lang, (lang: Lang) => void] {
  const [lang, setLang] = useState<Lang>("pt")

  useEffect(() => {
    const initial = detect()
    setLang(initial)
    applyLang(initial)
  }, [])

  const set = useCallback((next: Lang) => {
    setLang(next)
    applyLang(next)
  }, [])

  return [lang, set]
}

export const LANG_LABEL: Record<Lang, string> = { pt: "PT", en: "EN", es: "ES" }
export const LANG_ORDER: Lang[] = LANGS
