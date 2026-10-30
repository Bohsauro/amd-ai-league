import React, { useState } from 'react';
import { api, ApiError } from '../../lib/api';
import { useApp } from '../../context/AppContext';
import { SpinnerIcon, DownloadIcon, AlertCircleIcon, CheckIcon } from '../../components/Icons';

export const ExportPage: React.FC = () => {
  const { expenses } = useApp();
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const handleExportAll = async () => {
    setIsExporting(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      const { blob, filename } = await api.exportZip();

      // Trigger del download del file nel browser
      const blobUrl = window.URL.createObjectURL(blob);
      const tempLink = document.createElement('a');
      tempLink.href = blobUrl;
      tempLink.download = filename || 'spesemed_export.zip';
      document.body.appendChild(tempLink);
      tempLink.click();
      document.body.removeChild(tempLink);
      window.URL.revokeObjectURL(blobUrl);

      setSuccessMsg('Archivio scaricato: trovi il file ZIP tra i download del browser.');
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 400) {
          setErrorMsg('Nessuna estrazione presente da esportare. Carica prima una ricevuta.');
        } else if (err.status === 503) {
          setErrorMsg('Archivio Storage non configurato sul server backend.');
        } else {
          setErrorMsg(err.detail);
        }
      } else {
        setErrorMsg('Errore di comunicazione durante la generazione dell’archivio.');
      }
    } finally {
      setIsExporting(false);
    }
  };

  // Helper per generare l'anteprima del nome file normalizzato
  const getPreviewFilename = (data: string | null, esercente: string | null, importo: number | null, cat: string) => {
    const d = data || '2026-00-00';
    const es = (esercente || 'Esercente')
      .replace(/[^a-zA-Z0-9]/g, '-')
      .replace(/-+/g, '-')
      .slice(0, 20);
    const imp = (importo ?? 0).toFixed(2);
    const catCode = cat.slice(0, 3).toUpperCase();
    return `${d}_${es}_${imp}EUR_${catCode}.pdf`;
  };

  return (
    <div className="container" style={{ paddingTop: '2.5rem' }}>
      <span className="chip chip-neut" style={{ marginBottom: '1rem', display: 'inline-flex' }}>
        Esporta per il commercialista
      </span>
      <h2 style={{ margin: '0.4rem 0 0.8rem' }}>Scarica l’archivio già in ordine.</h2>
      <p className="lead" style={{ maxWidth: '680px', marginBottom: '2rem' }}>
        Ricevi un foglio Excel riepilogativo e uno ZIP con le ricevute rinominate col formato che serve
        per il 730, il CAF o la tua assicurazione sanitaria.
      </p>

      {errorMsg && (
        <div
          className="banner banner-err"
          style={{ marginBottom: '1.5rem', maxWidth: '820px' }}
          role="alert"
        >
          <AlertCircleIcon size={18} />
          <span>{errorMsg}</span>
        </div>
      )}

      {successMsg && (
        <div
          className="banner banner-ok"
          style={{ marginBottom: '1.5rem', maxWidth: '820px' }}
          role="status"
        >
          <CheckIcon size={18} />
          <span>{successMsg}</span>
        </div>
      )}

      <div className="export">
        <div className="exportgrid">
          {/* Card Cosa Ottieni */}
          <div className="surface" style={{ padding: '1.8rem', backgroundColor: 'var(--bg)' }}>
            <h3 style={{ fontSize: '1.15rem' }}>Cosa ottieni</h3>
            <div style={{ marginTop: '1.2rem', display: 'grid', gap: '1rem' }}>
              <div>
                <b style={{ display: 'block', marginBottom: '0.2rem' }}>Excel riepilogativo (.xlsx)</b>
                <div className="dim" style={{ fontSize: '0.92rem' }}>
                  Un foglio con l’elenco cronologico e un foglio con i totali suddivisi per categoria
                  fiscale.
                </div>
              </div>
              <div>
                <b style={{ display: 'block', marginBottom: '0.2rem' }}>ZIP con ricevute rinominate</b>
                <div className="dim" style={{ fontSize: '0.92rem' }}>
                  Ogni file pronto da allegare al 730 senza dover rinominare nulla a mano.
                </div>
              </div>
              <div className="meta dim" style={{ fontSize: '0.84rem' }}>
                Formato standard:{' '}
                <span className="mono" style={{ color: 'var(--ink)' }}>
                  YYYY-MM-DD_esercente_importoCAT.ext
                </span>
              </div>
            </div>

            <button
              className="btn btn-green btn-block"
              onClick={handleExportAll}
              disabled={isExporting}
              style={{ marginTop: '1.6rem' }}
            >
              {isExporting ? (
                <>
                  <SpinnerIcon size={18} /> Generazione ZIP in corso...
                </>
              ) : (
                <>
                  <DownloadIcon size={18} /> Scarica export completo (ZIP)
                </>
              )}
            </button>
          </div>

          {/* Anteprima Nomi File */}
          <div className="band" style={{ borderRadius: 'var(--radius)', padding: '1.6rem' }}>
            <span className="tag">Anteprima nomi file generati</span>
            <div className="pret" style={{ marginTop: '0.8rem' }}>
              {expenses.length > 0 ? (
                expenses.slice(0, 4).map((e, idx) => {
                  const name = getPreviewFilename(
                    e.data_spesa,
                    e.esercente,
                    e.importo_totale,
                    e.categoria_spesa
                  );
                  const parts = name.split('_');
                  return (
                    <div key={idx} style={{ marginBottom: '0.25rem' }}>
                      <b>{parts[0]}</b>_{parts[1]}
                      <span className="g">_{parts[2]}_{parts[3]}</span>
                    </div>
                  );
                })
              ) : (
                <>
                  <b>2026-03-15</b>_Farmacia-Centrale<span className="g">_42.80EUR_FAR</span>.pdf<br />
                  <b>2026-04-02</b>_Studio-Dentistico<span className="g">_210.00EUR_VIS</span>.pdf<br />
                  <b>2026-05-18</b>_Lab-Analisi-Verdi<span className="g">_88.50EUR_ESA</span>.png<br />
                  <b>2026-06-30</b>_Ottica-Sole<span className="g">_154.99EUR_DIS</span>.pdf
                </>
              )}
            </div>
            <p className="dim" style={{ fontSize: '0.82rem', marginTop: '0.8rem' }}>
              I nomi sono conformi ai requisiti dei principali software gestionali di commercialisti e CAF.
            </p>
          </div>
        </div>

        <p className="dim" style={{ marginTop: '1.8rem', fontSize: '0.88rem' }}>
          L’archivio viene preparato in automatico dal tuo archivio privato: nessun riordino manuale.
          Ogni download riguarda solo i dati del tuo account.
        </p>
      </div>
    </div>
  );
};
