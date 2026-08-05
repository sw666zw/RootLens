import { Link } from "react-router-dom";
import { PageHeader } from "../components/layout/page-header";

export function NotFoundPage() {
  return (
    <div className="page not-found">
      <PageHeader
        eyebrow="404"
        title="Page not found"
        description="The requested RootLens view does not exist."
      />
      <Link className="primary-button" to="/">
        Return to overview
      </Link>
    </div>
  );
}
