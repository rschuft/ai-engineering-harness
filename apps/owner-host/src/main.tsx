import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { OwnerApp } from "./App";
import { ownerRoutes } from "./routes";
import "./shell/shell.css";

const container = document.getElementById("root");
if (!container) throw new Error("Owner host: #root element missing from index.html");

createRoot(container).render(
  <StrictMode>
    <OwnerApp router={createBrowserRouter(ownerRoutes)} />
  </StrictMode>,
);
