/** The Owner's three areas, in navigation order. */
export const AREAS = [
  { id: "chat", path: "/chat", label: "Chat", summary: "Conversation with AI Engineering" },
  { id: "work", path: "/work", label: "Work", summary: "Objectives and Work" },
  { id: "engineering", path: "/engineering", label: "Engineering", summary: "Engineering sessions in Agent Canvas" },
] as const;

export type AreaId = (typeof AREAS)[number]["id"];

export const DEFAULT_AREA_PATH = AREAS[0].path;
