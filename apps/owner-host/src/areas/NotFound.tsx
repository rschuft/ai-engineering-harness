import { Link } from "react-router";
import { AREAS } from "../areas";

export function NotFound() {
  return (
    <section className="owner-area" aria-labelledby="not-found-heading" data-testid="area-not-found">
      <h2 id="not-found-heading" className="owner-area__title">
        Page not found
      </h2>
      <p>This address is not an area of the Owner host. Choose an area:</p>
      <ul>
        {AREAS.map((area) => (
          <li key={area.id}>
            <Link to={area.path}>{area.label}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
