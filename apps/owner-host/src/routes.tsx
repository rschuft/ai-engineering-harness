import { Navigate, type RouteObject } from "react-router";
import { OwnerShell } from "./shell/OwnerShell";
import { ChatArea } from "./areas/ChatArea";
import { WorkArea } from "./areas/WorkArea";
import { EngineeringArea } from "./areas/EngineeringArea";
import { EngineeringSession } from "./engineering/EngineeringSession";
import { ENGINEERING_SESSION_ROUTE } from "./engineering/session-detail";
import { NotFound } from "./areas/NotFound";
import { SignIn } from "./identity/SignIn";
import { DEFAULT_AREA_PATH } from "./areas";

/**
 * Route table of the Owner host. Every area renders inside OwnerShell, so the
 * navigation and the session identity stay mounted while the area changes.
 * U-01.2: an outcome's engineering session is selected by its own address,
 * /engineering/outcomes/<outcome id>/sessions/<conversation id>, so a refresh
 * keeps it (src/engineering/EngineeringSession.tsx). /sign-in is the login to the Integration process
 * (U-01.3): not an area, so it is not in the navigation.
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
      { path: ENGINEERING_SESSION_ROUTE, element: <EngineeringSession /> },
      { path: "sign-in", element: <SignIn /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];
