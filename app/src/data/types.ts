/** Shapes returned by the FastAPI server (server/main.py). */

export type ChoreGroup = {
  name: string;
  tasks: string[];
  frequency_days?: number | null;
  tolerance_days?: number | null;
  buffer_days?: number | null;
  piggyback_on?: string | null;
  every_nth?: number | null;
  /** app-only: named sessions within a day, e.g. breakfast / lunch / dinner */
  sessions?: string[] | null;
  /** solo mode: rough minutes, used to keep any one day from getting heavy */
  minutes?: number | null;
};

export type Household = {
  mode: 'household' | 'solo';
  roommates: string[];
  colors: Record<string, string>;
  buffer_days: number;
  chore_groups: ChoreGroup[];
  days_off: Record<string, string[]>;
  exclusions: Record<string, string[]>;
  random_seed: number | 'auto';
  start_day: string;
  weeks_to_plan: number;
  // solo mode
  daily_cap_minutes?: number;
  busy_days?: string[];
  busy_cap_minutes?: number;
};

export type Slot = {
  id: string;
  date: string;
  day: string;
  day_idx: number;
  task: string;
  group: string;
  person: string;
  rest_before: number | null;
};

export type Metrics = {
  structural_violations: number;
  buffer_violations: number;
  workload_spread: number;
  rest_balance_spread: number;
  per_chore_spread: number;
  workload: Record<string, number>;
  per_task_counts: Record<string, Record<string, number>>;
  avg_rest: number;
  min_rest: number;
  total_tasks: number;
  // solo mode
  daily_minutes?: Record<string, number>;
  heaviest_day_minutes?: number;
  days_over_cap?: string[];
};

export type Violation = Record<string, string | number>;

export type Candidate = {
  key: string;
  label: string;
  proven: boolean;
  rank_key: number[];
  metrics: Metrics;
  slots: Slot[];
  forced_violations?: Violation[];
  cadence_violations?: Violation[];
};

export type AlgoProgress = {
  label: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  seconds: number | null;
  note: string | null;
};

export type PlanJob = {
  id: string;
  mode?: 'household' | 'solo';
  status: 'running' | 'done' | 'failed';
  started_at: string;
  progress: Record<string, AlgoProgress>;
  error: string | null;
  result?: {
    start_day: string;
    days: number;
    roommates: string[];
    seed: number;
    warnings: string[];
    carried_over: boolean;
    candidates: Candidate[];
  };
};

export type Schedule = {
  published_at: string;
  start_day: string;
  days: number;
  algorithm: string;
  label: string;
  proven: boolean;
  metrics: Metrics;
  forced_violations: Violation[];
  cadence_violations: Violation[];
  slots: Slot[];
};

export type SessionMark = 'done' | 'missed' | null;

export type TaskStatus = {
  state: 'done' | 'missed' | 'covered' | 'skipped' | 'partial';
  sessions?: SessionMark[];
  covered_by?: string;
  note?: string;
  updated_at?: string;
};
