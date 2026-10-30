import React from 'react';
import { LockIcon, ShieldCheckIcon } from './Icons';

export const TrustBadgePrivacy: React.FC<{ className?: string }> = ({ className = '' }) => (
  <span className={`chip chip-neut ${className}`} style={{ fontWeight: 700, letterSpacing: '0.04em' }}>
    <LockIcon size={14} /> Dati medici crittografati · Bucket privato
  </span>
);

export const TrustPointsHero: React.FC = () => (
  <div className="hero-trust" aria-label="Punti di fiducia" style={{
    display: 'flex',
    flexWrap: 'wrap',
    gap: '0.6rem 1.4rem',
    marginTop: '1.6rem',
    color: 'var(--ink-3)',
    fontSize: '0.9rem',
    fontWeight: 600,
  }}>
    <span style={{ display: 'inline-flex', gap: '0.4rem', alignItems: 'center' }}>
      <ShieldCheckIcon size={17} style={{ color: 'var(--success)', flexShrink: 0 }} /> Nessuna ricevuta resa pubblica
    </span>
    <span style={{ display: 'inline-flex', gap: '0.4rem', alignItems: 'center' }}>
      <ShieldCheckIcon size={17} style={{ color: 'var(--success)', flexShrink: 0 }} /> Codice fiscale validato
    </span>
    <span style={{ display: 'inline-flex', gap: '0.4rem', alignItems: 'center' }}>
      <ShieldCheckIcon size={17} style={{ color: 'var(--success)', flexShrink: 0 }} /> Export pronto per il 730
    </span>
  </div>
);
