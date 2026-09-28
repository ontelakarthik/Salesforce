import { createSlice, nanoid, type PayloadAction } from "@reduxjs/toolkit";

/** App-wide success/info toasts — e.g. "Lead saved successfully." /
 * "Account saved successfully." (see NewLeadModal.tsx/NewAccountModal.tsx).
 * A tiny Redux slice rather than a one-off component-local flag so any
 * component can raise one (dispatch(showToast(...))) without prop-drilling a
 * callback through Leads.tsx/Accounts.tsx — rendered once, globally, by
 * Toast.tsx (mounted in Shell.tsx). A plain array (not a single message) so
 * two toasts raised in quick succession (e.g. "New Account" inline-creating
 * an Account, then the Lead itself, from NewLeadModal) both get seen instead
 * of the second clobbering the first. */
export interface ToastItem {
  id: string;
  message: string;
}

export interface ToastState {
  items: ToastItem[];
}

const initialState: ToastState = {
  items: [],
};

const toastSlice = createSlice({
  name: "toast",
  initialState,
  reducers: {
    showToast: {
      reducer(state, action: PayloadAction<ToastItem>) {
        state.items.push(action.payload);
      },
      prepare(message: string) {
        return { payload: { id: nanoid(), message } };
      },
    },
    dismissToast(state, action: PayloadAction<string>) {
      state.items = state.items.filter((t) => t.id !== action.payload);
    },
  },
});

export const { showToast, dismissToast } = toastSlice.actions;
export default toastSlice.reducer;
