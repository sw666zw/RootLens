import { NavLink, Outlet } from "react-router-dom";
import { ExternalToolLinks } from "./external-tool-links";

const navigation = [
  { to: "/", label: "Overview", symbol: "⌂" },
  { to: "/incidents", label: "Incidents", symbol: "!" },
  { to: "/diagnoses", label: "Diagnoses", symbol: "◎" },
  { to: "/explanations", label: "Explanations", symbol: "≋" },
];

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
          <span className="nav-symbol" aria-hidden="true">
            {item.symbol}
          </span>
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
        <NavLink to="/" className="brand" aria-label="RootLens overview">
          <span className="brand-mark" aria-hidden="true">
            R
          </span>
          <span>
            <strong>RootLens</strong>
            <small>Diagnosis console</small>
          </span>
        </NavLink>
        <Navigation />
        <div className="sidebar-tools">
          <p className="eyebrow">External tools</p>
          <ExternalToolLinks compact />
        </div>
      </aside>
      <header className="mobile-header">
        <NavLink to="/" className="brand" aria-label="RootLens overview">
          <span className="brand-mark" aria-hidden="true">
            R
          </span>
          <strong>RootLens</strong>
        </NavLink>
        <Navigation />
      </header>
      <main id="main-content" className="main-content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
