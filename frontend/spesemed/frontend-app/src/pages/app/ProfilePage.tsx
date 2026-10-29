import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import {
  LogoutIcon,
  RefreshIcon,
  SpinnerIcon,
  CheckIcon,
  AlertCircleIcon,
  ShieldCheckIcon,
  LockIcon,
} from '../../components/Icons';

export const ProfilePage: React.FC = () => {
  const { session, userEmail, userId, logout, refreshToken } = useAuth();
  const navigate = useNavigate();

  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [notice, setNotice] = useState<{ text: string; error?: boolean } | null>(null);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    setNotice(null);
    try {
      await refreshToken();
      setNotice({ text: 'Sessione rinnovata. La tua protezione è aggiornata.' });
    } catch {
      setNotice({ text: 'Impossibile rinnovare la sessione. Effettua nuovamente l’accesso.', error: true });
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleLogout = async () => {
    setIsLoggingOut(true);
    try {
      await logout();
      navigate('/login', { replace: true });
    } finally {
      setIsLoggingOut(false);
    }
  };

  const formatExpires = () => {
    if (!session?.expiresAt) return 'Sessione attiva';
    const diff = session.expiresAt - Date.now();
    if (diff <= 0) return 'In scadenza';
    const minutes = Math.floor(diff / 60_000);
    return `Valido per circa ${minutes} minuti`;
  };

  return (
    <div className="container ctr" style={{ paddingTop: '2.5rem' }}>
      <span className="chip chip-neut" style={{ marginBottom: '1rem', display: 'inline-flex' }}>
        Profilo e sicurezza
      </span>
      <h2 style={{ margin: '0.4rem 0 0.6rem' }}>Gestione account</h2>
      <p className="dim" style={{ marginBottom: '2rem' }}>
        Dati di autenticazione, sicurezza della sessione e stato dell’archivio privato.
      </p>

      {notice && (
        <div
          className={notice.error ? 'banner banner-err' : 'banner banner-ok'}
          style={{ marginBottom: '1.4rem' }}
          role={notice.error ? 'alert' : 'status'}
        >
          {notice.error ? <AlertCircleIcon size={16} /> : <CheckIcon size={16} />}
          <span>{notice.text}</span>
        </div>
      )}

      {/* Scheda Utente */}
      <div className="surface" style={{ padding: '1.8rem', backgroundColor: 'var(--bg)', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
          <div
            style={{
              width: '54px',
              height: '54px',
              borderRadius: '50%',
              backgroundColor: 'var(--green)',
              color: 'var(--green-deep)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 800,
              fontSize: '1.25rem',
            }}
          >
            {userEmail.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: '1.15rem' }}>{userEmail}</div>
            <div className="mono dim" style={{ fontSize: '0.82rem', marginTop: '0.2rem' }}>
              ID: {userId || 'sessione-locale'}
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gap: '0.9rem', borderTop: '1px solid var(--line)', paddingTop: '1.2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.92rem', color: 'var(--ink-2)' }}>Stato sessione</span>
            <span className="chip chip-ok">
              <CheckIcon size={12} /> Autenticato
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.92rem', color: 'var(--ink-2)' }}>Scadenza token</span>
            <span className="mono dim" style={{ fontSize: '0.88rem' }}>
              {formatExpires()}
            </span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.92rem', color: 'var(--ink-2)' }}>Archivio Storage</span>
            <span className="chip chip-neut" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
              <LockIcon size={12} /> Bucket privato cifrato
            </span>
          </div>
        </div>

        {/* Azioni sessione */}
        <div style={{ marginTop: '1.8rem', display: 'flex', gap: '0.8rem', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={handleRefresh}
            disabled={isRefreshing}
          >
            {isRefreshing ? (
              <>
                <SpinnerIcon size={14} /> Rinnovo...
              </>
            ) : (
              <>
                <RefreshIcon size={14} /> Rinnova sessione
              </>
            )}
          </button>

          <button
            type="button"
            className="btn btn-danger btn-sm"
            onClick={handleLogout}
            disabled={isLoggingOut}
            style={{ marginLeft: 'auto' }}
          >
            {isLoggingOut ? (
              <>
                <SpinnerIcon size={14} /> Uscita...
              </>
            ) : (
              <>
                <LogoutIcon size={14} /> Esci dall’account
              </>
            )}
          </button>
        </div>
      </div>

      {/* Box Informazioni di Sicurezza */}
      <div className="band" style={{ borderRadius: 'var(--radius)', padding: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700, fontSize: '0.95rem' }}>
          <ShieldCheckIcon size={18} style={{ color: 'var(--success)' }} />
          <span>Garanzia di riservatezza SPESEMED</span>
        </div>
        <p className="dim" style={{ fontSize: '0.86rem', marginTop: '0.5rem', lineHeight: '1.6' }}>
          Ogni accesso è protetto da credenziali che si rinnovano automaticamente. I documenti medici e
          gli scontrini restano in un archivio privato, accessibile solo a te. Nessun dato viene venduto
          o usato da terzi.
        </p>
      </div>
    </div>
  );
};
