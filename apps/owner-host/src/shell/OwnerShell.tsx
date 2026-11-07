import { NavLink, Outlet } from "react-router";
import { AREAS } from "../areas";
import { SessionIdentity } from "../identity/SessionIdentity";
import { useShellLayout } from "./layout";

/**
 * The persistent frame around every area: product name, session identity and
 * area navigation. It stays mounted across navigation; only the outlet changes.
 */
export function OwnerShell() {
  const layout = useShellLayout();
  const narrow = layout === "narrow";
  return (
    <div className="owner-shell" data-layout={layout} data-testid="owner-shell">
      <header className="owner-shell__header">
        <span className="owner-shell__brand">AI Engineering</span>
        <SessionIdentity compact={narrow} />
      </header>
      <nav className="owner-shell__nav" aria-label="Owner areas">
        <ul className="owner-nav" aria-orientation={narrow ? "horizontal" : "vertical"}>
          {AREAS.map((area) => (
            <li key={area.id} className="owner-nav__item">
              <NavLink
                to={area.path}
                className={({ isActive }) => (isActive ? "owner-nav__link owner-nav__link--active" : "owner-nav__link")}
              >
                <span className="owner-nav__label">{area.label}</span>
                {narrow ? null : <span className="owner-nav__summary">{area.summary}</span>}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main className="owner-shell__main" id="owner-main">
        <Outlet />
      </main>
    </div>
  );
}
