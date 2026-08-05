import { Ban, CheckCircle2, CircleAlert, LoaderCircle, X } from "lucide-react";
import type { JobEvent } from "../types";

interface JobBarProps {
  jobs: JobEvent[];
  onCancel: (id: string) => void;
}

const activeStatuses = new Set(["queued", "loading", "running", "rendering"]);

export function JobBar({ jobs, onCancel }: JobBarProps) {
  const visible = jobs.slice(0, 4);
  return (
    <footer className="job-bar" aria-label="任务队列">
      <div className="job-bar__label">
        <LoaderCircle size={15} />
        <span>任务</span>
        <span className="count-badge">{jobs.filter((job) => activeStatuses.has(job.status)).length}</span>
      </div>
      <div className="job-bar__items">
        {visible.length === 0 ? (
          <span className="muted">队列空闲</span>
        ) : (
          visible.map((job) => (
            <div className="job-item" key={job.id}>
              {job.status === "completed" ? (
                <CheckCircle2 className="status-success" size={15} />
              ) : job.status === "failed" ? (
                <CircleAlert className="status-danger" size={15} />
              ) : job.status === "cancelled" ? (
                <Ban className="muted" size={15} />
              ) : (
                <LoaderCircle className="spin status-primary" size={15} />
              )}
              <div className="job-item__body">
                <div className="job-item__title">
                  <span>{job.stage}</span>
                  <span>{Math.round(job.progress * 100)}%</span>
                </div>
                <div className="progress-track"><span style={{ width: `${job.progress * 100}%` }} /></div>
              </div>
              {activeStatuses.has(job.status) && (
                <button className="icon-button small" title="取消任务" onClick={() => onCancel(job.id)}>
                  <X size={14} />
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </footer>
  );
}
