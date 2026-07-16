// @ts-ignore
/* eslint-disable */
import { request } from "@umijs/max";

/** Change Password POST /api/v1/auth/change-password */
export async function authChangePassword(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.authChangePasswordParams,
  body: API.ChangePasswordRequest,
  options?: { [key: string]: any }
) {
  return request<API.SuccessResponse>("/api/v1/auth/change-password", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    params: { ...params },
    data: body,
    ...(options || {}),
  });
}

/** Login POST /api/v1/auth/login */
export async function authLogin(
  body: API.LoginRequest,
  options?: { [key: string]: any }
) {
  return request<API.LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    data: body,
    ...(options || {}),
  });
}

/** Logout POST /api/v1/auth/logout */
export async function authLogout(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.authLogoutParams,
  options?: { [key: string]: any }
) {
  return request<API.SuccessResponse>("/api/v1/auth/logout", {
    method: "POST",
    params: { ...params },
    ...(options || {}),
  });
}

/** Me GET /api/v1/auth/me */
export async function authMe(
  // 叠加生成的Param类型 (非body参数swagger默认没有生成对象)
  params: API.authMeParams,
  options?: { [key: string]: any }
) {
  return request<API.AdminProfile>("/api/v1/auth/me", {
    method: "GET",
    params: { ...params },
    ...(options || {}),
  });
}
