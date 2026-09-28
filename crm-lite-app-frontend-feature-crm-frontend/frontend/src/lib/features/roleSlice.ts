import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { Role } from "@/components/clm/data";
import { loadPersistedAuth, loginSuccess, logout } from "./authSlice";

export interface RoleState {
  value: Role;
}

/** Most-to-least privileged — an employee with multiple real roles (see
 * admin_service.set_employee_roles()) shows as their highest one here, the
 * same way this "current role" has always driven nav/RoleOnly gating. */
const PRECEDENCE: Role[] = ["ADMIN", "LEADERSHIP", "ACCOUNT_EXEC", "SALES"];

function highestRole(codes: string[]): Role {
  return PRECEDENCE.find((r) => codes.includes(r)) ?? "SALES";
}

// A returning user's session is restored directly into authSlice's initial
// state (see loadPersistedAuth) without dispatching loginSuccess — mirror
// that here so a page reload doesn't lose the real-role sync below.
const initialState: RoleState = {
  value: highestRole(loadPersistedAuth().employee?.roles ?? []),
};

const roleSlice = createSlice({
  name: "role",
  initialState,
  reducers: {
    setRole(state, action: PayloadAction<Role>) {
      state.value = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      // The real login is the source of truth for what a user can actually
      // do — default the "viewing as" simulation (see Topbar.tsx) to their
      // real highest role so nav/RoleOnly gating (which all read this same
      // state.role.value) works correctly out of the box. An admin can
      // still flip the switcher afterward to preview a different role.
      .addCase(loginSuccess, (state, action) => {
        state.value = highestRole(action.payload.employee.roles);
      })
      .addCase(logout, (state) => {
        state.value = "SALES";
      });
  },
});

export const { setRole } = roleSlice.actions;
export default roleSlice.reducer;
