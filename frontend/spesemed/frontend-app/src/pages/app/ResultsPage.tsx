import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useApp } from '../../context/AppContext';
import { CATEGORIE_SPESA, CategoriaSpesa, SpesaMedica } from '../../types/api';
import { CheckIcon, AlertCircleIcon, ArrowRightIcon } from '../../components/Icons';

export const ResultsPage: React.FC = () => {
  const { expenses, updateExpense, confirmExpense } = useApp();
  const [successNotice, setSuccessNotice] = useState<string | null>(null);

  // CF Validation Check (16 caratteri alfanumerici)
  const isCfValid = (cf: string | null) => {
    if (!cf) return false;
    return /^[A-Z0-9]{16}$/i.test(cf.trim());
  };

  const handleFieldChange = (
    id: string,
    field: keyof SpesaMedica,
    value: string | number | null
  ) => {
    updateExpense(id, { [field]: value });
  };

  const handleConfirm = (id: string) => {
    confirmExpense(id);
    setSuccessNotice('Spesa confermata e validata per il 730.');
    window.setTimeout(() => setSuccessNotice(null), 3000);
  };

  const handleSaveDraft = () => {
    setSuccessNotice('Modifiche salvate in bozza.');
    window.setTimeout(() => setSuccessNotice(null), 3000);
  };

  return (
    <div className="container" style={{ paddingTop: '2rem' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          flexWrap: 'wrap',
          gap: '0.8rem',
          marginBottom: '1.4rem',
        }}
      >
        <div>
          <span className="chip chip-ok" style={{ display: 'inline-flex' }}>
            {expenses.length} {expenses.length === 1 ? 'estratta' : 'estratte'}
          </span>
          <h2 style={{ marginTop: '0.4rem' }}>Risultati estrazione</h2>
        </div>
        <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
          <span className="chip chip-neut">Ogni campo si può correggere in un tocco</span>
          <Link to="/app/export" className="btn btn-green btn-sm">
            Vai all’esportazione <ArrowRightIcon size={14} />
          </Link>
        </div>
      </div>

      {successNotice && (
        <div
          className="chip-ok"
          style={{
            padding: '0.8rem 1.2rem',
            borderRadius: 'var(--radius-sm)',
            marginBottom: '1.4rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            fontWeight: 600,
          }}
        >
          <CheckIcon size={16} />
          <span>{successNotice}</span>
        </div>
      )}

      {expenses.length === 0 ? (
        <div className="surface" style={{ padding: '3rem 2rem', textAlign: 'center' }}>
          <h3>Nessuna spesa da mostrare</h3>
          <p className="dim" style={{ margin: '0.6rem 0 1.5rem' }}>
            Carica le tue ricevute o scontrini per visualizzare i risultati estratti.
          </p>
          <Link to="/app/upload" className="btn btn-green">
            Carica subito una ricevuta
          </Link>
        </div>
      ) : (
        expenses.map((spesa, index) => {
          const id = spesa.id || `idx-${index}`;
          const cfOk = isCfValid(spesa.codice_fiscale_paziente);
          const isValidated = spesa.status === 'validated';

          return (
            <div
              key={id}
              className="surface"
              style={{
                padding: '1.4rem 1.6rem',
                marginBottom: '1.4rem',
                backgroundColor: '#ffffff',
              }}
            >
              {/* Header Card Spesa */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  flexWrap: 'wrap',
                  gap: '0.6rem',
                }}
              >
                <div>
                  <div style={{ fontWeight: 800, fontSize: '1.15rem' }}>
                    {spesa.esercente || 'Esercente non riconosciuto'}
                  </div>
                  <div className="meta dim" style={{ fontSize: '0.85rem' }}>
                    {spesa.source_file_name || `documento-${index + 1}.pdf`}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                  {cfOk ? (
                    <span className="chip chip-ok">
                      <CheckIcon size={13} /> CF verificato
                    </span>
                  ) : (
                    <span className="chip chip-run">
                      <AlertCircleIcon size={13} /> CF da verificare
                    </span>
                  )}
                  {isValidated ? (
                    <span className="chip chip-ok">
                      <CheckIcon size={13} /> Confermato
                    </span>
                  ) : (
                    <span className="chip chip-run">● In attesa di conferma</span>
                  )}
                </div>
              </div>

              {/* Form di modifica */}
              <div className="two" style={{ marginTop: '1.2rem' }}>
                <div className="field">
                  <label htmlFor={`data-${id}`}>Data spesa (AAAA-MM-GG)</label>
                  <input
                    id={`data-${id}`}
                    type="date"
                    className="in"
                    value={spesa.data_spesa || ''}
                    onChange={(e) => handleFieldChange(id, 'data_spesa', e.target.value)}
                  />
                </div>

                <div className="field">
                  <label htmlFor={`cat-${id}`}>Categoria detrazione</label>
                  <select
                    id={`cat-${id}`}
                    className="in"
                    value={spesa.categoria_spesa}
                    onChange={(e) =>
                      handleFieldChange(id, 'categoria_spesa', e.target.value as CategoriaSpesa)
                    }
                  >
                    {CATEGORIE_SPESA.map((cat) => (
                      <option key={cat} value={cat}>
                        {cat}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="two">
                <div className="field">
                  <label htmlFor={`imp-${id}`}>Importo totale (€)</label>
                  <input
                    id={`imp-${id}`}
                    type="number"
                    step="0.01"
                    min="0"
                    className="in"
                    value={spesa.importo_totale ?? ''}
                    onChange={(e) => {
                      const val = e.target.value === '' ? null : parseFloat(e.target.value);
                      handleFieldChange(id, 'importo_totale', val);
                    }}
                  />
                </div>

                <div className="field">
                  <label htmlFor={`cf-${id}`}>Codice fiscale paziente</label>
                  <input
                    id={`cf-${id}`}
                    type="text"
                    maxLength={16}
                    className="in mono"
                    style={{ textTransform: 'uppercase' }}
                    value={spesa.codice_fiscale_paziente || ''}
                    onChange={(e) =>
                      handleFieldChange(id, 'codice_fiscale_paziente', e.target.value.toUpperCase())
                    }
                  />
                </div>
              </div>

              <div className="field">
                <label htmlFor={`esercente-${id}`}>Ragione sociale / Esercente</label>
                <input
                  id={`esercente-${id}`}
                  type="text"
                  className="in"
                  value={spesa.esercente || ''}
                  onChange={(e) => handleFieldChange(id, 'esercente', e.target.value)}
                />
              </div>

              {/* Bottoni di conferma */}
              <div
                style={{
                  display: 'flex',
                  gap: '0.6rem',
                  flexWrap: 'wrap',
                  justifyContent: 'flex-end',
                  marginTop: '0.8rem',
                }}
              >
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={handleSaveDraft}
                >
                  Salva bozza
                </button>
                <button
                  type="button"
                  className="btn btn-green btn-sm"
                  onClick={() => handleConfirm(id)}
                >
                  <CheckIcon size={14} /> Conferma spesa
                </button>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
};
