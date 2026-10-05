import { useEffect, useState } from 'react';

import { api } from './api';
import type { PlanJob } from './types';

/** Polls a solve job until every algorithm has finished. */
export function usePlan(jobId: string | undefined) {
  const [job, setJob] = useState<PlanJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const j = await api.getPlan(jobId);
        if (!alive) return;
        setJob(j);
        if (j.status === 'running') timer = setTimeout(poll, 600);
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [jobId]);

  return { job, error };
}

/** "exceptions" the way the app talks about them: rule breaks + rest-buffer breaks. */
export function exceptions(m: { structural_violations: number; buffer_violations: number }) {
  return m.structural_violations + m.buffer_violations;
}
