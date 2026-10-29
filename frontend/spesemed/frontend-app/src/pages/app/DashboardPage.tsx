import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../lib/api';
import { useApp } from '../../context/AppContext';
import { JobListItem, UsageSummaryResponse } from '../../types/api';
import { CheckIcon, SpinnerIcon, ArrowRightIcon, UploadIcon } from '../../components/Icons';
import { TrustBadgePrivacy } from '../../components/TrustBadges';

export const DashboardPage: React.FC = () => {
  const { expenses, summaryRefreshTrigger } = useApp();
  const [summary, setSummary] = useState<UsageSummaryResponse | null>(null);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isOffline, setIsOffline] = useState<boolean>(false);

  useEffect(() => {
    let isMounted = true;

    async function loadDashboardData() {
      setIsLoading(true);
      let summaryOk = false;
      let jobsOk = false;

      // Carica summary dal backend (se disponibile)
      try {
        const sumData = await api.getSummary();
        if (isMounted) setSummary(sumData);
        summaryOk = true;
      } catch {
        // Backend non raggiungibile o Supabase non configurato: resta il riepilogo locale
      }

      // Carica jobs recenti
      try {
        const jobList = await api.listJobs(5, 0);
        if (isMounted) setJobs(jobList.jobs);
        jobsOk = true;
      } catch {
        // Nessuno storico disponibile: resta lo stato locale
      }

      if (isMounted) {
        setIsOffline(!summaryOk && !jobsOk);
        setIsLoading(false);
      }
    }

    loadDashboardData();

    return () => {
      isMounted = false;
    };
  }, [summaryRefreshTrigger]);

  // Calcola aggregato locale come fallback trasparente
  const localTotal = expenses.reduce((acc, curr) => acc + (curr.importo_totale || 0), 0);
  const localCount = expenses.length;

  const totalAmount = summary ? summary.totale_importo : localTotal;
  const totalCount = summary ? summary.total_spese : localCount;

  // Categorie aggregate
  const catCounts: Record<string, number> = {};
  if (summary && summary.per_categoria.length > 0) {
    summary.per_categoria.forEach((c) => {
      catCounts[c.categoria] = c.count;
    });
  } else {
    expenses.forEach((e) => {
      catCounts[e.categoria_spesa] = (catCounts[e.categoria_spesa] || 0) + 1;
    });
  }

  const formatEuro = (val: number) => {
    return new Intl.NumberFormat('it-IT', {
      style: 'currency',
      currency: 'EUR',
      minimumFractionDigits: 2,
    }).format(val);
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Data da verificare';
    try {
      const parts = dateStr.split('-');
      if (parts.length === 3) {
        const d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric' });
      }
    } catch {
      // ignore
    }
    return dateStr;
  };

  return (
    <div className="container" style={{ paddingTop: '2rem' }}>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
        <TrustBadgePrivacy />
      </div>

      {/* Banda Riepilogo */}
      <div className="sumband">
        <div className="top">
          <div>
            <div className="label">Totale spese esportabili</div>
            <div className="big">
              {formatEuro(totalAmount)}{' '}
              <small>· {totalCount} {totalCount === 1 ? 'spesa' : 'spese'}</small>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
            <Link to="/app/upload" className="btn btn-green btn-sm">
              <UploadIcon size={16} /> Carica nuove
            </Link>
          </div>
        </div>

        <div className="cats" aria-label="Spese per categoria">
          <span className="chip chip-ok">Farmaci · {catCounts['Farmaci'] || 0}</span>
          <span className="chip chip-neut">Visite · {catCounts['Visita Specialistica'] || 0}</span>
          <span className="chip chip-neut">Esami · {catCounts['Esami'] || 0}</span>
          <span className="chip chip-neut">Dispositivi · {catCounts['Dispositivo Medico'] || 0}</span>
          <span className="chip chip-neut">Altro · {catCounts['Altro'] || 0}</span>
        </div>

        <p className="note">
          Tutti gli importi vengono aggregati in automatico per il 730 e le detrazioni sanitarie.
        </p>
      </div>

      {isOffline && (
        <div className="banner banner-info" style={{ marginTop: '1rem' }} role="status">
          <span>
            Server non raggiungibile: mostriamo le spese salvate su questo browser. Ricarica quando la
            connessione è attiva.
          </span>
        </div>
      )}

      {/* Griglia a 2 colonne: Ultime spese + Job recenti */}
      <div className="dashgrid">
        {/* Colonna Sinistra: Ultime Spese */}
        <div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'baseline',
              marginBottom: '0.6rem',
            }}
          >
            <h3 style={{ fontSize: '1.2rem' }}>Ultime spese registrate</h3>
            <Link to="/app/results" style={{ fontSize: '0.9rem', display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}>
              Modifica e valida →
            </Link>
          </div>

          <div className="surface" style={{ padding: '0.2rem 1.4rem' }}>
            {expenses.length === 0 ? (
              <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--ink-3)' }}>
                Nessuna spesa presente. Carica la prima ricevuta per iniziare.
              </div>
            ) : (
              expenses.slice(0, 5).map((spesa, idx) => (
                <div key={spesa.id || idx} className="seg">
                  <div>
                    <div className="who">{spesa.esercente || 'Esercente da specificare'}</div>
                    <div className="meta">
                      {formatDate(spesa.data_spesa)} · {spesa.categoria_spesa}
                    </div>
                  </div>
                  <div className="right">
                    <span className="amt">{formatEuro(spesa.importo_totale || 0)}</span>
                    {spesa.status === 'validated' ? (
                      <span className="chip chip-ok">
                        <CheckIcon size={13} /> Validato
                      </span>
                    ) : (
                      <span className="chip chip-run">
                        <i className="dot" aria-hidden="true"></i> In attesa
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Colonna Destra: Job Recenti */}
        <div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'baseline',
              marginBottom: '0.6rem',
            }}
          >
            <h3 style={{ fontSize: '1.2rem' }}>Lavori recenti</h3>
            <Link to="/app/jobs" style={{ fontSize: '0.9rem' }}>
              Tutto lo storico →
            </Link>
          </div>

          <div className="surface" style={{ padding: '0.8rem 1.2rem' }}>
            {isLoading ? (
              <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--ink-3)' }}>
                <SpinnerIcon size={20} /> Caricamento storico...
              </div>
            ) : jobs.length > 0 ? (
              jobs.map((j) => (
                <div key={j.job_id} style={{ padding: '0.6rem 0', borderBottom: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <b style={{ fontSize: '0.92rem' }}>
                      {j.file_count} {j.file_count === 1 ? 'ricevuta' : 'ricevute'}
                    </b>
                    <span
                      className={`chip ${
                        j.status === 'done'
                          ? 'chip-ok'
                          : j.status === 'failed'
                          ? 'chip-err'
                          : 'chip-run'
                      }`}
                    >
                      {j.status === 'done' ? (
                        'Fatto'
                      ) : j.status === 'failed' ? (
                        'Errore'
                      ) : (
                        <>
                          <i className="dot" aria-hidden="true"></i> In corso
                        </>
                      )}
                    </span>
                  </div>
                  <div className="meta" style={{ fontSize: '0.82rem', color: 'var(--ink-3)', marginTop: '0.2rem' }}>
                    {j.created_at ? new Date(j.created_at).toLocaleString('it-IT') : 'Recente'}
                  </div>
                </div>
              ))
            ) : (
              <div style={{ padding: '1.6rem 0.5rem', textAlign: 'center', color: 'var(--ink-3)' }}>
                Nessun lavoro presente. Carica la prima ricevuta per iniziare.
              </div>
            )}
          </div>

          {/* Quick CTA Box */}
          <div className="band" style={{ borderRadius: 'var(--radius)', padding: '1.2rem', marginTop: '1.2rem' }}>
            <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>Pronto per il commercialista?</div>
            <p className="dim" style={{ fontSize: '0.86rem', margin: '0.3rem 0 0.8rem' }}>
              Genera l’archivio ZIP con l’Excel riepilogativo e le ricevute rinominate.
            </p>
            <Link to="/app/export" className="btn btn-ghost btn-sm btn-block">
              Vai alla pagina Esporta <ArrowRightIcon size={14} />
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
};
