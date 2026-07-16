// @ts-ignore
/* eslint-disable */
import { request } from "@umijs/max";

/** Dependencies GET /api/v1/health/dependencies */
export async function healthDependencies(options?: { [key: string]: any }) {
  return request<API.DependencyHealthResponse>("/api/v1/health/dependencies", {
    method: "GET",
    ...(options || {}),
  });
}

/** Live GET /api/v1/health/live */
export async function healthLive(options?: { [key: string]: any }) {
  return request<API.HealthResponse>("/api/v1/health/live", {
    method: "GET",
    ...(options || {}),
  });
}

/** Ready GET /api/v1/health/ready */
export async function healthReady(options?: { [key: string]: any }) {
  return request<API.DependencyHealthResponse>("/api/v1/health/ready", {
    method: "GET",
    ...(options || {}),
  });
}
