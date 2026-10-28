import type { ComponentType } from "react";
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

// Routes and navigation follow FRONTEND_SPEC.md § 4. Role areas are guarded by RequireRole; the
// server checks every request regardless.

/** A page loaded only when opened, so each role downloads just its own pages. */
function page<K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) {
  return async () => ({ Component: (await load())[name] });
}

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
      {
        path: "/theme",
        lazy: page(() => import("@/features/system/ThemePreviewPage"), "ThemePreviewPage"),
      },
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
          { path: "users", lazy: page(() => import("@/features/admin/UsersPage"), "UsersPage") },
          {
            path: "users/:userId",
            lazy: page(() => import("@/features/admin/UserDetailPage"), "UserDetailPage"),
          },
          { path: "groups", lazy: page(() => import("@/features/admin/GroupsPage"), "GroupsPage") },
          {
            path: "groups/:groupId",
            lazy: page(() => import("@/features/admin/GroupDetailPage"), "GroupDetailPage"),
          },
          // The admin exam list needs the exam API (TCK-0502); the page comes with it.
          { path: "exams", element: <PlaceholderPage title="Exams" ticket="TCK-0502" /> },
          {
            path: "settings",
            lazy: page(() => import("@/features/admin/SettingsPage"), "SettingsPage"),
          },
          { path: "audit", lazy: page(() => import("@/features/admin/AuditPage"), "AuditPage") },
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
