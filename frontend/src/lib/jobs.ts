/**
 * Background job API (Phase 3).
 *
 * Long-running media/storage work moved from in-memory endpoints to the
 * `jobs` table:
 *
 *   POST /api/admin/jobs          {kind, media_id?, gallery_id?, force?} -> {ok, job}
 *   GET  /api/admin/jobs/{id}     -> job
 *   GET  /api/admin/jobs?...      -> {items, total}
 *   POST /api/admin/jobs/{id}/cancel
 *
 * `runJob()` creates the job; `waitForJob()` polls it every couple of seconds
 * and reports progress so the admin UI can keep showing status.
 */
import { api } from './api';

export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | string;

export interface Job {
  id: number;
  kind: string;
  status: JobStatus;
  /** 0–100 (backend-defined; may stay 0 for indeterminate work). */
  progress: number;
  result: string;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  media_id?: number | null;
  gallery_id?: number | null;
  force?: boolean;
}

export interface JobRequest {
  kind: string;
  media_id?: number;
  gallery_id?: number;
  force?: boolean;
}

export interface WaitForJobOptions {
  /** Poll interval in ms (default 2000). */
  intervalMs?: number;
  /** Called immediately and after every poll. */
  onProgress?: (job: Job) => void;
  /** Stop polling when aborted. */
  signal?: AbortSignal;
}

const TERMINAL: ReadonlySet<string> = new Set(['done', 'failed', 'cancelled']);

export function isJobFinished(status: JobStatus): boolean {
  return TERMINAL.has(status);
}

/** Human label for a job kind (used by the admin UI). */
export function jobLabel(kind: string): string {
  switch (kind) {
    case 'reencode':
      return '重新生成派生图';
    case 'storage_sync':
      return '同步到对象存储';
    case 'prewarm':
      return '预热派生图';
    case 'prune':
      return '清理派生图';
    default:
      return kind;
  }
}

/** Human label for a job status. */
export function jobStatusLabel(status: JobStatus): string {
  switch (status) {
    case 'queued':
      return '排队中';
    case 'running':
      return '进行中';
    case 'done':
      return '已完成';
    case 'failed':
      return '失败';
    case 'cancelled':
      return '已取消';
    default:
      return status;
  }
}

/** One-line progress text, e.g. `重新生成派生图 · 进行中 42%`. */
export function jobProgressText(job: Job): string {
  const label = jobLabel(job.kind);
  const status = jobStatusLabel(job.status);
  if (job.status === 'failed') return `${label} · 失败：${job.error || '未知错误'}`;
  const progress =
    job.status === 'running' && Number.isFinite(job.progress) && job.progress > 0
      ? ` ${Math.min(100, Math.round(job.progress))}%`
      : '';
  return `${label} · ${status}${progress}`;
}

/** Create a background job. */
export async function runJob(request: JobRequest): Promise<Job> {
  const result = await api<{ ok: boolean; job: Job }>('/api/admin/jobs', {
    method: 'POST',
    body: request,
  });
  return result.job;
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve();
      return;
    }
    const timer = window.setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        window.clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

/**
 * Poll a job until it reaches a terminal status. Resolves with the last known
 * job state even when aborted, so callers can stop cleanly on page teardown.
 */
export async function waitForJob(
  job: Job,
  options: WaitForJobOptions = {},
): Promise<Job> {
  const intervalMs = options.intervalMs ?? 2000;
  let current = job;
  options.onProgress?.(current);
  while (!isJobFinished(current.status) && !options.signal?.aborted) {
    await delay(intervalMs, options.signal);
    if (options.signal?.aborted) break;
    try {
      current = await api<Job>(`/api/admin/jobs/${job.id}`);
    } catch {
      // A transient poll failure must not abort the UI; try again next tick.
      continue;
    }
    options.onProgress?.(current);
  }
  return current;
}

/** Cancel a queued job (the backend only allows queued jobs). */
export async function cancelJob(jobId: number): Promise<Job> {
  const result = await api<{ ok: boolean; job?: Job }>(
    `/api/admin/jobs/${jobId}/cancel`,
    { method: 'POST' },
  );
  return result.job ?? ({ id: jobId } as Job);
}
