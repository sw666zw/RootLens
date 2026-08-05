import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/app-shell";
import { DashboardPage } from "./pages/dashboard-page";
import { DiagnosesPage } from "./pages/diagnoses-page";
import { DiagnosisDetailPage } from "./pages/diagnosis-detail-page";
import { ExplanationDetailPage } from "./pages/explanation-detail-page";
import { ExplanationsPage } from "./pages/explanations-page";
import { IncidentDetailPage } from "./pages/incident-detail-page";
import { IncidentsPage } from "./pages/incidents-page";
import { NotFoundPage } from "./pages/not-found-page";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:scenarioId" element={<IncidentDetailPage />} />
        <Route path="diagnoses" element={<DiagnosesPage />} />
        <Route
          path="diagnoses/:diagnosisId"
          element={<DiagnosisDetailPage />}
        />
        <Route path="explanations" element={<ExplanationsPage />} />
        <Route
          path="explanations/:explanationId"
          element={<ExplanationDetailPage />}
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
