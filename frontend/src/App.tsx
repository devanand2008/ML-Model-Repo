import AuthGate from "./components/AuthGate";
import { Routes, Route, Navigate } from "react-router-dom";
import WebcamPage from "./pages/WebcamPage";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import ImageAnalyzerPage from "./pages/ImageAnalyzerPage";
import HumanAnalyzerPage from "./pages/HumanAnalyzerPage";
import ShipAnalyzerPage from "./pages/ShipAnalyzerPage";
import ContainerAnalyzerPage from "./pages/ContainerAnalyzerPage";
import CombinedAnalyzerPage from "./pages/CombinedAnalyzerPage";
import VideoAnalyzerPage from "./pages/VideoAnalyzerPage";
import ModelCenterPage from "./pages/ModelCenterPage";
import HistoryPage from "./pages/HistoryPage";

export default function App() {
  return (
    <AuthGate><Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
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
    </Routes></AuthGate>
  );
}
