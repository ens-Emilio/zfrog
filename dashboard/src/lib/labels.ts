import { JobMode, JobStatus } from "./api"
import type { I18nKey } from "./i18n"
import type { IconName } from "./icons"

/** Short label for status pills and table cells. Keys into `status.*` in the i18n dict. */
export const STATUS_LABELS: Record<JobStatus, I18nKey> = {
  pending: "status.pending",
  probing: "status.probing",
  processing: "status.processing",
  running: "status.running",
  completed: "status.completed",
  failed: "status.failed",
  cancelled: "status.cancelled",
}

/** Very short label for the progress stepper. */
export const STATUS_SHORT: Record<JobStatus, I18nKey> = {
  pending: "status.shortPending",
  probing: "status.shortProbing",
  processing: "status.shortProcessing",
  running: "status.shortRunning",
  completed: "status.shortCompleted",
  failed: "status.shortFailed",
  cancelled: "status.shortCancelled",
}

/** One sentence explaining what the status means, shown to the user. */
export const STATUS_HELP: Record<JobStatus, I18nKey> = {
  pending: "status.helpPending",
  probing: "status.helpProbing",
  processing: "status.helpProcessing",
  running: "status.helpRunning",
  completed: "status.helpCompleted",
  failed: "status.helpFailed",
  cancelled: "status.helpCancelled",
}

export interface ModeInfo {
  /** Short name shown on tiles and in the navigation. Keys into `mode.*.label`. */
  label: I18nKey
  /** Icon name in the design system. */
  icon: IconName
  /** What the mode does, in one sentence. Keys into `mode.*.what`. */
  what: I18nKey
  /** When to pick this mode. Keys into `mode.*.when`. */
  when: I18nKey
  /** What the user receives in the end. Keys into `mode.*.output`. */
  output: I18nKey
  /** `rec` shows up as a tile; `adv` lives in the "More modes…" menu. */
  group: "rec" | "adv"
}

/**
 * The extraction modes, in the order and with the wording of the design system.
 *
 * `auto` leads because it is the backend default: the probe picks the capture motor.
 * The four recommended tiles are the capture modes; everything else lives behind
 * "Mais modos…" so the first screen stays a single decision.
 */
export const MODES: Record<JobMode, ModeInfo> = {
  auto: {
    label: "mode.auto.label",
    icon: "i-frog",
    group: "rec",
    what: "mode.auto.what",
    when: "mode.auto.when",
    output: "mode.auto.output",
  },
  jump: {
    label: "mode.jump.label",
    icon: "i-target",
    group: "rec",
    what: "mode.jump.what",
    when: "mode.jump.when",
    output: "mode.jump.output",
  },
  tongue: {
    label: "mode.tongue.label",
    icon: "i-code",
    group: "adv",
    what: "mode.tongue.what",
    when: "mode.tongue.when",
    output: "mode.tongue.output",
  },
  singlepage: {
    label: "mode.singlepage.label",
    icon: "i-file",
    group: "rec",
    what: "mode.singlepage.what",
    when: "mode.singlepage.when",
    output: "mode.singlepage.output",
  },
  mirror: {
    label: "mode.mirror.label",
    icon: "i-globe",
    group: "rec",
    what: "mode.mirror.what",
    when: "mode.mirror.when",
    output: "mode.mirror.output",
  },
  scrape: {
    label: "mode.scrape.label",
    icon: "i-code",
    group: "rec",
    what: "mode.scrape.what",
    when: "mode.scrape.when",
    output: "mode.scrape.output",
  },
  delta: {
    label: "mode.delta.label",
    icon: "i-repeat",
    group: "rec",
    what: "mode.delta.what",
    when: "mode.delta.when",
    output: "mode.delta.output",
  },
  extract: {
    label: "mode.extract.label",
    icon: "i-database",
    group: "adv",
    what: "mode.extract.what",
    when: "mode.extract.when",
    output: "mode.extract.output",
  },
  analyze: {
    label: "mode.analyze.label",
    icon: "i-search",
    group: "adv",
    what: "mode.analyze.what",
    when: "mode.analyze.when",
    output: "mode.analyze.output",
  },
  compare: {
    label: "mode.compare.label",
    icon: "i-scale",
    group: "adv",
    what: "mode.compare.what",
    when: "mode.compare.when",
    output: "mode.compare.output",
  },
  ask: {
    label: "mode.ask.label",
    icon: "i-message",
    group: "adv",
    what: "mode.ask.what",
    when: "mode.ask.when",
    output: "mode.ask.output",
  },
  pdf: {
    label: "mode.pdf.label",
    icon: "i-file-down",
    group: "adv",
    what: "mode.pdf.what",
    when: "mode.pdf.when",
    output: "mode.pdf.output",
  },
  summarize: {
    label: "mode.summarize.label",
    icon: "i-sparkles",
    group: "adv",
    what: "mode.summarize.what",
    when: "mode.summarize.when",
    output: "mode.summarize.output",
  },
  entities: {
    label: "mode.entities.label",
    icon: "i-users",
    group: "adv",
    what: "mode.entities.what",
    when: "mode.entities.when",
    output: "mode.entities.output",
  },
  translate: {
    label: "mode.translate.label",
    icon: "i-globe",
    group: "adv",
    what: "mode.translate.what",
    when: "mode.translate.when",
    output: "mode.translate.output",
  },
  sentiment: {
    label: "mode.sentiment.label",
    icon: "i-activity",
    group: "adv",
    what: "mode.sentiment.what",
    when: "mode.sentiment.when",
    output: "mode.sentiment.output",
  },
  tags: {
    label: "mode.tags.label",
    icon: "i-type",
    group: "adv",
    what: "mode.tags.what",
    when: "mode.tags.when",
    output: "mode.tags.output",
  },
  video: {
    label: "mode.video.label",
    icon: "i-play",
    group: "adv",
    what: "mode.video.what",
    when: "mode.video.when",
    output: "mode.video.output",
  },
  api_discovery: {
    label: "mode.api_discovery.label",
    icon: "i-terminal",
    group: "adv",
    what: "mode.api_discovery.what",
    when: "mode.api_discovery.when",
    output: "mode.api_discovery.output",
  },
}

/** The four recommended tiles, `auto` first. */
export const RECOMMENDED_MODES = (Object.keys(MODES) as JobMode[]).filter((mode) => MODES[mode].group === "rec")

/** Everything behind "More modes…". */
export const ADVANCED_MODES = (Object.keys(MODES) as JobMode[]).filter((mode) => MODES[mode].group === "adv")

/** Every mode in display order: the recommended tiles, then the advanced menu. */
export const MODE_ORDER: JobMode[] = [...RECOMMENDED_MODES, ...ADVANCED_MODES]
