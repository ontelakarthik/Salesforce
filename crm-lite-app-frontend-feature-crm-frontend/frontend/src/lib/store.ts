import { configureStore } from "@reduxjs/toolkit";
import appReducer from "./features/appSlice";
import authReducer from "./features/authSlice";
import roleReducer from "./features/roleSlice";
import toastReducer from "./features/toastSlice";

export function makeStore() {
  return configureStore({
    reducer: {
      role: roleReducer,
      app: appReducer,
      auth: authReducer,
      toast: toastReducer,
    },
  });
}

export type AppStore = ReturnType<typeof makeStore>;
export type RootState = ReturnType<AppStore["getState"]>;
export type AppDispatch = AppStore["dispatch"];

/** A genuine singleton, not per-component-instance like the old
 * `useState(() => makeStore())` in StoreProvider — this is a client-only,
 * SPA-style app (no server-rendered data flows through the store), so
 * there's no per-request-isolation concern a typical Next.js SSR app would
 * have. client.ts needs a stable instance to read the current auth token
 * from outside React (see request()'s Authorization header logic). */
export const store = makeStore();

if (typeof window !== "undefined") {
  let lastAuth = store.getState().auth;
  store.subscribe(() => {
    const auth = store.getState().auth;
    if (auth !== lastAuth) {
      lastAuth = auth;
      window.localStorage.setItem("crmlite.auth", JSON.stringify(auth));
    }
  });
}
