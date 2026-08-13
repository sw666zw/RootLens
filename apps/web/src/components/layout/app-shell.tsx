import { NavLink, Outlet } from "react-router-dom";
import { ExternalToolLinks } from "./external-tool-links";

const navigation = [
  { to: "/", label: "Overview" },
  { to: "/incidents", label: "Incidents" },
  { to: "/diagnoses", label: "Diagnoses" },
  { to: "/explanations", label: "Explanations" },
];

function Brand() {
  return (
    <NavLink to="/" className="brand" aria-label="RootLens overview">
      <span className="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 40 40" focusable="false">
          <circle className="brand-lens" cx="15.5" cy="15.5" r="11.5" />
          <path className="brand-handle" d="m23.8 23.8 6.6 6.6" />
          <path
            className="brand-graph"
            d="M14.4 11.3c.1 1.7.1 2.9-.3 4.1m0 0c.3 2.8-.1 5.7-.7 8.6m.7-8.6c-1.5 1.4-2.7 3.3-3.4 6.2m.4-1.1c-1.1.3-1.8 1-2.3 1.8m5.3-6.9c2.1 1.2 3.7 3 4.6 6.4"
          />
          <circle
            className="brand-node brand-node-accent"
            cx="14.3"
            cy="9.7"
            r="1.55"
          />
        </svg>
      </span>
      <span className="brand-type">
        <strong>RootLens</strong>
        <small>Incident intelligence</small>
      </span>
    </NavLink>
  );
}

function Navigation() {
  return (
    <nav aria-label="Primary navigation" className="primary-nav">
      {navigation.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          className={({ isActive }) =>
            isActive ? "nav-link active" : "nav-link"
          }
        >
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <Brand />
        <p className="nav-section-label">Workspace</p>
        <Navigation />
        <div className="sidebar-tools">
          <p className="eyebrow">External tools</p>
          <ExternalToolLinks compact />
        </div>
      </aside>
      <header className="mobile-header">
        <Brand />
        <Navigation />
      </header>
      <main id="main-content" className="main-content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
