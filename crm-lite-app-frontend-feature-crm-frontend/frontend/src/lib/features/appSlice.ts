import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { AppId } from "@/components/clm/apps";

export interface AppState {
  value: AppId;
}

// Default MUST stay "CLM" — every existing user's nav/rail/route access
// resolves identically to pre-App-Launcher behavior until they explicitly
// open the launcher and switch.
const initialState: AppState = {
  value: "CLM",
};

const appSlice = createSlice({
  name: "app",
  initialState,
  reducers: {
    setApp(state, action: PayloadAction<AppId>) {
      state.value = action.payload;
    },
  },
});

export const { setApp } = appSlice.actions;
export default appSlice.reducer;
