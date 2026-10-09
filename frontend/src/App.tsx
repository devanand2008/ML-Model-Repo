import AuthGate from "./components/AuthGate";
import { lazy, Suspense } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import WebcamPage from "./pages/WebcamPage";
import HomePage from "./pages/HomePage";
import ImageAnalyzerPage from "./pages/ImageAnalyzerPage";
import HumanAnalyzerPage from "./pages/HumanAnalyzerPage";
import ShipAnalyzerPage from "./pages/ShipAnalyzerPage";
import ContainerAnalyzerPage from "./pages/ContainerAnalyzerPage";
import CombinedAnalyzerPage from "./pages/CombinedAnalyzerPage";
import VideoAnalyzerPage from "./pages/VideoAnalyzerPage";
import ModelCenterPage from "./pages/ModelCenterPage";
import HistoryPage from "./pages/HistoryPage";
import TransitLayout from "./components/transit/TransitLayout";
import { DashboardPage, OptimizationPage, SimulatorPage, NetworkPage, RecommendationsPage } from "./pages/transit/OperationsPages";
import DemandPage from "./pages/transit/DemandPage";
import CCTVPage from "./pages/transit/CCTVPage";
import AnalyticsPage from "./pages/transit/AnalyticsPage";
import SettingsPage from "./pages/transit/SettingsPage";
import ProjectPage from "./pages/transit/ProjectPage";
import { DemoRecorderProvider } from './components/DemoRecorder';
import { ThemeProvider } from './context/ThemeContext';
import ModuleErrorBoundary from './components/ModuleErrorBoundary';
import HostingStatus from './components/HostingStatus';

const PassengerPage = lazy(() => import("./pages/transit/PassengerPage"));
const DriverPage = lazy(() => import("./pages/transit/DriverPage"));
const FleetPage = lazy(() => import("./pages/transit/MobilityPages").then(module => ({ default: module.FleetPage })));
const SafetyPage = lazy(() => import("./pages/transit/MobilityPages").then(module => ({ default: module.SafetyPage })));
const AccountsPage = lazy(() => import("./pages/transit/AccountsPage"));
const AppHomePage = lazy(() => import("./pages/transit/AppHomePage"));
const MLWorkspacePage = lazy(() => import("./pages/transit/MLWorkspacePage"));
const ConnectDevicePage = lazy(() => import("./pages/transit/ConnectDevicePage"));
const RecordDemoPage = lazy(() => import('./pages/transit/RecordDemoPage'));
const BusSpeedPage = lazy(() => import('./pages/transit/BusSpeedPage'));
const RouteRagPage = lazy(() => import('./pages/transit/RouteRagPage'));
const AppStatusPage = lazy(() => import('./pages/transit/AppStatusPage'));
const RecordedSamplePage = lazy(() => import('./pages/transit/RecordDemoPage').then(m=>({default:m.RecordedSamplePage})));

export default function App() {
  return (
    <ThemeProvider><HostingStatus /><DemoRecorderProvider><ModuleErrorBoundary><Suspense fallback={<div role="status" style={{ padding: 32 }}>Loading TransitOpt…</div>}><Routes>
      <Route index element={<AppHomePage />} />
      <Route path="connect" element={<ConnectDevicePage />} />
      <Route path="passenger" element={<PassengerPage />} />
      <Route path="driver" element={<DriverPage />} />
      <Route element={<AuthGate><TransitLayout /></AuthGate>}>
        <Route path="admin" element={<DashboardPage />} />
        <Route path="ml" element={<MLWorkspacePage />} />
        <Route path="speed" element={<BusSpeedPage />} />
        <Route path="rag" element={<RouteRagPage />} />
        <Route path="status" element={<AppStatusPage />} />
        <Route path="record-demo" element={<RecordDemoPage />} />
        <Route path="record-result/:mode" element={<RecordedSamplePage />} />
        <Route path="project" element={<ProjectPage />} />
        <Route path="cctv" element={<CCTVPage />} />
        <Route path="demand" element={<DemandPage />} />
        <Route path="optimization" element={<OptimizationPage />} />
        <Route path="network" element={<NetworkPage />} />
        <Route path="simulator" element={<SimulatorPage />} />
        <Route path="recommendations" element={<RecommendationsPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="fleet" element={<FleetPage />} />
        <Route path="safety" element={<SafetyPage />} />
        <Route path="accounts" element={<AccountsPage />} />
        <Route path="vision-overview" element={<HomePage />} />
        <Route path="image"     element={<ImageAnalyzerPage />} />
        <Route path="human"     element={<HumanAnalyzerPage />} />
        <Route path="ship"      element={<ShipAnalyzerPage />} />
        <Route path="container" element={<ContainerAnalyzerPage />} />
        <Route path="combined"  element={<CombinedAnalyzerPage />} />
        <Route path="webcam" element={<WebcamPage />} />
        <Route path="video"     element={<VideoAnalyzerPage />} />
        <Route path="models"    element={<ModelCenterPage />} />
        <Route path="history"   element={<HistoryPage />} />
        <Route path="*"         element={<Navigate to="/" replace />} />
      </Route>
    </Routes></Suspense></ModuleErrorBoundary></DemoRecorderProvider></ThemeProvider>
  );
}
