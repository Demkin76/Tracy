import { createContext, useContext } from "react";
import type { Agent, Config } from "./api";
export type User = { user_id: string; email: string; name: string };
export type Session = { agent: Agent; key: CryptoKey };
export const Context = createContext<{
  config: Config | null;
  agents: Agent[];
  refresh: () => Promise<void>;
  session: Session | null;
  setSession: React.Dispatch<React.SetStateAction<Session | null>>;
  user: User;
  updateUser: (user: User) => void;
  logout: () => Promise<void>;
}>(null!);
export const useApp = () => useContext(Context);
