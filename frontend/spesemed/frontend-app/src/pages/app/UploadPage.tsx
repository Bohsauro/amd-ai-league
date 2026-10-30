import React, { useState, useRef, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, ApiError } from '../../lib/api';
import { useApp } from '../../context/AppContext';
import { SpesaMedica } from '../../types/api';
import { SpinnerIcon, CheckIcon, AlertCircleIcon, UploadIcon, CloseIcon } from '../../components/Icons';
import { TrustBadgePrivacy } from '../../components/TrustBadges';

const ACCEPTED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png', '.webp', '.bmp'];
const MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024; // 20 MB
const MAX_FILES = 20;

export const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const { addExpenses, setActiveJobId } = useApp();

  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [paymentRequired, setPaymentRequired] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  // Stato per async job polling
  const [asyncJobId, setAsyncJobId] = useState<string | null>(null);
  const [asyncStatus, setAsyncStatus] = useState<string | null>(null);
  const [completedCount, setCompletedCount] = useState<number>(0);
  const [totalFilesCount, setTotalFilesCount] = useState<number>(0);
  const [isStale, setIsStale] = useState<boolean>(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pollingRef = useRef<number | null>(null);
  const staleTimerRef = useRef<number | null>(null);

  // Cleanup polling su unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) window.clearInterval(pollingRef.current);
      if (staleTimerRef.current) window.clearTimeout(staleTimerRef.current);
    };
  }, []);

  const validateAndAddFiles = (incoming: FileList | File[]) => {
    setErrorMsg(null);
    const newFiles: File[] = [];

    for (let i = 0; i < incoming.length; i++) {
      const file = incoming[i];
      const ext = '.' + file.name.split('.').pop()?.toLowerCase();

      if (!ACCEPTED_EXTENSIONS.includes(ext)) {
        setErrorMsg(`Il file '${file.name}' ha un formato non supportato. Formati ammessi: PDF, JPG, PNG, WEBP, BMP.`);
        return;
      }

      if (file.size > MAX_FILE_SIZE_BYTES) {
        setErrorMsg(`Il file '${file.name}' supera il limite massimo di 20 MB.`);
        return;
      }

      newFiles.push(file);
    }

    if (selectedFiles.length + newFiles.length > MAX_FILES) {
      setErrorMsg(`Puoi caricare al massimo ${MAX_FILES} file per volta.`);
      return;
    }

    setSelectedFiles((prev) => [...prev, ...newFiles]);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndAddFiles(e.dataTransfer.files);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      validateAndAddFiles(e.target.files);
    }
  };

  const handleRemoveFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, idx) => idx !== index));
  };

  const startPolling = (jobId: string, initialCount: number) => {
    setAsyncJobId(jobId);
    setActiveJobId(jobId);
    setAsyncStatus('in_coda');
    setTotalFilesCount(initialCount);
    setCompletedCount(0);
    setIsStale(false);

    // Stale timer: 60 secondi
    staleTimerRef.current = window.setTimeout(() => {
      setIsStale(true);
    }, 60_000);

    pollingRef.current = window.setInterval(async () => {
      try {
        const job = await api.getJob(jobId);
        setAsyncStatus(job.status);
        setCompletedCount(job.completed_count || 0);

        if (job.status === 'done') {
          if (pollingRef.current) window.clearInterval(pollingRef.current);
          if (staleTimerRef.current) window.clearTimeout(staleTimerRef.current);

          setIsProcessing(false);
          if (job.results && job.results.length > 0) {
            addExpenses(job.results);
          }
          navigate('/app/results');
        } else if (job.status === 'failed') {
          if (pollingRef.current) window.clearInterval(pollingRef.current);
          if (staleTimerRef.current) window.clearTimeout(staleTimerRef.current);

          setIsProcessing(false);
          setErrorMsg(job.error || 'L’estrazione asincrona è fallita. Riprova con file più nitidi.');
        }
      } catch (pollErr) {
        console.warn('Errore di polling job:', pollErr);
      }
    }, 2500);
  };

  const handleExtract = async () => {
    if (selectedFiles.length === 0) return;

    setIsProcessing(true);
    setErrorMsg(null);
    setPaymentRequired(false);
    setIsStale(false);

    try {
      const response = await api.extract(selectedFiles);

      if (response.kind === 'sync') {
        // Modalità sincrona (N <= 3)
        const extractedExpenses: SpesaMedica[] = response.data.results.map((spesa, idx) => ({
          ...spesa,
          id: `sync-${Date.now()}-${idx}`,
          source_file_name: selectedFiles[idx]?.name || 'ricevuta.pdf',
          file_hash: response.data.file_hashes[idx],
          status: 'pending',
        }));

        addExpenses(extractedExpenses);
        setIsProcessing(false);
        navigate('/app/results');
      } else {
        // Modalità asincrona (N > 3)
        startPolling(response.data.job_id, response.data.file_count);
      }
    } catch (err: unknown) {
      setIsProcessing(false);
      if (err instanceof ApiError) {
        if (err.status === 402 || err.code === 'payment_required') {
          setPaymentRequired(true);
        } else {
          setErrorMsg(err.detail);
        }
      } else {
        setErrorMsg('Errore imprevisto durante l’invio dei file.');
      }
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024 * 1024) {
      return (bytes / 1024).toFixed(1) + ' KB';
    }
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  return (
    <div className="container ctr" style={{ paddingTop: '2.5rem' }}>
      <TrustBadgePrivacy />

      <span className="chip chip-neut" style={{ marginTop: '1rem', display: 'inline-flex' }}>
        Carica ricevute
      </span>
      <h2 style={{ margin: '0.4rem 0 0.6rem' }}>Mettile qui. Ce ne occupiamo noi.</h2>
      <p className="lead" style={{ marginBottom: '1.6rem' }}>
        PDF (anche multipagina) oppure foto di scontrini, fatture e parcelle mediche.
      </p>

      {errorMsg && (
        <div
          className="banner banner-err"
          style={{ marginBottom: '1.4rem' }}
          role="alert"
        >
          <AlertCircleIcon size={18} />
          <span>{errorMsg}</span>
        </div>
      )}

      {paymentRequired && (
        <div
          className="banner banner-info"
          style={{ marginBottom: '1.4rem', alignItems: 'center', flexWrap: 'wrap' }}
          role="status"
        >
          <AlertCircleIcon size={18} />
          <span style={{ flex: '1 1 240px' }}>
            Il tuo piano non copre altre estrazioni. I file restano qui: attiva il piano Pro dal
            Profilo e riprendi quando vuoi.
          </span>
          <Link to="/app/profile" className="btn btn-green btn-sm">
            Vai al Profilo
          </Link>
        </div>
      )}

      {/* Async Polling Progress Banner */}
      {asyncJobId && isProcessing && (
        <div
          className="band"
          style={{
            padding: '1.4rem',
            borderRadius: 'var(--radius)',
            marginBottom: '1.5rem',
            textAlign: 'left',
          }}
          role="status"
          aria-live="polite"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>
              Elaborazione in secondo piano (Job {asyncJobId.slice(0, 8)}...)
            </span>
            <span className="chip chip-run">
              <SpinnerIcon size={14} /> {asyncStatus === 'processing' ? 'In lettura AI' : 'In coda'}
            </span>
          </div>

          <p className="dim" style={{ fontSize: '0.88rem', margin: '0.5rem 0 0.8rem' }}>
            Completati {completedCount} di {totalFilesCount} documenti.
          </p>

          <div style={{ height: '8px', background: 'var(--line)', borderRadius: '4px', overflow: 'hidden' }}>
            <div
              style={{
                height: '100%',
                width: `${totalFilesCount > 0 ? (completedCount / totalFilesCount) * 100 : 25}%`,
                background: 'var(--green)',
                transition: 'width 0.4s ease',
              }}
            ></div>
          </div>

          {isStale && (
            <div
              className="chip-neut"
              style={{
                marginTop: '1rem',
                padding: '0.6rem 0.9rem',
                borderRadius: '8px',
                fontSize: '0.84rem',
                display: 'block',
              }}
            >
              L’elaborazione sta richiedendo più tempo del previsto. Puoi attendere qui o ritrovare i
              risultati nello Storico non appena completati.
            </div>
          )}
        </div>
      )}

      {/* Drop-zone */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.jpg,.jpeg,.png,.webp,.bmp"
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />

      <div
        className={`drop ${isDragging ? 'over' : ''}`}
        tabIndex={0}
        role="button"
        aria-label="Trascina i file qui o clicca per selezionarli"
        onClick={() => fileInputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            fileInputRef.current?.click();
          }
        }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <span aria-hidden="true" style={{ display: 'inline-flex', color: 'var(--green-deep)' }}>
          <UploadIcon size={40} />
        </span>
        <h3 style={{ marginTop: '0.6rem' }}>Trascina i file qui</h3>
        <p>oppure clicca per selezionarli · max 20 alla volta</p>
      </div>

      {/* Lista file selezionati */}
      {selectedFiles.length > 0 && (
        <div className="uplist" style={{ textAlign: 'left' }}>
          {selectedFiles.map((file, idx) => (
            <div key={`${file.name}-${idx}`} className="uprow">
              <span className="chip chip-ok">
                <CheckIcon size={12} /> Pronto
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="name">{file.name}</div>
                <div className="size">{formatFileSize(file.size)}</div>
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-icon"
                onClick={() => handleRemoveFile(idx)}
                aria-label={`Rimuovi ${file.name}`}
                title={`Rimuovi ${file.name}`}
              >
                <CloseIcon size={18} />
              </button>
            </div>
          ))}
        </div>
      )}

      <p className="hint dim" style={{ textAlign: 'center' }}>
        Fino a 3 file l’estrazione è immediata (sincrona). Con più di 3 file parte un lavoro in
        secondo piano con avanzamento automatico.
      </p>

      {/* Azioni di invio */}
      <div style={{ display: 'flex', gap: '0.8rem', justifyContent: 'center', marginTop: '1.6rem' }}>
        <button
          className="btn btn-green"
          disabled={selectedFiles.length === 0 || isProcessing}
          onClick={handleExtract}
          style={{ minWidth: '160px' }}
        >
          {isProcessing ? (
            <>
              <SpinnerIcon size={18} /> Estrazione in corso...
            </>
          ) : (
            <>
              <UploadIcon size={18} /> Estrai ora ({selectedFiles.length})
            </>
          )}
        </button>

        {selectedFiles.length > 0 && (
          <button
            className="btn btn-ghost"
            disabled={isProcessing}
            onClick={() => setSelectedFiles([])}
          >
            Annulla
          </button>
        )}
      </div>
    </div>
  );
};
