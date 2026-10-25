import { createBrowserRouter, Navigate } from "react-router";

import { AppShell, type NavItem } from "@/components/layout/AppShell";
import { ForbiddenPage, HomePage, NotFoundPage, PlaceholderPage } from "@/features/system/pages";

// Routes and navigation follow FRONTEND_SPEC.md § 4. Role guards come with login (TCK-0110).

const adminNav: NavItem[] = [
  { to: "/admin/users", label: "Users" },
  { to: "/admin/groups", label: "Groups" },
  { to: "/admin/exams", label: "Exams" },
  { to: "/admin/settings", label: "Settings" },
  { to: "/admin/audit", label: "Audit log" },
];

const teacherNav: NavItem[] = [
  { to: "/teacher", label: "Dashboard", end: true },
  { to: "/teacher/questions", label: "Questions" },
  { to: "/teacher/exams", label: "Exams" },
];

const studentNav: NavItem[] = [
  { to: "/student", label: "Dashboard", end: true },
  { to: "/student/results", label: "Results" },
];

export const router = createBrowserRouter([
  { path: "/", element: <HomePage /> },
  { path: "/login", element: <PlaceholderPage title="Log in" ticket="TCK-0110" /> },
  {
    path: "/admin",
    element: <AppShell roleLabel="Admin" nav={adminNav} layout="sidebar" />,
    children: [
      { index: true, element: <Navigate to="users" replace /> },
      { path: "users", element: <PlaceholderPage title="Users" ticket="TCK-0305" /> },
      { path: "groups", element: <PlaceholderPage title="Groups" ticket="TCK-0305" /> },
      { path: "exams", element: <PlaceholderPage title="Exams" ticket="TCK-0305" /> },
      { path: "settings", element: <PlaceholderPage title="Settings" ticket="TCK-0305" /> },
      { path: "audit", element: <PlaceholderPage title="Audit log" ticket="TCK-0305" /> },
    ],
  },
  {
    path: "/teacher",
    element: <AppShell roleLabel="Teacher" nav={teacherNav} layout="sidebar" />,
    children: [
      { index: true, element: <PlaceholderPage title="Dashboard" ticket="TCK-0507" /> },
      { path: "questions", element: <PlaceholderPage title="Questions" ticket="TCK-0408" /> },
      { path: "exams", element: <PlaceholderPage title="Exams" ticket="TCK-0507" /> },
    ],
  },
  {
    path: "/student",
    element: <AppShell roleLabel="Student" nav={studentNav} layout="topbar" />,
    children: [
      { index: true, element: <PlaceholderPage title="Dashboard" ticket="TCK-0613" /> },
      { path: "results", element: <PlaceholderPage title="Results" ticket="TCK-0910" /> },
    ],
  },
  { path: "/403", element: <ForbiddenPage /> },
  { path: "*", element: <NotFoundPage /> },
]);
