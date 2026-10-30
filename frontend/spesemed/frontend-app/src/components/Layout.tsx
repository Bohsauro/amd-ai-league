import React from 'react';
import { NavLink, Outlet, Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export const Layout: React.FC = () => {
  const { userEmail } = useAuth();
  const location = useLocation();
  const isProfileRoute =
    location.pathname === '/app/profile' || location.pathname === '/app/profilo';

  // Genera iniziali dall'email o nome
  const getInitials = (email: string) => {
    if (!email) return 'SM';
    const parts = email.split('@')[0].split(/[._-]/);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return email.slice(0, 2).toUpperCase();
  };

  const initials = getInitials(userEmail);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <header className="app-header">
        <div className="container app-bar">
          <Link to="/app/dashboard" className="brand" aria-label="SPESEMED Home">
            <span className="mark" aria-hidden="true"></span>
            SPESEMED
          </Link>

          <nav className="app-nav" aria-label="Navigazione applicazione">
            <NavLink
              to="/app/dashboard"
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              Dashboard
            </NavLink>
            <NavLink
              to="/app/upload"
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              Carica
            </NavLink>
            <NavLink
              to="/app/results"
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              Risultati
            </NavLink>
            <NavLink
              to="/app/jobs"
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              Storico
            </NavLink>
            <NavLink
              to="/app/export"
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              Esporta
            </NavLink>
            <NavLink
              to="/app/profile"
              className={() => (isProfileRoute ? 'active' : '')}
            >
              Profilo
            </NavLink>
          </nav>

          <Link
            to="/app/profile"
            className="user-chip"
            style={{ textDecoration: 'none' }}
            title="Visualizza profilo"
          >
            <span className="av" aria-hidden="true">
              {initials}
            </span>
            <span>{userEmail.split('@')[0]}</span>
          </Link>
        </div>
      </header>

      <main style={{ flex: 1, paddingBottom: '3rem' }}>
        <Outlet />
      </main>

      <footer className="foot" style={{ marginTop: 'auto', borderTop: '1px solid var(--line)', padding: '1.5rem 0' }}>
        <div className="container" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', fontSize: '0.88rem', color: 'var(--ink-3)' }}>
          <div>SPESEMED · Gestione spese mediche conforme GDPR</div>
          <div style={{ display: 'flex', gap: '1.2rem' }}>
            <Link to="/" style={{ color: 'var(--ink-3)' }}>Landing</Link>
            <Link to="/app/export" style={{ color: 'var(--ink-3)' }}>Esporta</Link>
            <Link to="/app/profile" style={{ color: 'var(--ink-3)' }}>Profilo</Link>
          </div>
        </div>
      </footer>
    </div>
  );
};
