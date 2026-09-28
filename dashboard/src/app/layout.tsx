import type { Metadata } from "next"
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google"
import "./globals.css"
import { AuthGate } from "@/components/AuthGate"
import { Navbar } from "@/components/Navbar"
import { CommandPalette } from "@/components/CommandPalette"
import { ToastRegion } from "@/components/ToastRegion"

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-space-grotesk",
})
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" })
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains-mono" })

export const metadata: Metadata = {
  title: "zfrog — Referências de design da web",
  description: "Capturar, organizar e adaptar referências de design da web",
}

/**
 * Applies the stored theme and motion preference before the first paint.
 *
 * Blocking on purpose: setting `data-theme` after hydration would flash the dark
 * palette for someone who chose the light one. Kept to two attribute writes —
 * anything more belongs in a component.
 */
const bootstrapPreferences = `(function(){try{
var t=localStorage.getItem("zfrog-theme");document.documentElement.setAttribute("data-theme",t==="light"?"light":"dark");
var m=localStorage.getItem("zfrog-motion");document.documentElement.setAttribute("data-motion",m==="reduced"?"reduced":"full");
}catch(e){}})()`

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="pt-BR"
      data-theme="dark"
      data-motion="full"
      suppressHydrationWarning
      className={`${spaceGrotesk.variable} ${inter.variable} ${jetbrainsMono.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: bootstrapPreferences }} />
      </head>
      <body className="min-h-screen">
        <ToastRegion>
          <a className="skip-link" href="#conteudo">
            Ir para o conteúdo
          </a>
          <div className="ambient" aria-hidden="true" />
          <div className="app">
            <Navbar />
            <main className="main" id="conteudo">
              <div className="views">
                <AuthGate>{children}</AuthGate>
              </div>
            </main>
          </div>
          <CommandPalette />
        </ToastRegion>
      </body>
    </html>
  )
}
