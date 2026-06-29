/**
 * ChatGPT OAuth API client — OpenAI's proprietary device-auth flow.
 * 
 * NOTE: api.client.ts prepends /api automatically.
 */
import { api } from "./client";

export interface DeviceCodeResponse {
  device_auth_id: string;
  user_code: string;
  verification_uri: string;
  interval: number;
}

export interface TokenPollResponse {
  status: "pending" | "authorized" | "expired" | "denied" | "error";
  access_token: string;
  refresh_token: string;
  expires_in: number;
  message: string;
}

export interface AuthStatusResponse {
  connected: boolean;
  provider_id: number;
  expires_at: number;
  has_refresh_token: boolean;
  model: string;
}

export const chatgptOAuth = {
  async startDeviceCode(): Promise<DeviceCodeResponse> {
    const r = await api.post("/auth/chatgpt/device-code");
    return r as DeviceCodeResponse;
  },

  async pollToken(
    device_auth_id: string,
    user_code: string,
    interval: number,
    provider_id: number,
  ): Promise<TokenPollResponse> {
    const r = await api.post("/auth/chatgpt/token", {
      device_auth_id,
      user_code,
      interval,
      provider_id,
    });
    return r as TokenPollResponse;
  },

  async getStatus(provider_id: number): Promise<AuthStatusResponse> {
    const r = await api.get(`/auth/chatgpt/status?provider_id=${provider_id}`);
    return r as AuthStatusResponse;
  },

  async refresh(provider_id: number): Promise<AuthStatusResponse> {
    const r = await api.post(`/auth/chatgpt/refresh?provider_id=${provider_id}`, {});
    return r as AuthStatusResponse;
  },

  async logout(provider_id: number): Promise<void> {
    await api.delete(`/auth/chatgpt/logout/${provider_id}`);
  },
};
