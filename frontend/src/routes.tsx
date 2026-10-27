import { createBrowserRouter, Navigate, Outlet } from "react-router";

import { AuthProvider, RequireRole, RootRedirect } from "@/auth/AuthProvider";

import { AppShell, type NavItem } from "@/components/layout/AppShell";
import { LoginPage } from "@/features/auth/LoginPage";
import {
  ActivatePage,
  ForgotPasswordPage,
  ResetPasswordPage,
} from "@/features/auth/SetPasswordPages";
import { ForbiddenPage, NotFoundPage, PlaceholderPage } from "@/features/system/pages";
import { ThemePreviewPage } from "@/features/system/ThemePreviewPage";

// Routes and navigation follow FRONTEND_SPEC.md § 4. Role areas are guarded by RequireRole; the
// server checks every request regardless.

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
  {
    // Every page sits inside the AuthProvider, which restores the session after a reload.
    element: (
      <AuthProvider>
        <Outlet />
      </AuthProvider>
    ),
    children: [
      { path: "/", element: <RootRedirect /> },
      { path: "/theme", element: <ThemePreviewPage /> },
      { path: "/login", element: <LoginPage /> },
      { path: "/activate", element: <ActivatePage /> },
      { path: "/forgot-password", element: <ForgotPasswordPage /> },
      { path: "/reset-password", element: <ResetPasswordPage /> },
      {
        path: "/admin",
        element: (
          <RequireRole role="ADMIN">
            <AppShell roleLabel="Admin" nav={adminNav} layout="sidebar" />
          </RequireRole>
        ),
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
        element: (
          <RequireRole role="TEACHER">
            <AppShell roleLabel="Teacher" nav={teacherNav} layout="sidebar" />
          </RequireRole>
        ),
        children: [
          { index: true, element: <PlaceholderPage title="Dashboard" ticket="TCK-0507" /> },
          { path: "questions", element: <PlaceholderPage title="Questions" ticket="TCK-0408" /> },
          { path: "exams", element: <PlaceholderPage title="Exams" ticket="TCK-0507" /> },
        ],
      },
      {
        path: "/student",
        element: (
          <RequireRole role="STUDENT">
            <AppShell roleLabel="Student" nav={studentNav} layout="topbar" />
          </RequireRole>
        ),
        children: [
          { index: true, element: <PlaceholderPage title="Dashboard" ticket="TCK-0613" /> },
          { path: "results", element: <PlaceholderPage title="Results" ticket="TCK-0910" /> },
        ],
      },
      { path: "/403", element: <ForbiddenPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
