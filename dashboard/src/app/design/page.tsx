"use client"
import { Button } from "@/components/ui/button"
import { StatusBadge } from "@/components/ui/badge"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Input, Select } from "@/components/ui/input"
import { StatCard } from "@/components/ui/stat-card"
import { Topbar } from "@/components/Navbar"
import { MODE_ORDER } from "@/lib/labels"
import { Search, CheckCircle2, Clock3, AlertCircle } from "lucide-react"

export default function DesignPage() {
  return (
    <div className="space-y-8 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar title="Design System" description="Zfrog v2 — tokens, componentes e padrões" />

      <div className="grid md:grid-cols-3 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Cores</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex gap-2">
              <div className="h-10 w-10 rounded-[10px] bg-primary" />
              <div className="h-10 w-10 rounded-[10px] bg-emerald-500" />
              <div className="h-10 w-10 rounded-[10px] bg-amber-500" />
              <div className="h-10 w-10 rounded-[10px] bg-red-500" />
              <div className="h-10 w-10 rounded-[10px] bg-secondary border" />
            </div>
            <p className="text-[12px] text-muted-foreground">
              primary violeta, sucesso esmeralda, atenção âmbar, erro vermelho
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Tipografia</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            <p className="text-[22px] font-semibold tracking-tight">Título 22px</p>
            <p className="text-[14px] font-medium">Subtítulo 14px</p>
            <p className="text-[13.5px]">Corpo 13.5px</p>
            <p className="text-[12px] font-mono">Mono 12px — identificadores</p>
            <p className="text-[11px] uppercase tracking-widest text-muted-foreground">Rótulo 11px maiúsculas</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Cantos arredondados</CardTitle>
          </CardHeader>
          <CardContent className="flex gap-2">
            <div className="h-10 w-10 rounded-[8px] border bg-card" />
            <div className="h-10 w-10 rounded-[10px] border bg-card" />
            <div className="h-10 w-10 rounded-[12px] border bg-card" />
            <div className="h-10 w-10 rounded-[16px] border bg-card" />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Botões</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button>Primário</Button>
          <Button variant="secondary">Secundário</Button>
          <Button variant="outline">Contorno</Button>
          <Button variant="ghost">Discreto</Button>
          <Button variant="destructive">Destrutivo</Button>
          <Button size="sm">Pequeno</Button>
          <Button size="lg">Grande</Button>
          <Button loading>Carregando</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Situações (status)</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <StatusBadge status="completed" />
          <StatusBadge status="running" />
          <StatusBadge status="probing" />
          <StatusBadge status="processing" />
          <StatusBadge status="pending" />
          <StatusBadge status="failed" />
          <StatusBadge status="cancelled" />
        </CardContent>
      </Card>

      <div className="grid md:grid-cols-4 gap-3">
        <StatCard label="Total" value={128} icon={<Search className="h-4 w-4" />} trend="desde o início" />
        <StatCard label="Concluídas" value={96} icon={<CheckCircle2 className="h-4 w-4" />} trend="75% de sucesso" />
        <StatCard label="Em andamento" value={4} icon={<Clock3 className="h-4 w-4" />} />
        <StatCard label="Falhas" value={8} icon={<AlertCircle className="h-4 w-4" />} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Campos de formulário</CardTitle>
        </CardHeader>
        <CardContent className="grid md:grid-cols-2 gap-4 max-w-[600px]">
          <Input label="Endereço" placeholder="https://exemplo.com.br" leftIcon={<Search className="h-4 w-4" />} hint="Texto de ajuda" />
          <Select label="Modo">
            {MODE_ORDER.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </Select>
        </CardContent>
      </Card>
    </div>
  )
}
