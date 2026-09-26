import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import "./globals.css"
import { AuthGate } from "@/components/AuthGate"
import { Navbar } from "@/components/Navbar"

const geistSans = Geist({ subsets: ["latin"], variable: "--font-geist-sans" })
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" })

export const metadata: Metadata = {
  title: "Zfrog — Referências de design da web",
  description: "Capturar, organizar e adaptar referências de design da web",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" className={`dark ${geistSans.variable} ${geistMono.variable}`}>
      <body className="min-h-screen bg-background font-sans">
        <div className="flex min-h-screen">
          <Navbar />
          <main className="flex-1 md:ml-[240px] min-h-screen">
            <div className="mx-auto max-w-[1280px] p-4 md:p-8 pt-6 md:pt-8">
              <AuthGate>{children}</AuthGate>
            </div>
          </main>
        </div>
      </body>
    </html>
  )
}
