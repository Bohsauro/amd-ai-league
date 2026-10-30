import React, { useState, useEffect } from 'react';
import { api, ApiError } from '../../lib/api';
import { JobListItem } from '../../types/api';
import { CheckIcon, SpinnerIcon, DownloadIcon, AlertCircleIcon, RefreshIcon } from '../../components/Icons';

export const JobsPage: React.FC = () => {
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [exportingJobId, setExportingJobId] = useState<string | null>(null);

  const loadJobs = async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const data = await api.listJobs(20, 0);
      setJobs(data.jobs);
      setTotal(data.total);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setErrorMsg(err.detail);
      } else {
        setErrorMsg('Impossibile caricare lo storico dei lavori.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadJobs();
  }, []);

  const handleExportJob = async (jobId: string) => {
    setExportingJobId(jobId);
    try {
      const { blob, filename } = await api.exportZip({ job_id: jobId });
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename || `spesemed_job_${jobId.slice(0, 8)}.zip`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        alert(`Errore export: ${err.detail}`);
      } else {
        alert('Errore durante il download dell’archivio.');
      }
    } finally {
      setExportingJobId(null);
    }
  };

  const formatDate = (dateStr?: string | null) => {
    if (!dateStr) return 'Recente';
    try {
      return new Date(dateStr).toLocaleString('it-IT', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="container ctr" style={{ paddingTop: '2.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <span className="chip chip-neut" style={{ display: 'inline-flex' }}>
          Storico elaborazioni
        </span>
        <button
          className="btn btn-ghost btn-sm"
          onClick={loadJobs}
          disabled={isLoading}
          title="Ricarica elenco"
        >
          <RefreshIcon size={14} /> Aggiorna
        </button>
      </div>

      <h2 style={{ margin: '0.4rem 0 0.8rem' }}>I tuoi lavori di estrazione</h2>
      <p className="dim" style={{ marginBottom: '1.8rem' }}>
        Ogni caricamento diventa un lavoro: ne vedi lo stato e puoi scaricarne l’export se pronto.
      </p>

      {errorMsg && (
        <div
          className="chip-err"
          style={{
            padding: '0.85rem 1rem',
            borderRadius: 'var(--radius-sm)',
            marginBottom: '1.4rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <AlertCircleIcon size={16} />
          <span>{errorMsg}</span>
        </div>
      )}

      <div className="surface" style={{ padding: '0 1.4rem' }}>
        {isLoading ? (
          <div style={{ padding: '2.5rem 1rem', textAlign: 'center', color: 'var(--ink-3)' }}>
            <SpinnerIcon size={20} /> Caricamento storico in corso...
          </div>
        ) : jobs.length > 0 ? (
          jobs.map((job) => {
            const isDone = job.status === 'done';
            const isFailed = job.status === 'failed';
            const isRunning = job.status === 'processing' || job.status === 'pending';
            const isDownloading = exportingJobId === job.job_id;

            return (
              <div key={job.job_id} className="seg">
                <div>
                  <div className="who">
                    {job.file_count} {job.file_count === 1 ? 'ricevuta' : 'ricevute'}
                  </div>
                  <div className="meta">
                    {formatDate(job.created_at)}
                    {job.last_error && ` · ${job.last_error}`}
                  </div>
                </div>

                <div className="right">
                  {isDone && (
                    <span className="chip chip-ok">
                      <CheckIcon size={13} /> Fatto
                    </span>
                  )}
                  {isRunning && <span className="chip chip-run">● In corso</span>}
                  {isFailed && <span className="chip chip-err">Fallito</span>}

                  {isDone && (
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => handleExportJob(job.job_id)}
                      disabled={isDownloading}
                      style={{ padding: '0.35rem 0.85rem', minHeight: '36px' }}
                    >
                      {isDownloading ? (
                        <>
                          <SpinnerIcon size={14} /> ZIP...
                        </>
                      ) : (
                        <>
                          <DownloadIcon size={14} /> Esporta
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            );
          })
        ) : (
          <div style={{ padding: '2rem 0.5rem', textAlign: 'center', color: 'var(--ink-3)' }}>
            Nessun lavoro ancora. Carica la prima ricevuta per iniziare l’estrazione.
          </div>
        )}
      </div>

      {total > 0 && (
        <p className="dim" style={{ textAlign: 'center', marginTop: '1.2rem', fontSize: '0.86rem' }}>
          Visualizzati {jobs.length} di {total} lavori archiviati.
        </p>
      )}
    </div>
  );
};
