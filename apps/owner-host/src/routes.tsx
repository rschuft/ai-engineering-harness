import { Navigate, type RouteObject } from "react-router";
import { OwnerShell } from "./shell/OwnerShell";
import { ChatArea } from "./areas/ChatArea";
import { WorkArea } from "./areas/WorkArea";
import { EngineeringArea } from "./areas/EngineeringArea";
import { NotFound } from "./areas/NotFound";
import { DEFAULT_AREA_PATH } from "./areas";

/**
 * Route table of the Owner host. Every area renders inside OwnerShell, so the
 * navigation and the session identity stay mounted while the area changes.
 * U-01.2 adds outcome-to-session selection under /engineering; nothing here
 * selects a session yet.
 */
export const ownerRoutes: RouteObject[] = [
  {
    path: "/",
    element: <OwnerShell />,
    children: [
      { index: true, element: <Navigate to={DEFAULT_AREA_PATH} replace /> },
      { path: "chat", element: <ChatArea /> },
      { path: "work", element: <WorkArea /> },
      { path: "engineering", element: <EngineeringArea /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];
